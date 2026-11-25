"""Page publique : fiche d'UN lieu en lecture seule, atteinte via un lien de
partage (?lieu=<id>) posé sur le bouton "🔗 Partager" de la fiche dans
l'Annuaire (connecté). Aucune connexion requise — même principe que
l'Observatoire et le Portfolio : n'importe qui recevant ce lien voit la
même synthèse qu'un contributeur connecté, sans les sections de
modération/administration ni les réponses brutes nominatives.

Sélectionnée via st.Page dans src/app.py (menu de navigation unifié) : le
set_page_config()/apply_theme()/load_dotenv() de app.py s'appliquent déjà
avant que cette page ne s'exécute, donc pas besoin de les refaire ici — les
répéter lèverait une erreur (set_page_config ne peut être appelé qu'une
fois par run)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st

from src.annuaire import render_fiche_header, render_fiche_sections
from src.auth_session import read_session_cookie
from src.db.factory import get_admin_store, get_store
from src.i18n import t


def _store_pour_lecture_publique():
    """Même repli que l'Observatoire (voir sa propre note) : get_all_answers_
    by_contributeur() filtre d'abord par contributeurs non bloqués, une
    lecture que RLS n'autorise qu'à voir ses PROPRES lignes — pour un
    visiteur anonyme, ça viderait les réponses de tout le monde par excès
    de prudence. Seules des synthèses déjà publiques (lieu_derive) quittent
    cette page, jamais de donnée nominative, donc contourner RLS ici reste
    sûr. Repli sur le store public si la clé service_role n'est pas
    configurée."""
    try:
        return get_admin_store()
    except RuntimeError:
        return get_store()


# Défini ici plutôt qu'importé de src/theme.py : sur Streamlit Cloud, un push
# ne recharge que les scripts (app.py, pages), pas les modules déjà importés.
# Un nouveau nom importé d'un module existant faisait planter toute l'app
# (ImportError) jusqu'au redémarrage manuel, constaté le 25/11/2026.
CSS_SANS_MENU = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapseButton"], [data-testid="stSidebarNav"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stExpandSidebarButton"] { display: none !important; }
</style>"""

# Visiteur non connecté (lien de partage reçu) : la fiche seule, sans le menu
# de l'app. Connecté = session déjà ouverte dans cet onglet, ou cookie de
# connexion présent dans le navigateur (la fiche n'appelle pas auth_screen(),
# donc un utilisateur qui ouvre le lien dans un nouvel onglet n'a pas encore
# de user_id ; son cookie suffit à lui garder le menu).
if not (st.session_state.get("user_id") or read_session_cookie()):
    st.markdown(CSS_SANS_MENU, unsafe_allow_html=True)

lieu_id = st.query_params.get("lieu")
if not lieu_id:
    st.title(t("fiche_page.title"))
    st.info(t("fiche_page.aucun_lieu_specifie"))
    st.stop()

store = _store_pour_lecture_publique()
lieux = {l.id: l for l in store.list_tiers_lieux()}
lieu = lieux.get(lieu_id)
if lieu is None:
    st.title(t("fiche_page.title"))
    st.error(t("fiche_page.lieu_introuvable"))
    st.stop()

derive = store.get_lieu_derive(lieu.id)
st.caption(t("fiche_page.caption"))
render_fiche_header(store, lieu, derive)
render_fiche_sections(store, lieu, derive, montrer_sources=False)
