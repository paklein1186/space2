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
/* Barre basse fixe de st.chat_input (Entretien, Bibliothèque) : son
   conteneur parent (sans data-testid propre) garde un fond blanc Streamlit
   par défaut, visible derrière le champ pourtant transparent lui-même. */
[data-testid="stBottomBlockContainer"]{{ background: var(--sp-bg) !important; }}
[data-testid="stSidebar"]{{
  background: var(--sp-bg-sidebar) !important; border-right: 1px solid var(--sp-border-soft);
}}
/* Sans !important, cette règle perdait face aux règles internes de
   Streamlit qui fixent la couleur du texte markdown (stMarkdownContainer
   p/li/span...) sur le gris quasi-noir du thème clair par défaut — texte
   quasi invisible sur notre fond sombre (résumés de lieu, réponses de la
   Bibliothèque...), signalé en production comme "illisible". Les règles
   plus spécifiques ci-dessous (boutons, etc.) restent prioritaires malgré
   le !important : à spécificité CSS égale sur !important, la règle la plus
   spécifique gagne toujours, pas seulement l'ordre d'apparition. */
[data-testid="stSidebar"] *, [data-testid="stMain"] * {{ color: var(--sp-text) !important; }}
/* Flèche de repli de la barre latérale : en dehors de stSidebar (chrome de
   l'appli, pas son contenu), donc pas couverte par la règle générale
   ci-dessus — et son icône fixe une couleur via un attribut HTML `color=`
   calé sur le texte sombre du thème clair Streamlit, quasi invisible au
   repos sur notre fond sombre (visible seulement au survol, qui la
   réhausse). */
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stSidebarCollapseButton"] span {{ color: var(--sp-text) !important; }}
[data-testid="stCaptionContainer"], .stCaption {{ color: var(--sp-text-muted) !important; }}
/* st.dialog (fiche du lieu, etc.) : rendu dans un portail directement sous
   <body>, JAMAIS à l'intérieur de stMain — aucune des règles ci-dessus ne
   l'atteint, donc tout son texte restait sur les couleurs du thème clair
   Streamlit par défaut (texte quasi noir), y compris en thème sombre.
   Repéré en inspectant la chaîne de parents réelle d'un texte de fiche
   (stDialog est un enfant direct de body), pas une supposition — même
   classe de piège que les popovers BaseWeb (menus déroulants) déjà
   contournée plus bas. */
[data-testid="stDialog"] {{ background: var(--sp-bg) !important; }}
/* La boîte modale elle-même (fond blanc Streamlit par défaut) n'a pas de
   data-testid stable — role="dialog" (attribut d'accessibilité, posé par
   Streamlit/BaseWeb) est le seul sélecteur fiable trouvé pour l'atteindre. */
[data-testid="stDialog"] [role="dialog"] {{ background: var(--sp-bg-elevated) !important; }}
[data-testid="stDialog"] * {{ color: var(--sp-text) !important; }}
[data-testid="stDialog"] [data-testid="stCaptionContainer"] {{ color: var(--sp-text-muted) !important; }}
[data-testid="stDialog"] [data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--sp-bg-elevated) !important; border-color: var(--sp-border-soft) !important;
}}

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
/* Le <summary> (en-tête cliquable) a son propre fond explicite par défaut
   (gris très clair) qui recouvre celui du conteneur parent ci-dessus — sans
   ceci, l'en-tête de chaque expander (ex. "⚙️ Administration") restait
   illisible en thème sombre alors que son contenu, une fois déplié, était
   déjà correctement sombre. */
[data-testid="stExpander"] summary{{
  background: var(--sp-bg-elevated) !important; color: var(--sp-text) !important;
}}

/* ---------- champs de saisie ---------- */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div {{
  background: var(--sp-bg-elevated) !important; color: var(--sp-text) !important;
  border-color: var(--sp-border-soft) !important;
}}

/* ---------- menus déroulants (selectbox/multiselect) ---------- */
/* Le popup d'options (BaseWeb) n'est PAS imbriqué dans stSidebar/stMain —
   il se monte dans son propre portail — donc les règles ci-dessus ne
   l'atteignent jamais : sans ceci, il gardait un fond blanc BaseWeb par
   défaut, illisible/disparate sur le reste de l'interface en thème sombre. */
[data-baseweb="popover"]{{ background: var(--sp-bg-elevated) !important; }}
[data-testid="stSelectboxVirtualDropdown"]{{
  background: var(--sp-bg-elevated) !important;
}}
[data-testid="stSelectboxVirtualDropdown"] li[role="option"]{{
  background: var(--sp-bg-elevated) !important; color: var(--sp-text) !important;
}}
[data-testid="stSelectboxVirtualDropdown"] li[role="option"]:hover,
[data-testid="stSelectboxVirtualDropdown"] li[aria-selected="true"]{{
  background: var(--sp-border-soft) !important;
}}

/* ---------- alignement : boutons en colonne à largeur homogène ---------- */
[data-testid="column"] [data-testid="stButton"]{{ display: flex; }}
[data-testid="column"] [data-testid="stButton"] button{{ width: 100%; }}

hr{{ border-color: var(--sp-border-soft) !important; }}

/* ---------- page "Fiche partagée" : masquée du menu, pas de la navigation ---------- */
/* Cette page n'a de sens qu'ouverte via un lien de partage (?lieu=<id>) — la
   lister dans le menu comme les autres onglets n'aboutit qu'à "Aucun lieu
   spécifié" pour qui clique dessus par curiosité, ce qui a été rapporté
   comme confus. La retirer de st.navigation() casserait les liens de
   partage déjà envoyés (Streamlit ne route plus vers une page absente de la
   liste) : on la garde donc dans st.navigation(), en masquant uniquement
   son lien dans le menu par CSS. */
a[data-testid="stSidebarNavLink"][href$="/fiche"]{{ display: none; }}
</style>
"""


def apply_theme() -> str:
    """Affiche le sélecteur clair/sombre en barre latérale et injecte le CSS
    correspondant. À appeler une fois, juste après st.set_page_config(), sur
    chaque script (app.py + chaque page) — retourne le mode actif ("dark" ou
    "light") si un appelant veut l'utiliser ailleurs (ex. couleurs de graphique).

    Le choix est mémorisé dans un cookie (pas seulement st.session_state) :
    app.py et chaque page de src/pages/ sont des scripts Streamlit distincts,
    et st.session_state ne s'est pas propagé de façon fiable entre eux en
    pratique (réglé sur une page, revenu à "sombre" par défaut en naviguant
    vers une autre) — le cookie devient la source de vérité commune, relue
    au tout début de chaque page, qui persiste aussi d'une visite à l'autre.

    Le composant cookie (iframe bidirectionnel) ne répond pas forcément dès
    le premier passage du script : une lecture peut renvoyer vide alors qu'un
    cookie existe bel et bien, le temps que le navigateur réponde. Tant que
    l'utilisateur n'a pas explicitement touché le bouton (détecté via
    on_click, pas juste "le widget a été rendu"), on continue de relire le
    cookie à chaque rerun et de s'y aligner — sans quoi une lecture prématurée
    (vide) se figerait et écraserait ensuite un cookie déjà valide."""
    from src.auth_session import THEME_COOKIE_NAME, read_cookie, refresh_cookies, save_cookie

    # Seul vrai appel au composant cookie de tout le script (voir la note
    # dans auth_session.py) : auth_screen()/read_session_cookie() ne font
    # ensuite que relire l'instantané que ce refresh vient de poser, sans
    # réinvoquer le composant — deux appels avec la même clé dans un même
    # passage de script feraient planter l'app (StreamlitDuplicateElementKey,
    # rencontré concrètement).
    refresh_cookies()

    if "ui_theme" not in st.session_state:
        st.session_state["ui_theme"] = "dark"
        st.session_state["ui_theme_user_set"] = False

    if not st.session_state.get("ui_theme_user_set"):
        cookie_value = read_cookie(THEME_COOKIE_NAME)
        if cookie_value in _PALETTES:
            st.session_state["ui_theme"] = cookie_value

    def _basculer_theme() -> None:
        st.session_state["ui_theme"] = "light" if st.session_state["ui_theme"] == "dark" else "dark"
        st.session_state["ui_theme_user_set"] = True
        save_cookie(THEME_COOKIE_NAME, st.session_state["ui_theme"])

    mode = st.session_state["ui_theme"]
    # Un simple bouton bascule (icône soleil/lune) plutôt qu'un st.selectbox :
    # la structure DOM interne du composant BaseWeb Select (utilisé par
    # st.selectbox) ne correspondait plus au sélecteur CSS ciblé pour le
    # thème sombre — le menu déroulant s'affichait avec un fond blanc
    # illisible. st.button suit le même style déjà éprouvé partout ailleurs
    # dans l'app (voir _CSS_TEMPLATE plus haut), sans ce risque.
    from src.i18n import t

    st.sidebar.button(
        t("theme.light") if mode == "dark" else t("theme.dark"),
        key="ui_theme_toggle", on_click=_basculer_theme, use_container_width=True,
    )

    palette = _PALETTES.get(mode, _PALETTES["dark"])
    st.markdown(_CSS_TEMPLATE.format(**palette), unsafe_allow_html=True)
    return mode
