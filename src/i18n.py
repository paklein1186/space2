"""Traduction légère du "chrome" de l'interface (navigation, écran de
connexion, en-têtes de page, barre latérale) — pas le contenu du
questionnaire, ni les échanges avec l'agent, ni les fiches lieu, qui restent
en français pour l'instant : les traduire correctement demanderait soit de
dupliquer l'intégralité du schéma (121 champs) dans chaque langue, soit une
traduction à la volée par LLM à chaque affichage (coût et latence non
négligeables) — un choix d'ampleur différente, à trancher séparément si
besoin, pas embarqué silencieusement ici.

Même mécanique que le thème clair/sombre (src/theme.py) : un simple bouton
en barre latérale, mémorisé dans st.session_state ET dans un cookie (les
pages de src/pages/ sont des scripts indépendants, session_state seul ne
suffit pas à s'y propager de façon fiable)."""

from __future__ import annotations

import streamlit as st

LANG_DEFAULT = "fr"
LANGUAGES = ("fr", "en")

_TRANSLATIONS: dict[str, dict[str, str]] = {
    "nav.entretien": {"fr": "Compléter l'histoire", "en": "Complete the story"},
    "nav.bibliotheque": {"fr": "Bibliothèque", "en": "Library"},
    "nav.lieux_hybrides": {"fr": "Lieux hybrides", "en": "Hybrid spaces"},
    "nav.observatoire": {"fr": "Observatoire", "en": "Observatory"},
    "nav.portfolio": {"fr": "Portfolio", "en": "Portfolio"},
    "nav.administration": {"fr": "Administration", "en": "Administration"},

    "auth.title": {"fr": "Lieux hybrides et territoires", "en": "Hybrid spaces and territories"},
    "auth.email_label": {"fr": "Votre email", "en": "Your email"},
    "auth.send_code": {"fr": "Recevoir un code de connexion", "en": "Send a login code"},
    "auth.code_sent": {"fr": "Un code a été envoyé à **{email}**.", "en": "A code was sent to **{email}**."},
    "auth.code_label": {"fr": "Code reçu par email", "en": "Code received by email"},
    "auth.verify": {"fr": "Valider", "en": "Verify"},
    "auth.change_email": {"fr": "Changer d'email", "en": "Change email"},
    "auth.invalid_code": {"fr": "Code invalide ou expiré.", "en": "Invalid or expired code."},

    "sidebar.connected_as": {"fr": "Connecté·e : {email}", "en": "Signed in as: {email}"},
    "sidebar.logout": {"fr": "Se déconnecter", "en": "Log out"},
    "sidebar.admin_local_mode": {
        "fr": "Mode admin local (LOCAL_DEV_AUTOLOGIN) — accès complet sans RLS.",
        "en": "Local admin mode (LOCAL_DEV_AUTOLOGIN) — full access, RLS bypassed.",
    },

    "theme.light": {"fr": "☀️ Mode clair", "en": "☀️ Light mode"},
    "theme.dark": {"fr": "🌙 Mode sombre", "en": "🌙 Dark mode"},
    "lang.toggle": {"fr": "🇬🇧 English", "en": "🇫🇷 Français"},

    "entretien.title": {"fr": "Compléter l'histoire", "en": "Complete the story"},
    "bibliotheque.title": {"fr": "Bibliothèque", "en": "Library"},
    "bibliotheque.caption": {
        "fr": "Interrogez en langage naturel l'ensemble des lieux recensés et des documents déposés.",
        "en": "Ask, in plain language, about all the recorded spaces and uploaded documents.",
    },
    "lieux_hybrides.title": {"fr": "Lieux hybrides", "en": "Hybrid spaces"},
    "lieux_hybrides.caption": {
        "fr": "L'annuaire de l'ensemble des tiers-lieux recensés.",
        "en": "The directory of all recorded hybrid spaces.",
    },
    "observatoire.title": {
        "fr": "Observatoire des lieux hybrides et territoires",
        "en": "Observatory of hybrid spaces and territories",
    },
    "observatoire.caption": {
        "fr": "Relevés statistiques, publics, sur l'ensemble des lieux recensés dans l'Annuaire.",
        "en": "Public statistical overview of all the spaces recorded in the Directory.",
    },
    "portfolio.title": {"fr": "Portfolio", "en": "Portfolio"},
    "portfolio.caption": {
        "fr": "Une sélection de lieux et de leurs campagnes de besoins actuelles.",
        "en": "A selection of spaces and their current fundraising/support campaigns.",
    },
    "chat.entretien_placeholder": {"fr": "Votre réponse...", "en": "Your answer..."},
    "chat.bibliotheque_placeholder": {
        "fr": "Posez une question sur les lieux recensés ou les documents déposés...",
        "en": "Ask a question about the recorded spaces or uploaded documents...",
    },
    "voice.dicter_reponse": {"fr": "Dicter la réponse", "en": "Dictate your answer"},
    "voice.dicter_question": {"fr": "Dicter la question", "en": "Dictate your question"},

    "nav.compte": {"fr": "Compte", "en": "Account"},
    "contribution.title": {"fr": "Votre contribution", "en": "Your contribution"},
    "contribution.lieu_label": {"fr": "Tiers-lieu", "en": "Hybrid space"},
    "contribution.nouveau_lieu_option": {"fr": "— Nouveau lieu —", "en": "— New space —"},
    "contribution.nom_nouveau_lieu": {"fr": "Nom du nouveau lieu", "en": "Name of the new space"},
    "contribution.role_label": {"fr": "Votre rôle vis-à-vis de ce lieu", "en": "Your role regarding this space"},
    "contribution.choisir_pour_demarrer": {
        "fr": "Choisissez ou créez un tiers-lieu ci-dessus pour démarrer.",
        "en": "Choose or create a hybrid space above to get started.",
    },
    "role.fondateur": {"fr": "Fondateur·rice / porteur de projet", "en": "Founder / project lead"},
    "role.equipe": {"fr": "Équipe opérationnelle", "en": "Operational team"},
    "role.partenaire": {"fr": "Partie prenante externe", "en": "External stakeholder"},
    "role.usager": {"fr": "Usager régulier", "en": "Regular user"},
    "role.steward": {
        "fr": "Steward (je continue à nourrir ce lieu)",
        "en": "Steward (I keep contributing to this space)",
    },
    "role.autre": {"fr": "Autre", "en": "Other"},
}


def _lang() -> str:
    return st.session_state.get("ui_lang", LANG_DEFAULT)


def t(key: str, **kwargs) -> str:
    """Traduit `key` dans la langue active (repli sur le français, puis sur
    `key` elle-même si la clé n'existe pas — pour ne jamais planter sur une
    traduction manquante)."""
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        return key
    text = entry.get(_lang()) or entry.get(LANG_DEFAULT) or key
    return text.format(**kwargs) if kwargs else text


def language_toggle() -> str:
    """Affiche le bouton de bascule FR/EN en barre latérale (à appeler une
    fois par script, juste après apply_theme()) et renvoie la langue active.
    Persisté en cookie comme le thème — voir la note dans theme.apply_theme()
    sur pourquoi st.session_state seul ne suffit pas entre les pages."""
    from src.auth_session import LANG_COOKIE_NAME, read_cookie, save_cookie

    if "ui_lang" not in st.session_state:
        st.session_state["ui_lang"] = LANG_DEFAULT
        st.session_state["ui_lang_user_set"] = False

    if not st.session_state.get("ui_lang_user_set"):
        cookie_value = read_cookie(LANG_COOKIE_NAME)
        if cookie_value in LANGUAGES:
            st.session_state["ui_lang"] = cookie_value

    def _basculer_langue() -> None:
        st.session_state["ui_lang"] = "en" if st.session_state["ui_lang"] == "fr" else "fr"
        st.session_state["ui_lang_user_set"] = True
        save_cookie(LANG_COOKIE_NAME, st.session_state["ui_lang"])

    st.sidebar.button(
        t("lang.toggle"), key="ui_lang_toggle", on_click=_basculer_langue, use_container_width=True,
    )
    return st.session_state["ui_lang"]
