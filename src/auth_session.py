"""Persistance entre visites via cookie navigateur — connexion (refresh_token
Supabase, ou l'email en mode développement sans Supabase) et préférences
d'affichage (thème clair/sombre). Isolé dans son propre module pour rester
facile à retirer si le composant cookie posait problème : sans lui, l'app
fonctionne comme avant, avec une reconnexion et un thème par défaut à
chaque visite.

Généralisé à plusieurs cookies nommés (pas seulement la session de
connexion) : st.session_state ne suffit pas seul pour ce genre de préférence
car il ne se propage pas de façon fiable d'une page à l'autre dans cette
version de Streamlit (observé sur le thème : réglé sur une page, revenu à
la valeur par défaut en naviguant vers une autre) — le cookie devient la
source de vérité commune, relue au tout début de chaque page."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

COOKIE_NAME = "lh_session"
THEME_COOKIE_NAME = "lh_theme"


def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        import extra_streamlit_components as stx
        st.session_state["cookie_manager"] = stx.CookieManager(key="lh_cookie_manager")
    return st.session_state["cookie_manager"]


def save_cookie(name: str, value: str, days: int = 30) -> None:
    get_cookie_manager().set(
        name, value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        key=f"lh_cookie_set_{name}",
    )


def read_cookie(name: str) -> str | None:
    # CookieManager.get() lit un dict `self.cookies` peuplé UNE SEULE FOIS, à
    # la construction de l'instance (dans __init__) — jamais rafraîchi
    # ensuite. Comme get_cookie_manager() met cette instance en cache dans
    # st.session_state, un .get() direct restait figé sur l'instantané pris
    # au tout premier rendu (souvent vide, le composant n'ayant pas encore
    # reçu la réponse du navigateur), pour toute la durée de la session —
    # observé concrètement : un cookie posé restait invisible indéfiniment.
    # get_all() ré-invoque le composant à chaque appel (même clé => même
    # emplacement de composant côté Streamlit, pas de doublon) et renvoie
    # l'état réellement à jour.
    cookies = get_cookie_manager().get_all(key="lh_cookie_get_all")
    return (cookies or {}).get(name)


def clear_cookie(name: str) -> None:
    try:
        get_cookie_manager().delete(name, key=f"lh_cookie_delete_{name}")
    except KeyError:
        pass


def save_session_cookie(value: str) -> None:
    save_cookie(COOKIE_NAME, value)


def read_session_cookie() -> str | None:
    return read_cookie(COOKIE_NAME)


def clear_session_cookie() -> None:
    clear_cookie(COOKIE_NAME)
