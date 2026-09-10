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

from src.agent.collecte_agent import CollecteAgent
from src.agent.collecte_tools import CollecteToolHandler
from src.annuaire import build_annuaire, lieux_avec_coordonnees
from src.db.factory import get_store
from src.questionnaire.schema import Role

RAG_DISPONIBLE = bool(os.environ.get("VOYAGE_API_KEY"))

load_dotenv()
st.set_page_config(page_title="Lieux hybrides et territoires", layout="wide")

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


def _capture_magic_link_redirect() -> None:
    """Supabase renvoie le token dans le FRAGMENT de l'URL (#access_token=...),
    invisible côté serveur (Streamlit ne peut lire que la query string). Ce
    script convertit le fragment en paramètres de requête puis recharge la
    page — après quoi `st.query_params` peut les lire côté Python.

    `st.components.v1.html` exécute ce script dans une iframe isolée : il
    faut donc cibler `window.top` (la vraie fenêtre du navigateur), pas
    `window.location` qui ne renverrait que la pseudo-URL de l'iframe
    elle-même (toujours vide) — sans ça, rien ne se passait jamais."""
    st.components.v1.html(
        """
        <script>
        if (window.top.location.hash && window.top.location.hash.includes('access_token')) {
            const params = new URLSearchParams(window.top.location.hash.substring(1));
            const newUrl = window.top.location.pathname + '?' + params.toString();
            window.top.location.replace(newUrl);
        }
        </script>
        """,
        height=0,
    )


def _consume_magic_link_query_params(client) -> None:
    """Si l'URL contient access_token/refresh_token (déposés par le script
    ci-dessus après le clic sur le lien magique), pose la session Supabase et
    mémorise l'utilisateur dans st.session_state — AVANT de nettoyer l'URL.

    Ordre important : `st.query_params.clear()` peut déclencher un rerun de
    Streamlit avant même d'atteindre l'instruction suivante. Si l'id
    utilisateur n'était pas déjà en session_state à ce moment-là, ce rerun
    repartait du formulaire de connexion — la session Supabase était bien
    établie côté client, mais Streamlit "l'oubliait" aussitôt, d'où la
    boucle infinie."""
    params = st.query_params
    access_token = params.get("access_token")
    refresh_token = params.get("refresh_token")
    if not access_token or not refresh_token:
        return
    try:
        result = client.auth.set_session(access_token, refresh_token)
    except Exception as exc:
        st.query_params.clear()
        st.error(f"Le lien de connexion est invalide ou expiré : {exc}. Redemandez-en un nouveau ci-dessous.")
        return
    if not result.user:
        st.query_params.clear()
        st.error("La session n'a pas pu être établie (réponse Supabase sans utilisateur). Redemandez un lien.")
        return
    st.session_state["user_id"] = result.user.id  # mémorisé AVANT le clear()
    st.query_params.clear()
    st.rerun()


def auth_screen() -> str | None:
    """Renvoie l'identifiant utilisateur une fois authentifié, sinon None
    (et affiche l'écran de connexion)."""
    if "user_id" in st.session_state:
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
    _capture_magic_link_redirect()
    _consume_magic_link_query_params(client)

    if "magic_link_sent_to" not in st.session_state:
        with st.form("magic_link_form"):
            email = st.text_input("Votre email")
            submitted = st.form_submit_button("Recevoir le lien de connexion")
        if submitted and email:
            redirect_to = os.environ.get("APP_BASE_URL")
            options = {"email_redirect_to": redirect_to} if redirect_to else {}
            try:
                client.auth.sign_in_with_otp({"email": email, "options": options})
                st.session_state["magic_link_sent_to"] = email
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
                    st.error(f"Échec de l'envoi du lien de connexion : {message}")
        return None

    st.write(f"Un lien de connexion a été envoyé à **{st.session_state['magic_link_sent_to']}**.")
    st.caption("Cliquez sur le lien reçu par email — il vous ramènera directement ici, connecté.")
    if st.button("Changer d'email"):
        del st.session_state["magic_link_sent_to"]
        st.rerun()
    return None


def sidebar_lieu_et_role(store, user_id: str):
    st.sidebar.header("Votre contribution")
    lieux_existants = store.list_tiers_lieux(owner_user_id=user_id)
    noms_existants = [l.nom for l in lieux_existants]

    choix = st.sidebar.selectbox(
        "Tiers-lieu", options=["— Nouveau lieu —"] + noms_existants
    )
    if choix == "— Nouveau lieu —":
        nom_lieu = st.sidebar.text_input("Nom du nouveau lieu")
    else:
        nom_lieu = choix

    role = st.sidebar.selectbox(
        "Votre rôle vis-à-vis de ce lieu",
        options=[r.value for r in Role],
        format_func=lambda r: {
            "fondateur": "Fondateur·rice / porteur de projet",
            "equipe": "Équipe opérationnelle",
            "partenaire": "Partie prenante externe",
            "usager": "Usager régulier",
            "autre": "Autre",
        }[r],
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
        opening = agent.send("Bonjour, je suis prêt à commencer l'entretien.")
        st.session_state[session_key]["history"].append(("assistant", opening))

    state = st.session_state[session_key]
    for speaker, text in state["history"]:
        with st.chat_message(speaker):
            st.write(text)

    user_text = st.chat_input("Votre réponse...")
    if user_text:
        state["history"].append(("user", user_text))
        with st.chat_message("user"):
            st.write(user_text)
        reply = state["agent"].send(user_text)
        state["history"].append(("assistant", reply))
        with st.chat_message("assistant"):
            st.write(reply)


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
        with st.expander(f"{lieu.nom} — {fiche['nombre_contributeurs']} contributeur(s)"):
            st.write(f"Pays : {lieu.pays or 'non renseigné'} — Région : {lieu.region or 'non renseignée'}")

            derive = store.get_lieu_derive(lieu.id)
            col1, col2 = st.columns([3, 1])
            with col1:
                if derive:
                    st.caption(f"Synthèse générée le {derive.genere_le} ({derive.model})")
                    st.markdown(derive.donnees.get("resume", ""))
                else:
                    st.caption("Pas encore de synthèse générée pour ce lieu.")
            with col2:
                bouton_label = "Ré-enrichir" if derive else "Finaliser ce lieu"
                if st.button(bouton_label, key=f"enrich_{lieu.id}"):
                    if not os.environ.get("ANTHROPIC_API_KEY") or not RAG_DISPONIBLE:
                        st.error("ANTHROPIC_API_KEY et VOYAGE_API_KEY sont nécessaires pour enrichir un lieu.")
                    else:
                        from src.agent.enrichissement import enrich_lieu
                        with st.spinner("Génération de la synthèse et du profil sémantique..."):
                            result, updated = enrich_lieu(store, lieu.id, force=True, nom_lieu=lieu.nom)
                        if result is None:
                            st.warning("Aucune réponse à synthétiser pour ce lieu.")
                        else:
                            st.success("Synthèse mise à jour." if updated else "Déjà à jour.")
                            st.rerun()

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
        with st.chat_message("user"):
            st.write(question)
        reply = st.session_state["rag_agent"].send(question)
        st.session_state["rag_history"].append(("assistant", reply))
        with st.chat_message("assistant"):
            st.write(reply)


def main():
    user_id = auth_screen()
    if not user_id:
        return

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
