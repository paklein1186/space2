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
source de vérité commune, relue au tout début de chaque page.

Lecture en deux temps (refresh_cookies + read_cookie) plutôt qu'un appel
direct à chaque lecture : Streamlit interdit d'invoquer un composant deux
fois avec la MÊME clé au sein d'un même passage de script — hors avec une
clé fixe, appeler le composant "getAll" à la fois pour le cookie de session
(auth_screen) et pour le cookie de thème (apply_theme) dans le même run
lève StreamlitDuplicateElementKey. refresh_cookies() fait le seul vrai appel
par script (theme.apply_theme() l'appelle systématiquement en tout début de
page) ; read_cookie() ne fait ensuite que relire l'instantané qui en résulte."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

COOKIE_NAME = "lh_session"
THEME_COOKIE_NAME = "lh_theme"

_SNAPSHOT_KEY = "_cookies_snapshot"


def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        import extra_streamlit_components as stx
        st.session_state["cookie_manager"] = stx.CookieManager(key="lh_cookie_manager")
    return st.session_state["cookie_manager"]


def refresh_cookies() -> dict:
    """Le seul appel réel au composant CookieManager d'un script donné —
    rafraîchit l'instantané que read_cookie() relit ensuite. À appeler une
    fois, le plus tôt possible (apply_theme() le fait déjà systématiquement).
    CookieManager.get() seul lit un dict peuplé une seule fois à la
    construction de l'instance, jamais rafraîchi ensuite ; get_all() se
    rafraîchit à chaque appel, d'où son usage ici plutôt qu'un simple .get()."""
    cookies = get_cookie_manager().get_all(key="lh_cookie_get_all") or {}
    st.session_state[_SNAPSHOT_KEY] = cookies
    return cookies


def read_cookie(name: str) -> str | None:
    return st.session_state.get(_SNAPSHOT_KEY, {}).get(name)


def save_cookie(name: str, value: str, days: int = 30) -> None:
    get_cookie_manager().set(
        name, value,
        expires_at=datetime.now(timezone.utc) + timedelta(days=days),
        key=f"lh_cookie_set_{name}",
    )
    # Mise à jour optimiste de l'instantané : une lecture plus tard dans ce
    # même run doit voir la valeur qu'on vient de poser, pas attendre le
    # prochain refresh_cookies() (prochain script) pour la voir apparaître.
    st.session_state.setdefault(_SNAPSHOT_KEY, {})[name] = value


def clear_cookie(name: str) -> None:
    try:
        get_cookie_manager().delete(name, key=f"lh_cookie_delete_{name}")
    except KeyError:
        pass
    st.session_state.setdefault(_SNAPSHOT_KEY, {}).pop(name, None)


def save_session_cookie(value: str) -> None:
    save_cookie(COOKIE_NAME, value)


def read_session_cookie() -> str | None:
    return read_cookie(COOKIE_NAME)


def clear_session_cookie() -> None:
    clear_cookie(COOKIE_NAME)
