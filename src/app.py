"""Interface Streamlit : entretien de collecte, annuaire/cartographie, et
(à venir) assistant RAG. Authentification par email sans mot de passe —
via Supabase OTP si `SUPABASE_URL`/`SUPABASE_KEY` sont configurés, sinon un
mode développement local (identification simple, sans vérification) pour
travailler sans compte Supabase.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.agent.collecte_agent import CollecteAgent, opening_message
from src.agent.collecte_tools import CollecteToolHandler
from src.annuaire import (
    SECTIONS_SYNTHESE,
    build_annuaire,
    default_visual,
    lieux_avec_coordonnees,
    source_items_for_section,
)
from src.db.factory import get_admin_store, get_store
from src.questionnaire.schema import Role

RAG_DISPONIBLE = bool(os.environ.get("VOYAGE_API_KEY"))

load_dotenv()
st.set_page_config(page_title="Lieux hybrides et territoires", layout="wide")

# Contournement d'authentification STRICTEMENT réservé au développement local.
# ⚠️ Ne JAMAIS définir LOCAL_DEV_AUTOLOGIN dans les secrets Streamlit Cloud (ou
# tout environnement accessible publiquement) — quiconque ouvrirait l'app
# aurait alors un accès admin complet sans vérification d'email.
LOCAL_DEV_AUTOLOGIN = os.environ.get("LOCAL_DEV_AUTOLOGIN", "").lower() in ("1", "true", "yes")
LOCAL_DEV_ADMIN_EMAIL = os.environ.get("LOCAL_DEV_ADMIN_EMAIL", "admin@localhost")

SUPABASE_CONFIGURED = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def _supabase_client():
    """Un seul client Supabase par session Streamlit, réutilisé à chaque
    rerun — indispensable pour que la session posée par verify_otp() reste
    active (un client recréé à chaque rerun repartirait anonyme, et les
    policies RLS `auth.role() = 'authenticated'` rejetteraient tout)."""
    if "supabase_client" not in st.session_state:
        from supabase import create_client
        st.session_state["supabase_client"] = create_client(
            os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
        )
    return st.session_state["supabase_client"]


def auth_screen() -> str | None:
    """Renvoie l'identifiant utilisateur une fois authentifié, sinon None
    (et affiche l'écran de connexion)."""
    if "user_id" in st.session_state:
        return st.session_state["user_id"]

    if LOCAL_DEV_AUTOLOGIN:
        # Connexion admin immédiate, sans passer par Supabase Auth — utilise
        # get_admin_store() (clé service_role, contourne RLS) plutôt qu'un
        # client anonyme qui serait de toute façon rejeté par les policies.
        st.session_state["user_id"] = LOCAL_DEV_ADMIN_EMAIL
        st.session_state["use_admin_store"] = True
        return st.session_state["user_id"]

    st.title("Lieux hybrides et territoires")

    if not SUPABASE_CONFIGURED:
        st.info(
            "Mode développement local : aucun projet Supabase configuré "
            "(`SUPABASE_URL`/`SUPABASE_KEY` absents de `.env`). L'identification "
            "ci-dessous n'est pas vérifiée — pratique pour tester, à remplacer "
            "par le vrai flux Supabase en production."
        )
        with st.form("dev_login_form"):
            email = st.text_input("Votre email")
            submitted = st.form_submit_button("Continuer")
        if submitted and email:
            st.session_state["user_id"] = email
            st.rerun()
        return None

    client = _supabase_client()

    if "otp_sent_to" not in st.session_state:
        with st.form("otp_request_form"):
            email = st.text_input("Votre email")
            submitted = st.form_submit_button("Recevoir un code de connexion")
        if submitted and email:
            try:
                client.auth.sign_in_with_otp({"email": email})
                st.session_state["otp_sent_to"] = email
                st.rerun()
            except Exception as exc:
                message = str(exc)
                if "security purposes" in message or "rate limit" in message.lower():
                    st.warning(
                        "Une demande a déjà été envoyée récemment pour cet email — "
                        "Supabase impose un délai anti-spam d'environ 60 secondes entre "
                        "deux demandes. Patientez une minute sans recliquer, puis réessayez "
                        "une seule fois."
                    )
                else:
                    st.error(f"Échec de l'envoi du code de connexion : {message}")
        return None

    st.write(f"Un code a été envoyé à **{st.session_state['otp_sent_to']}**.")
    with st.form("otp_verify_form"):
        code = st.text_input("Code reçu par email")
        col1, col2 = st.columns(2)
        with col1:
            verify = st.form_submit_button("Valider")
        with col2:
            change_email = st.form_submit_button("Changer d'email")
    if change_email:
        del st.session_state["otp_sent_to"]
        st.rerun()
    if verify and code:
        try:
            result = client.auth.verify_otp({
                "email": st.session_state["otp_sent_to"], "token": code.strip(), "type": "email",
            })
        except Exception as exc:
            st.error(f"Code invalide ou expiré : {exc}")
            return None
        if result.user:
            st.session_state["user_id"] = result.user.id
            st.rerun()
        else:
            st.error("Code invalide ou expiré.")
    return None


ROLE_LABELS = {
    "fondateur": "Fondateur·rice / porteur de projet",
    "equipe": "Équipe opérationnelle",
    "partenaire": "Partie prenante externe",
    "usager": "Usager régulier",
    "steward": "Steward (je continue à nourrir ce lieu)",
    "autre": "Autre",
}


def sidebar_lieu_et_role(store, user_id: str):
    st.sidebar.header("Votre contribution")
    # Tous les lieux recensés (pas seulement les siens) : n'importe quel
    # utilisateur connecté peut devenir contributeur/steward d'un lieu créé
    # par quelqu'un d'autre (cf. bouton "Continuer à nourrir" de l'Annuaire).
    tous_les_lieux = store.list_tiers_lieux()
    noms_existants = sorted(l.nom for l in tous_les_lieux)

    preselect_lieu = st.session_state.pop("preselect_lieu", None)
    preselect_role = st.session_state.pop("preselect_role", None)

    options_lieu = ["— Nouveau lieu —"] + noms_existants
    index_lieu = options_lieu.index(preselect_lieu) if preselect_lieu in options_lieu else 0
    choix = st.sidebar.selectbox("Tiers-lieu", options=options_lieu, index=index_lieu)
    if choix == "— Nouveau lieu —":
        nom_lieu = st.sidebar.text_input("Nom du nouveau lieu")
    else:
        nom_lieu = choix

    role_options = [r.value for r in Role]
    index_role = role_options.index(preselect_role) if preselect_role in role_options else 0
    role = st.sidebar.selectbox(
        "Votre rôle vis-à-vis de ce lieu",
        options=role_options,
        index=index_role,
        format_func=lambda r: ROLE_LABELS[r],
    )
    return nom_lieu, role


def entretien_tab(store, user_id: str, nom_lieu: str, role: str):
    if not nom_lieu:
        st.info("Choisissez ou créez un tiers-lieu dans la barre latérale pour démarrer.")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY n'est pas configuré (voir .env.example).")
        return

    session_key = f"agent::{nom_lieu}::{role}"
    if session_key not in st.session_state:
        tiers_lieu = store.get_or_create_tiers_lieu(user_id, nom_lieu)
        contributeur = store.get_or_create_contributeur(user_id, tiers_lieu.id, role)
        session = store.get_or_start_session(tiers_lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, tiers_lieu.id, contributeur.id, session, Role(role))
        agent = CollecteAgent(handler, store=store, tiers_lieu_id=tiers_lieu.id)
        st.session_state[session_key] = {"agent": agent, "history": []}
        opening = agent.send(opening_message(store, tiers_lieu.id))
        st.session_state[session_key]["history"].append(("assistant", opening))

    state = st.session_state[session_key]
    for speaker, text in state["history"]:
        with st.chat_message(speaker):
            st.write(text)

    user_text = st.chat_input("Votre réponse...")
    if user_text:
        state["history"].append(("user", user_text))
        with st.spinner("L'agent réfléchit..."):
            reply = state["agent"].send(user_text)
        state["history"].append(("assistant", reply))
        st.rerun()


def _lancer_enrichissement(store, lieu) -> None:
    if not os.environ.get("ANTHROPIC_API_KEY") or not RAG_DISPONIBLE:
        st.error("ANTHROPIC_API_KEY et VOYAGE_API_KEY sont nécessaires pour enrichir un lieu.")
        return
    from src.agent.enrichissement import enrich_lieu
    with st.spinner("Génération de la synthèse et du profil sémantique..."):
        result, updated = enrich_lieu(store, lieu.id, force=True, nom_lieu=lieu.nom)
    if result is None:
        st.warning("Aucune réponse à synthétiser pour ce lieu.")
    else:
        st.success("Synthèse mise à jour." if updated else "Déjà à jour.")
        st.rerun()


def _vignette_html(emoji: str, couleur: str) -> str:
    return (
        f'<div style="width:100%;aspect-ratio:16/9;border-radius:8px;background:{couleur};'
        f'display:flex;align-items:center;justify-content:center;font-size:2.5rem;">{emoji}</div>'
    )


def annuaire_tab(store):
    st.subheader("Annuaire des lieux recensés")
    fiches = build_annuaire(store)
    if not fiches:
        st.info("Aucun lieu recensé pour l'instant.")
        return

    coords = lieux_avec_coordonnees(store)
    if coords:
        st.map(pd.DataFrame(coords))

    for fiche in fiches:
        lieu = fiche["tiers_lieu"]
        derive = store.get_lieu_derive(lieu.id)
        donnees = derive.donnees if derive else {}

        with st.container(border=True):
            col_vignette, col_info, col_actions = st.columns([1, 3, 1.3])

            with col_vignette:
                if derive and derive.photo_url:
                    st.image(derive.photo_url, use_container_width=True)
                else:
                    emoji, couleur = default_visual(lieu.nom, donnees)
                    st.markdown(_vignette_html(emoji, couleur), unsafe_allow_html=True)

            with col_info:
                st.markdown(f"### {lieu.nom}")
                st.caption(
                    f"{lieu.pays or 'pays non renseigné'} — {lieu.region or 'région non renseignée'} · "
                    f"{fiche['nombre_contributeurs']} contributeur(s)"
                )
                if derive:
                    st.write(donnees.get("resume", ""))
                    if derive.lien_externe:
                        st.markdown(f"[🔗 Fiche externe]({derive.lien_externe})")
                else:
                    st.info("Pas encore de synthèse générée pour ce lieu.")

            with col_actions:
                bouton_label = "Ré-enrichir" if derive else "Finaliser ce lieu"
                if st.button(bouton_label, key=f"enrich_{lieu.id}", use_container_width=True):
                    _lancer_enrichissement(store, lieu)
                if st.button("Continuer à nourrir ce lieu", key=f"nourrir_{lieu.id}", use_container_width=True):
                    st.session_state["preselect_lieu"] = lieu.nom
                    st.session_state["preselect_role"] = "steward"
                    st.toast(f"« {lieu.nom} » sélectionné — rendez-vous dans l'onglet Entretien.", icon="🌱")

            if derive:
                st.divider()
                cols = st.columns(3)
                for i, (cle, titre) in enumerate(SECTIONS_SYNTHESE[1:]):  # sans "resume", déjà affiché
                    texte = donnees.get(cle) or "—"
                    with cols[i % 3]:
                        st.markdown(f"**{titre}**")
                        st.caption(texte)
                        sources = source_items_for_section(store, lieu.id, cle, derive)
                        if sources:
                            with st.popover("Sources", use_container_width=True):
                                for s in sources:
                                    st.markdown(f"**{s['label']}** : {s['valeur']}")

                with st.expander("Modifier le lien externe / la photo"):
                    with st.form(f"liens_{lieu.id}"):
                        nouveau_lien = st.text_input("Lien externe (ex. fiche tiers-lieux.xyz)",
                                                      value=derive.lien_externe or "")
                        nouvelle_photo = st.text_input("URL de la photo",
                                                        value=derive.photo_url or "")
                        if st.form_submit_button("Enregistrer"):
                            store.update_lieu_derive_liens(lieu.id, nouveau_lien or None, nouvelle_photo or None)
                            st.rerun()

            with st.expander("Voir toutes les réponses brutes et témoignages"):
                for label, entries in fiche["par_champ"].items():
                    valeurs = ", ".join(str(e["valeur"]) for e in entries)
                    st.markdown(f"**{label}** : {valeurs}")
                if fiche["temoignages"]:
                    st.markdown("**Témoignages libres**")
                    for t in fiche["temoignages"]:
                        st.markdown(f"> {t['texte']}")


def rag_tab(store):
    st.subheader("Assistant RAG")
    if not RAG_DISPONIBLE:
        st.info(
            "VOYAGE_API_KEY n'est pas configuré (voir .env.example) : l'assistant "
            "RAG a besoin des embeddings Voyage AI pour rechercher dans le corpus "
            "documentaire. Configurez la clé, déposez des fichiers dans data/raw/, "
            "lancez `python -m src.ingest.build_index`, puis revenez ici."
        )
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.error("ANTHROPIC_API_KEY n'est pas configuré (voir .env.example).")
        return

    if "rag_agent" not in st.session_state:
        from src.agent.rag_agent import RagAgent
        from src.agent.rag_tools import RagToolHandler

        st.session_state["rag_agent"] = RagAgent(RagToolHandler(store))
        st.session_state["rag_history"] = []

    for speaker, text in st.session_state["rag_history"]:
        with st.chat_message(speaker):
            st.write(text)

    question = st.chat_input("Posez une question sur les lieux recensés ou les documents déposés...")
    if question:
        st.session_state["rag_history"].append(("user", question))
        with st.spinner("Recherche en cours..."):
            reply = st.session_state["rag_agent"].send(question)
        st.session_state["rag_history"].append(("assistant", reply))
        st.rerun()


def main():
    user_id = auth_screen()
    if not user_id:
        return

    if st.session_state.get("use_admin_store"):
        store = get_admin_store()
        st.sidebar.warning("Mode admin local (LOCAL_DEV_AUTOLOGIN) — accès complet sans RLS.")
    else:
        supabase_client = st.session_state.get("supabase_client") if SUPABASE_CONFIGURED else None
        store = get_store(client=supabase_client)
    nom_lieu, role = sidebar_lieu_et_role(store, user_id)

    tab_entretien, tab_rag, tab_annuaire = st.tabs(["Entretien", "Assistant RAG", "Annuaire"])
    with tab_entretien:
        entretien_tab(store, user_id, nom_lieu, role)
    with tab_rag:
        rag_tab(store)
    with tab_annuaire:
        annuaire_tab(store)


if __name__ == "__main__":
    main()
