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
    build_fiche_lieu,
    default_visual,
    lieux_avec_coordonnees,
    source_items_for_section,
)
from src.auth_session import clear_session_cookie, read_session_cookie, save_session_cookie
from src.db.factory import get_admin_store, get_store
from src.db.store import Litige
from src.questionnaire.schema import QUESTIONNAIRE, CATEGORIES_POSSIBLES, Role, all_fields

ROLES_INTERNES = {"fondateur", "equipe", "steward"}

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

    if not SUPABASE_CONFIGURED:
        # Mode dev sans Supabase : pas de vraie sécurité de toute façon, donc
        # un cookie suffit à éviter de retaper son email à chaque visite.
        saved_email = read_session_cookie()
        if saved_email and "dev_cookie_declined" not in st.session_state:
            st.session_state["user_id"] = saved_email
            st.rerun()

        st.title("Lieux hybrides et territoires")
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
            save_session_cookie(email)
            st.rerun()
        return None

    client = _supabase_client()

    # Restaure une session déjà ouverte (cookie posé lors d'une connexion
    # précédente) avant d'afficher le moindre formulaire — évite de redemander
    # un email à chaque visite. `cookie_restore_failed` empêche de reboucler
    # indéfiniment si le refresh_token est expiré ou invalide.
    if "otp_sent_to" not in st.session_state and "cookie_restore_failed" not in st.session_state:
        refresh_token = read_session_cookie()
        if refresh_token:
            try:
                result = client.auth.refresh_session(refresh_token)
            except Exception:
                result = None
            if result and result.user:
                st.session_state["user_id"] = result.user.id
                if result.session and result.session.refresh_token:
                    save_session_cookie(result.session.refresh_token)
                st.rerun()
            else:
                st.session_state["cookie_restore_failed"] = True

    st.title("Lieux hybrides et territoires")

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
        st.session_state.pop("otp_sent_to", None)
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
            st.session_state.pop("otp_sent_to", None)
            st.session_state["user_id"] = result.user.id
            if result.session and result.session.refresh_token:
                save_session_cookie(result.session.refresh_token)
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

    tiers_lieu = store.get_or_create_tiers_lieu(user_id, nom_lieu)
    contributeur = store.get_or_create_contributeur(user_id, tiers_lieu.id, role)
    if contributeur.bloque:
        st.error(
            "Votre contribution à ce lieu a été suspendue par un administrateur ou un steward "
            "de ce lieu, suite à un signalement. Contactez l'équipe si vous pensez qu'il s'agit "
            "d'une erreur."
        )
        return

    session_key = f"agent::{nom_lieu}::{role}"
    if session_key not in st.session_state:
        # Le nom du lieu est déjà connu (saisi dans la barre latérale) : on le
        # pré-remplit comme réponse pour que l'entretien ne redemande jamais
        # "quel est le nom de votre lieu ?" en première question.
        if store.get_answers(tiers_lieu.id, contributeur.id).get("nom_lieu") is None:
            store.save_answer(tiers_lieu.id, contributeur.id, "nom_lieu", tiers_lieu.nom)
        session = store.get_or_start_session(tiers_lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, tiers_lieu.id, contributeur.id, session, Role(role))
        agent = CollecteAgent(handler, store=store, tiers_lieu_id=tiers_lieu.id)
        st.session_state[session_key] = {"agent": agent, "history": []}
        opening = agent.send(opening_message(
            store, tiers_lieu.id, nom_lieu=tiers_lieu.nom,
            contributeur_id=contributeur.id, role_label=ROLE_LABELS[role],
        ))
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


def _auto_enrich_one(store, lieu) -> None:
    """Ré-enrichissement automatique et silencieux d'UN SEUL lieu : plus de
    bouton manuel. `enrich_lieu` est idempotent (compare le hash des réponses
    source), donc peu coûteux dans le cas courant (déjà à jour) — appelé à
    l'ouverture de la fiche d'un lieu, jamais pour toute la grille d'un coup
    (24 lieux × 2 requêtes + hash à chaque affichage de l'Annuaire rendait la
    page très lente)."""
    if not (os.environ.get("ANTHROPIC_API_KEY") and RAG_DISPONIBLE):
        return
    from src.agent.enrichissement import enrich_lieu
    try:
        enrich_lieu(store, lieu.id, force=False, nom_lieu=lieu.nom)
    except Exception:
        pass  # une synthèse en échec ne doit jamais bloquer l'affichage de la fiche


def _vignette_html(emoji: str, couleur: str, hauteur: str = "9rem") -> str:
    return (
        f'<div style="width:100%;height:{hauteur};border-radius:8px;background:{couleur};'
        f'display:flex;align-items:center;justify-content:center;font-size:2.2rem;">{emoji}</div>'
    )


_CATEGORY_COLORS = {
    "Alimentaire": "#C97A3D", "Culturel": "#8B4B6B", "Éducation": "#3D6E8C", "Santé": "#4F7A52",
}


def _category_chips_html(categories: list) -> str:
    if not categories:
        return ""
    chips = "".join(
        f'<span style="background:{_CATEGORY_COLORS.get(c, "#888")};color:#fff;font-size:0.72rem;'
        f'padding:2px 8px;border-radius:10px;margin-right:4px;display:inline-block;'
        f'margin-bottom:4px;">{c}</span>'
        for c in categories
    )
    return f'<div style="margin:4px 0;">{chips}</div>'


@st.dialog("Fiche du lieu", width="large")
def _fiche_dialog(store, fiche, est_admin: bool, user_id: str):
    lieu = fiche["tiers_lieu"]
    if "fiche_enrichie" not in st.session_state:
        st.session_state["fiche_enrichie"] = set()
    if lieu.id not in st.session_state["fiche_enrichie"]:
        _auto_enrich_one(store, lieu)
        st.session_state["fiche_enrichie"].add(lieu.id)
    derive = store.get_lieu_derive(lieu.id)
    donnees = derive.donnees if derive else {}

    col_vignette, col_info = st.columns([1, 2.5])
    with col_vignette:
        if derive and derive.photo_url:
            st.image(derive.photo_url, use_container_width=True)
        else:
            emoji, couleur = default_visual(lieu.nom, donnees)
            st.markdown(_vignette_html(emoji, couleur, hauteur="10rem"), unsafe_allow_html=True)
    with col_info:
        st.markdown(f"### {lieu.nom}")
        st.caption(
            f"{lieu.pays or 'pays non renseigné'} — {lieu.region or 'région non renseignée'} · "
            f"{fiche['nombre_contributeurs']} contributeur(s)"
        )
        if donnees.get("categories"):
            st.markdown(_category_chips_html(donnees["categories"]), unsafe_allow_html=True)
        if derive:
            st.write(donnees.get("resume", ""))
            if derive.lien_externe:
                st.markdown(f"[🔗 Fiche externe]({derive.lien_externe})")
        else:
            st.info("Pas encore de synthèse générée pour ce lieu — répondez à quelques questions "
                     "dans l'onglet Entretien pour qu'elle apparaisse ici.")

    if st.button("🌱 Revendiquer le suivi de ce lieu (steward)", key=f"nourrir_{lieu.id}"):
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

    if est_admin:
        st.divider()
        _admin_portfolio_form(store, lieu, derive)

    contributeurs_lieu = store.list_contributeurs(lieu.id)
    mon_contributeur_interne = next(
        (c for c in contributeurs_lieu if c.user_id == user_id and c.role in ROLES_INTERNES and not c.bloque),
        None,
    )
    if est_admin or mon_contributeur_interne:
        st.divider()
        _historique_et_moderation(store, lieu, contributeurs_lieu, est_admin, user_id)


def _historique_et_moderation(store, lieu, contributeurs_lieu: list, est_admin: bool, user_id: str) -> None:
    with st.expander("Historique & modération"):
        st.markdown("**Contributeurs de ce lieu**")
        for c in contributeurs_lieu:
            col1, col2 = st.columns([4, 1])
            with col1:
                suffixe = " (vous)" if c.user_id == user_id else ""
                statut = " · 🚫 bloqué" if c.bloque else ""
                st.write(f"{ROLE_LABELS.get(c.role, c.role)} — `{c.user_id}`{suffixe}{statut}")
            with col2:
                if c.user_id == user_id:
                    pass
                elif c.bloque:
                    if st.button("Débloquer", key=f"unblock_{c.id}"):
                        get_admin_store().set_contributeur_bloque(c.id, False)
                        st.rerun()
                else:
                    if st.button("Bloquer", key=f"block_{c.id}"):
                        get_admin_store().set_contributeur_bloque(c.id, True, bloque_par=user_id)
                        st.rerun()

        st.markdown("**Signaler un litige**")
        options_cible = [None] + [c.id for c in contributeurs_lieu]
        labels_cible = {c.id: f"{ROLE_LABELS.get(c.role, c.role)} — {c.user_id}" for c in contributeurs_lieu}
        with st.form(f"litige_{lieu.id}", clear_on_submit=True):
            description = st.text_area("Description du désaccord")
            cible = st.selectbox("Contributeur concerné (optionnel)", options=options_cible,
                                  format_func=lambda cid: "—" if cid is None else labels_cible.get(cid, cid))
            if st.form_submit_button("Signaler"):
                if not description.strip():
                    st.error("Décrivez le désaccord avant de signaler.")
                else:
                    get_admin_store().save_litige(Litige(
                        tiers_lieu_id=lieu.id, description=description.strip(),
                        signale_par=user_id, contributeur_vise_id=cible,
                    ))
                    st.success("Litige signalé.")
                    st.rerun()

        litiges = store.list_litiges(lieu.id)
        if litiges:
            st.markdown("**Litiges**")
            for lit in litiges:
                col1, col2 = st.columns([4, 1])
                with col1:
                    marque = "🟢 résolu" if lit.statut == "resolu" else "🔴 ouvert"
                    st.write(f"{marque} — {lit.description}")
                with col2:
                    if est_admin and lit.statut == "ouvert":
                        if st.button("Résoudre", key=f"resoudre_{lit.id}"):
                            get_admin_store().resoudre_litige(lit.id)
                            st.rerun()

        st.markdown("**Historique récent**")
        historique = store.get_historique(lieu.id, limite=30)
        if not historique:
            st.caption("Aucun historique pour l'instant.")
        for h in historique:
            role = h.get("contributeur_role") or "?"
            champ = h.get("champ_id") or "note libre"
            statut_contrib = " 🚫" if h.get("contributeur_bloque") else ""
            st.caption(f"{h.get('cree_le', '')} — {role}{statut_contrib} — {champ} : {h.get('valeur')}")


def annuaire_tab(store, est_admin: bool, user_id: str):
    st.subheader("Annuaire des lieux recensés")
    lieux = store.list_tiers_lieux()
    if not lieux:
        st.info("Aucun lieu recensé pour l'instant.")
        return

    # La grille n'a besoin que de list_tiers_lieux + un batch de lieu_derive
    # (2 requêtes au total) — PAS de build_annuaire/build_fiche_lieu (qui
    # ajoutait 2 requêtes par lieu, pour des réponses brutes/témoignages qui
    # ne sont utiles que dans la fiche d'UN lieu ouvert, jamais dans la
    # grille). C'est cette fiche complète, calculée pour 24+ lieux à chaque
    # affichage, qui rendait l'Annuaire lent — elle n'est désormais calculée
    # que pour le lieu réellement ouvert dans le popup.
    derive_par_lieu = store.get_lieu_derive_batch([l.id for l in lieux])

    coords = lieux_avec_coordonnees(store)
    if coords:
        st.map(pd.DataFrame(coords))

    filtre_categories = st.multiselect("Filtrer par catégorie", options=CATEGORIES_POSSIBLES)

    lieux_affiches = lieux
    if filtre_categories:
        lieux_affiches = [
            l for l in lieux
            if (lambda d: d and set(d.donnees.get("categories") or []) & set(filtre_categories))(
                derive_par_lieu.get(l.id)
            )
        ]
    st.caption(f"{len(lieux_affiches)} lieu(x) affiché(s)")

    if "annuaire_open_lieu_id" in st.session_state:
        lieu_id = st.session_state.pop("annuaire_open_lieu_id")
        lieu_ouvert = next((l for l in lieux if l.id == lieu_id), None)
        if lieu_ouvert:
            _fiche_dialog(store, build_fiche_lieu(store, lieu_ouvert), est_admin, user_id)

    cols_par_ligne = 4
    for i in range(0, len(lieux_affiches), cols_par_ligne):
        cols = st.columns(cols_par_ligne)
        for col, lieu in zip(cols, lieux_affiches[i:i + cols_par_ligne]):
            derive = derive_par_lieu.get(lieu.id)
            donnees = derive.donnees if derive else {}
            with col:
                with st.container(border=True):
                    if derive and derive.photo_url:
                        st.image(derive.photo_url, use_container_width=True)
                    else:
                        emoji, couleur = default_visual(lieu.nom, donnees)
                        st.markdown(_vignette_html(emoji, couleur), unsafe_allow_html=True)
                    if donnees.get("categories"):
                        st.markdown(_category_chips_html(donnees["categories"]), unsafe_allow_html=True)
                    if st.button(lieu.nom, key=f"open_{lieu.id}", use_container_width=True):
                        st.session_state["annuaire_open_lieu_id"] = lieu.id
                        st.rerun()
                    st.caption(lieu.pays or "—")


def _admin_portfolio_form(store, lieu, derive) -> None:
    st.markdown("**Administration — Portfolio**")
    if derive is None:
        st.caption("Une synthèse doit d'abord être générée pour ce lieu avant de pouvoir "
                    "l'inclure au Portfolio.")
        return
    with st.form(f"portfolio_{lieu.id}"):
        inclus = st.checkbox("Inclure ce lieu dans le Portfolio public", value=bool(derive.inclus_portfolio))
        campagne_texte = st.text_area("Texte de campagne (appel, contexte des besoins)",
                                       value=derive.campagne_texte or "")
        col1, col2 = st.columns(2)
        with col1:
            campagne_objectif = st.text_input("Objectif (ex. montant recherché)",
                                                value=derive.campagne_objectif or "")
        with col2:
            campagne_contact = st.text_input("Contact", value=derive.campagne_contact or "")
        if st.form_submit_button("Enregistrer"):
            get_admin_store().update_portfolio_entry(
                lieu.id, inclus, campagne_texte or None, campagne_objectif or None, campagne_contact or None,
            )
            st.success("Portfolio mis à jour.")
            st.rerun()


def _condition_text(condition) -> str | None:
    if condition is None:
        return None
    op_labels = {"eq": "=", "ne": "≠", "in": "∈", "contains": "contient", "truthy": "renseigné"}
    label = op_labels.get(condition.operator, condition.operator)
    if condition.operator == "truthy":
        return f"{condition.field_id} {label}"
    return f"{condition.field_id} {label} {condition.value!r}"


def administration_tab(store, user_id: str) -> None:
    st.subheader("Administration")
    admin_store = get_admin_store()

    with st.expander("Comptes administrateurs", expanded=False):
        emails = store.list_admin_emails()
        st.write(", ".join(emails) if emails else "Aucun admin listé.")
        with st.form("add_admin_form", clear_on_submit=True):
            nouvel_email = st.text_input("Email à promouvoir administrateur")
            if st.form_submit_button("Ajouter"):
                if admin_store.add_admin_by_email(nouvel_email.strip()):
                    st.success(f"{nouvel_email} est désormais administrateur.")
                    st.rerun()
                else:
                    st.error("Aucun compte trouvé avec cet email (l'utilisateur doit s'être déjà connecté "
                              "au moins une fois).")

    with st.expander("Campagnes prioritaires (recensement ciblé)", expanded=False):
        st.caption("Pendant leur fenêtre active, les champs listés sont proposés en priorité dans "
                    "l'entretien, avant la suite normale du questionnaire.")
        campagnes = store.list_campagnes_prioritaires()
        if campagnes:
            for c in campagnes:
                col1, col2 = st.columns([5, 1])
                with col1:
                    st.markdown(f"**{c.titre}** · {c.date_debut[:10]} → {c.date_fin[:10]} "
                                f"· {len(c.champ_ids)} champ(s)")
                    if c.description:
                        st.caption(c.description)
                with col2:
                    if st.button("Supprimer", key=f"del_campagne_{c.id}"):
                        admin_store.delete_campagne_prioritaire(c.id)
                        st.rerun()
        else:
            st.caption("Aucune campagne prioritaire pour l'instant.")

        tous_les_champs = {f.id: f"{f.id} — {f.label}" for _, _, f in all_fields()}
        with st.form("nouvelle_campagne_form", clear_on_submit=True):
            titre = st.text_input("Titre de la campagne")
            description = st.text_area("Description (optionnel)")
            champ_ids = st.multiselect("Champs prioritaires", options=list(tous_les_champs.keys()),
                                        format_func=lambda cid: tous_les_champs[cid])
            col1, col2 = st.columns(2)
            with col1:
                date_debut = st.date_input("Début")
            with col2:
                date_fin = st.date_input("Fin")
            if st.form_submit_button("Créer la campagne"):
                if not titre or not champ_ids:
                    st.error("Titre et au moins un champ sont requis.")
                else:
                    from src.db.store import CampagnePrioritaire
                    admin_store.save_campagne_prioritaire(CampagnePrioritaire(
                        titre=titre, description=description or None, champ_ids=champ_ids,
                        date_debut=date_debut.isoformat(), date_fin=date_fin.isoformat(), cree_par=user_id,
                    ))
                    st.success("Campagne créée.")
                    st.rerun()

    with st.expander("Schéma de l'entretien (lecture seule)", expanded=False):
        for module in QUESTIONNAIRE:
            st.markdown(f"#### {module.title} {'· optionnel' if module.optional else '· obligatoire'}")
            for section in module.sections:
                cond = _condition_text(section.condition)
                titre_section = f"{section.title}" + (f" — actif si {cond}" if cond else "")
                with st.expander(titre_section):
                    for f in section.fields:
                        roles = ", ".join(r.value for r in f.roles) if f.roles else "tous rôles"
                        fcond = _condition_text(f.condition)
                        ligne = f"`{f.id}` — {f.label} ({f.type.value}, {roles}"
                        ligne += ", requis)" if f.required else ")"
                        if fcond:
                            ligne += f" — actif si {fcond}"
                        st.markdown(ligne)


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

        try:
            st.session_state["rag_agent"] = RagAgent(RagToolHandler(store))
            st.session_state["rag_history"] = []
        except Exception as exc:
            # L'initialisation de ChromaDB (index vectoriel local) peut échouer
            # sur certains environnements (ex. état du disque après un reboot) —
            # ne doit jamais faire planter tout le script (et donc les autres
            # onglets, qui s'exécutent dans le même passage) pour un onglet
            # secondaire.
            st.error(f"Assistant RAG temporairement indisponible : {exc}")
            return

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

    if st.sidebar.button("Se déconnecter"):
        clear_session_cookie()
        for key in ("user_id", "otp_sent_to", "cookie_restore_failed", "use_admin_store", "supabase_client"):
            st.session_state.pop(key, None)
        st.rerun()

    nom_lieu, role = sidebar_lieu_et_role(store, user_id)
    # En LOCAL_DEV_AUTOLOGIN, le store est déjà admin (service_role) : pas de
    # table `admins` à consulter, l'accès complet est déjà acquis par construction.
    est_admin = bool(st.session_state.get("use_admin_store")) or store.is_admin(user_id)

    onglets = ["Entretien", "Assistant RAG", "Annuaire"]
    if est_admin:
        onglets.append("Administration")
    tabs = st.tabs(onglets)

    # `st.tabs` ne crée pas de contextes d'exécution isolés : tous les onglets
    # sont rendus dans le même passage de script. Un bug non intercepté dans
    # UN SEUL onglet (ex. RAG) arrêterait sinon tout le script avant même
    # d'atteindre les onglets suivants — l'Annuaire pourrait ainsi sembler
    # "vide" alors que le vrai problème est ailleurs. Chaque onglet est donc
    # rendu défensivement : une erreur y reste locale, affichée sur place,
    # sans jamais empêcher les autres de s'afficher normalement.
    def _rendre_isole(nom_onglet: str, fonction, *args) -> None:
        try:
            fonction(*args)
        except Exception as exc:
            st.error(f"L'onglet « {nom_onglet} » a rencontré une erreur : {exc}")

    with tabs[0]:
        _rendre_isole("Entretien", entretien_tab, store, user_id, nom_lieu, role)
    with tabs[1]:
        _rendre_isole("Assistant RAG", rag_tab, store)
    with tabs[2]:
        _rendre_isole("Annuaire", annuaire_tab, store, est_admin, user_id)
    if est_admin:
        with tabs[3]:
            _rendre_isole("Administration", administration_tab, store, user_id)


if __name__ == "__main__":
    main()
