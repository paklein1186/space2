"""Page publique : accueil du site, sans connexion requise — explique les
bénéfices à rejoindre le réseau avant même de créer un compte, et sert de
porte d'entrée vers l'entretien (pour recenser son lieu), l'Annuaire et
l'Observatoire. Même principe que les autres pages publiques (Observatoire,
Portfolio, Fiche) : n'affiche que des agrégats déjà publics, jamais de
donnée nominative.

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

from src.db.factory import get_store
from src.i18n import t


def _stats_publiques() -> tuple[int, int, int]:
    """Compteurs légers pour la bannière d'accueil — mêmes données déjà
    publiques que l'Annuaire/l'Observatoire (tiers_lieux, lieu_derive),
    jamais de donnée nominative. Ne doit jamais faire planter la page
    d'accueil : un échec de connexion renvoie des compteurs à zéro plutôt
    qu'une erreur, cette page devant rester la plus robuste du site."""
    try:
        store = get_store()
        lieux = store.list_tiers_lieux()
        nb_pays = len({l.pays for l in lieux if l.pays})
        derive_par_lieu = store.get_lieu_derive_batch([l.id for l in lieux])
        nb_besoins = sum(
            len(d.besoins_mis_en_avant or []) for d in derive_par_lieu.values()
        )
        return len(lieux), nb_pays, nb_besoins
    except Exception:
        return 0, 0, 0


st.title(t("accueil.hero_titre"))
st.caption(t("accueil.hero_soustitre"))

nb_lieux, nb_pays, nb_besoins = _stats_publiques()
if nb_lieux:
    col1, col2, col3 = st.columns(3)
    col1.metric(t("accueil.stat_lieux"), nb_lieux)
    col2.metric(t("accueil.stat_pays"), nb_pays)
    col3.metric(t("accueil.stat_besoins"), nb_besoins)

st.divider()

BENEFICES = [
    ("accueil.benefice_1_titre", "accueil.benefice_1_texte"),
    ("accueil.benefice_2_titre", "accueil.benefice_2_texte"),
    ("accueil.benefice_3_titre", "accueil.benefice_3_texte"),
    ("accueil.benefice_4_titre", "accueil.benefice_4_texte"),
]
cols_benefices = st.columns(2)
for i, (titre_key, texte_key) in enumerate(BENEFICES):
    with cols_benefices[i % 2]:
        with st.container(border=True):
            st.markdown(f"#### {t(titre_key)}")
            st.write(t(texte_key))

st.divider()
st.subheader(t("accueil.cta_titre"))


def _lien_interne(href: str, label: str) -> None:
    """Lien vers une autre page DE CE SITE, dans le même onglet — st.markdown
    ajoute automatiquement target="_blank" à tout lien [texte](url) (pensé
    pour des liens externes), ce qui ouvrait ces boutons "Par où commencer ?"
    dans un nouvel onglet au lieu de naviguer sur place, surprenant pour une
    navigation interne. Le HTML brut, lui, n'est pas retraité par ce
    mécanisme : target="_self" explicite s'applique donc vraiment."""
    st.markdown(f'<a href="{href}" target="_self">{label}</a>', unsafe_allow_html=True)


col_a, col_b, col_c = st.columns(3)
with col_a:
    # page_entretien/page_lieux_hybrides sont des st.Page(fonction, ...) dans
    # app.py, pas des fichiers : st.page_link exige soit un objet StreamlitPage
    # (hors de portée depuis une page distincte), soit un chemin de fichier
    # relatif à app.py — inexistant pour une page-fonction. Un lien relatif
    # vers l'url_path déjà déclaré (routeur Streamlit côté client) fonctionne
    # pour les deux types de page, contrairement à st.page_link ici.
    _lien_interne("/entretien", t("accueil.cta_entretien"))
with col_b:
    _lien_interne("/lieux-hybrides", t("accueil.cta_annuaire"))
with col_c:
    st.page_link("pages/1_Observatoire.py", label=t("accueil.cta_observatoire"), use_container_width=True)
