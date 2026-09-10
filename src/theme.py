"""Identité visuelle partagée ("solarpunk technologique") — appelée en tout
début de chaque script Streamlit (app.py + chaque page de src/pages/, qui
s'exécutent indépendamment et n'héritent donc rien les uns des autres).

Les couleurs structurelles (fond, texte, accent) viennent de
.streamlit/config.toml — c'est ce qui pilote nativement les boutons primaires,
la coche des tabs, les barres de progression, etc. sans avoir à les
réécrire en CSS. Ce module n'ajoute que ce que le thème natif ne couvre
pas : la typographie, la texture (lueur, profondeur) et quelques
alignements.

Cible les attributs `data-testid`/`data-baseweb`, plus stables d'une version
Streamlit à l'autre que les noms de classes générés."""

from __future__ import annotations

import streamlit as st

_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700;800&family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root{
  --sp-glow: 0 0 0 1px rgba(74,222,128,0.28), 0 0 22px rgba(74,222,128,0.14);
  --sp-border: rgba(74,222,128,0.18);
  --sp-border-soft: rgba(234,242,233,0.10);
}

html, body, [class^="css"], [class*=" css"] { font-family: 'Manrope', -apple-system, sans-serif; }
h1, h2, h3, h4, h5, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
  font-family: 'Sora', -apple-system, sans-serif !important;
  letter-spacing: -0.01em;
}
code, pre, [data-testid="stMetricValue"], .stCode, [data-testid="stCaptionContainer"] code {
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}

/* ---------- boutons : lueur "bio-luminescente" au survol ---------- */
[data-testid="stButton"] button,
[data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
  border-radius: 10px !important;
  border: 1px solid var(--sp-border-soft) !important;
  font-weight: 600 !important;
  transition: box-shadow 0.15s ease, transform 0.15s ease, border-color 0.15s ease;
}
[data-testid="stButton"] button:hover,
[data-testid="stFormSubmitButton"] button:hover,
[data-testid="stDownloadButton"] button:hover {
  border-color: rgba(74,222,128,0.55) !important;
  box-shadow: var(--sp-glow);
  transform: translateY(-1px);
}
[data-testid="stButton"] button[kind="primary"]:hover { box-shadow: var(--sp-glow); }

/* ---------- cartes (st.container(border=True)) : profondeur, coin arrondi ---------- */
[data-testid="stVerticalBlockBorderWrapper"]{
  border-radius: 14px !important;
  border-color: var(--sp-border-soft) !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:has([data-testid="stButton"]):hover{
  border-color: var(--sp-border) !important;
}

/* ---------- onglets ---------- */
[data-testid="stTabs"] [data-baseweb="tab"]{
  font-family: 'Sora', sans-serif; font-weight: 600; font-size: 0.95rem;
}

/* ---------- barre latérale ---------- */
[data-testid="stSidebar"]{ border-right: 1px solid var(--sp-border-soft); }

/* ---------- métriques (Observatoire) ---------- */
[data-testid="stMetric"]{
  background: rgba(74,222,128,0.05);
  border: 1px solid var(--sp-border-soft);
  border-radius: 12px;
  padding: 14px 18px;
}

/* ---------- expanders / popovers ---------- */
[data-testid="stExpander"]{ border-color: var(--sp-border-soft) !important; border-radius: 10px !important; }

/* ---------- alignement : colonnes d'actions à hauteur/espacement homogènes ---------- */
[data-testid="column"] [data-testid="stButton"]{ display: flex; }
[data-testid="column"] [data-testid="stButton"] button{ width: 100%; }

/* ---------- séparateurs plus discrets sur fond sombre ---------- */
hr{ border-color: var(--sp-border-soft) !important; }
</style>
"""


def inject_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
