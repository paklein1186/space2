"""Identité visuelle partagée ("solarpunk technologique") — appelée en tout
début de chaque script Streamlit (app.py + chaque page de src/pages/, qui
s'exécutent indépendamment et n'héritent donc rien les uns des autres).

Clair et sombre sont tous deux des palettes maison (pas les presets
génériques de Streamlit) : le choix est un simple radio en barre latérale,
mémorisé dans st.session_state["ui_theme"] (partagé entre les pages d'une
même session), et c'est cette valeur — pas config.toml — qui pilote les
couleurs via des surcharges CSS ciblant les attributs `data-testid`, plus
stables d'une version Streamlit à l'autre que les noms de classes générés.
"""

from __future__ import annotations

import streamlit as st

_PALETTES = {
    "dark": {
        "bg": "#0F1812", "bg_elevated": "#16251A", "bg_sidebar": "#0C1610",
        "text": "#EAF2E9", "text_muted": "#93AB9B",
        "border_soft": "rgba(74,222,128,0.22)", "border": "rgba(74,222,128,0.45)",
        "accent": "#4ADE80", "accent_ink": "#06210F",
        "glow": "0 0 0 1px rgba(74,222,128,0.35), 0 0 22px rgba(74,222,128,0.16)",
    },
    "light": {
        "bg": "#F4F7F1", "bg_elevated": "#FFFFFF", "bg_sidebar": "#EAF0E4",
        "text": "#122016", "text_muted": "#4B5D50",
        "border_soft": "rgba(31,165,85,0.25)", "border": "rgba(31,165,85,0.55)",
        "accent": "#1FA555", "accent_ink": "#FFFFFF",
        "glow": "0 0 0 1px rgba(31,165,85,0.35), 0 0 18px rgba(31,165,85,0.18)",
    },
}

_CSS_TEMPLATE = """<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root{{
  --sp-bg: {bg}; --sp-bg-elevated: {bg_elevated}; --sp-bg-sidebar: {bg_sidebar};
  --sp-text: {text}; --sp-text-muted: {text_muted};
  --sp-border-soft: {border_soft}; --sp-border: {border};
  --sp-accent: {accent}; --sp-accent-ink: {accent_ink};
  --sp-glow: {glow};
}}

html, body, [class^="css"], [class*=" css"] {{ font-family: 'Manrope', -apple-system, sans-serif; }}
h1, h2, h3, h4, h5, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
  font-family: 'Sora', -apple-system, sans-serif !important;
  letter-spacing: -0.01em;
}}
code, pre, [data-testid="stMetricValue"], .stCode, [data-testid="stCaptionContainer"] code {{
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}}

/* ---------- structure : fond/texte pilotés par notre palette, pas config.toml ---------- */
[data-testid="stAppViewContainer"], [data-testid="stMain"], .main, body {{
  background: var(--sp-bg) !important; color: var(--sp-text) !important;
}}
[data-testid="stHeader"]{{ background: transparent !important; }}
[data-testid="stSidebar"]{{
  background: var(--sp-bg-sidebar) !important; border-right: 1px solid var(--sp-border-soft);
}}
[data-testid="stSidebar"] *, [data-testid="stMain"] * {{ color: var(--sp-text); }}
[data-testid="stCaptionContainer"], .stCaption {{ color: var(--sp-text-muted) !important; }}

/* ---------- boutons : lueur "bio-luminescente" au survol ---------- */
[data-testid="stButton"] button, [data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {{
  border-radius: 10px !important;
  border: 1px solid var(--sp-border-soft) !important;
  background: var(--sp-bg-elevated) !important; color: var(--sp-text) !important;
  font-weight: 600 !important;
  transition: box-shadow 0.15s ease, transform 0.15s ease, border-color 0.15s ease;
}}
[data-testid="stButton"] button:hover, [data-testid="stFormSubmitButton"] button:hover,
[data-testid="stDownloadButton"] button:hover {{
  border-color: var(--sp-border) !important; box-shadow: var(--sp-glow); transform: translateY(-1px);
}}
[data-testid="stButton"] button[kind="primary"] {{
  background: var(--sp-accent) !important; color: var(--sp-accent-ink) !important; border: none !important;
}}

/* ---------- cartes (st.container(border=True)) ---------- */
[data-testid="stVerticalBlockBorderWrapper"]{{
  border-radius: 14px !important; border-color: var(--sp-border-soft) !important;
  background: var(--sp-bg-elevated) !important;
}}

/* ---------- onglets ---------- */
[data-testid="stTabs"] [data-baseweb="tab"]{{
  font-family: 'Sora', sans-serif; font-weight: 600; font-size: 0.95rem; color: var(--sp-text-muted);
}}
[data-testid="stTabs"] [aria-selected="true"]{{ color: var(--sp-accent) !important; }}
[data-testid="stTabs"] [data-baseweb="tab-highlight"]{{ background-color: var(--sp-accent) !important; }}

/* ---------- métriques (Observatoire) ---------- */
[data-testid="stMetric"]{{
  background: var(--sp-bg-elevated); border: 1px solid var(--sp-border-soft);
  border-radius: 12px; padding: 14px 18px;
}}

/* ---------- expanders / popovers ---------- */
[data-testid="stExpander"]{{
  border-color: var(--sp-border-soft) !important; border-radius: 10px !important;
  background: var(--sp-bg-elevated) !important;
}}

/* ---------- champs de saisie ---------- */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div {{
  background: var(--sp-bg-elevated) !important; color: var(--sp-text) !important;
  border-color: var(--sp-border-soft) !important;
}}

/* ---------- alignement : boutons en colonne à largeur homogène ---------- */
[data-testid="column"] [data-testid="stButton"]{{ display: flex; }}
[data-testid="column"] [data-testid="stButton"] button{{ width: 100%; }}

hr{{ border-color: var(--sp-border-soft) !important; }}
</style>
"""


def apply_theme() -> str:
    """Affiche le sélecteur clair/sombre en barre latérale et injecte le CSS
    correspondant. À appeler une fois, juste après st.set_page_config(), sur
    chaque script (app.py + chaque page) — retourne le mode actif ("dark" ou
    "light") si un appelant veut l'utiliser ailleurs (ex. couleurs de graphique)."""
    if "ui_theme" not in st.session_state:
        st.session_state["ui_theme"] = "dark"
    # st.selectbox plutôt que st.radio/st.segmented_control/st.toggle : déjà
    # utilisé ailleurs dans cette app (rôle/lieu en barre latérale), donc son
    # chunk JS est déjà chargé de façon fiable — un widget jamais utilisé
    # avant a fait planter toute l'app en production (chunk JS introuvable).
    mode = st.sidebar.selectbox(
        "Thème", options=["dark", "light"],
        format_func=lambda m: "🌙 Sombre" if m == "dark" else "☀️ Clair",
        label_visibility="collapsed", key="ui_theme",
    )
    palette = _PALETTES.get(mode, _PALETTES["dark"])
    st.markdown(_CSS_TEMPLATE.format(**palette), unsafe_allow_html=True)
    return mode
