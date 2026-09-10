"""Persistance de la connexion entre visites, via un cookie navigateur qui
contient le refresh_token Supabase (ou l'email en mode développement sans
Supabase). Isolé dans son propre module pour rester facile à retirer si le
composant cookie posait problème : sans lui, l'app fonctionne exactement
comme avant, avec une reconnexion à chaque visite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

COOKIE_NAME = "lh_session"


def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        import extra_streamlit_components as stx
        st.session_state["cookie_manager"] = stx.CookieManager(key="lh_cookie_manager")
    return st.session_state["cookie_manager"]


def save_session_cookie(value: str) -> None:
    get_cookie_manager().set(
        COOKIE_NAME, value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        key="lh_cookie_set",
    )


def read_session_cookie() -> str | None:
    return get_cookie_manager().get(COOKIE_NAME)


def clear_session_cookie() -> None:
    try:
        get_cookie_manager().delete(COOKIE_NAME, key="lh_cookie_delete")
    except KeyError:
        pass
