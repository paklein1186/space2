"""Page publique : vitrine en lecture seule des lieux sélectionnés par un
administrateur pour y présenter leur campagne de besoins. Aucune connexion
requise — la curation (cocher "inclure au Portfolio", éditer la campagne) se
fait depuis l'Annuaire, section Administration.

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

from src.annuaire import (
    SECTIONS_SYNTHESE,
    besoins_chips_html,
    category_chips_html,
    default_visual,
    donnees_a_afficher,
    photo_html,
    texte_en_points,
    vignette_html,
)
from src.db.factory import get_store
from src.i18n import t, t_categorie


@st.dialog(t("fiche_dialog.title"), width="large")
def _fiche_publique_dialog(store, lieu, derive) -> None:
    """Version publique (sans connexion) de la fiche de l'Annuaire : mêmes
    informations de synthèse, sans les sections de modération/administration
    qui n'ont pas de sens pour un visiteur anonyme. La campagne, raison
    d'être de cette page, est mise en avant avant le reste plutôt que
    mélangée aux autres sections."""
    donnees = donnees_a_afficher(store, derive)
    col_photo, col_info = st.columns([1, 3])
    with col_photo:
        if derive and derive.photo_url:
            st.markdown(photo_html(derive.photo_url, hauteur="10rem"), unsafe_allow_html=True)
        else:
            emoji, couleur = default_visual(lieu.nom, donnees)
            st.markdown(vignette_html(emoji, couleur, hauteur="10rem"), unsafe_allow_html=True)
    with col_info:
        st.markdown(f"### {lieu.nom}")
        st.caption(f"{lieu.pays or ''} — {lieu.region or ''}")
        if donnees.get("categories"):
            st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
        if derive and derive.besoins_mis_en_avant:
            st.markdown(besoins_chips_html(derive.besoins_mis_en_avant), unsafe_allow_html=True)

    if derive and derive.campagne_texte:
        st.divider()
        with st.container(border=True):
            st.markdown(f"#### {t('portfolio.campagne_titre')}")
            st.write(derive.campagne_texte)
            col_obj, col_contact = st.columns(2)
            with col_obj:
                if derive.campagne_objectif:
                    st.markdown(t("portfolio.objectif_label", valeur=derive.campagne_objectif))
            with col_contact:
                if derive.campagne_contact:
                    st.markdown(t("portfolio.contact_label", valeur=derive.campagne_contact))

    if donnees.get("resume"):
        st.divider()
        st.write(donnees["resume"])

    if derive:
        # derive.sources[cle] non vide = section réellement alimentée par des
        # réponses (pas la formule de remplissage du prompt d'enrichissement
        # pour homogénéiser la longueur) — même logique que la fiche privée,
        # sans avoir besoin de résoudre les sources en détail (pas de
        # popover "Sources" ici, superflu pour un visiteur public).
        sections_a_afficher = [
            (cle, titre_key) for cle, titre_key in SECTIONS_SYNTHESE[1:] if derive.sources.get(cle)
        ]
        if sections_a_afficher:
            st.divider()
            cols = st.columns(3)
            for i, (cle, titre_key) in enumerate(sections_a_afficher):
                texte = donnees.get(cle) or "—"
                with cols[i % 3]:
                    st.markdown(f"**{t(titre_key)}**")
                    st.caption(texte_en_points(texte))

    if derive and derive.lien_externe:
        st.divider()
        st.markdown(f"[{t('portfolio.en_savoir_plus')}]({derive.lien_externe})")


st.title(t("portfolio.title"))
st.caption(t("portfolio.caption"))

store = get_store()
lieux = store.list_lieux_portfolio()

if not lieux:
    st.info(t("portfolio.aucun_lieu"))
    st.stop()

# Un seul aller-retour pour toutes les synthèses plutôt qu'un get_lieu_derive
# par lieu dans la boucle d'affichage (même piège de N+1 déjà rencontré et
# corrigé dans l'Annuaire) — réutilisé pour le filtre de catégories, les
# cartes ET la fiche ouverte au clic.
derive_par_lieu = store.get_lieu_derive_batch([l.id for l in lieux])

if "portfolio_open_lieu_id" in st.session_state:
    lieu_id = st.session_state.pop("portfolio_open_lieu_id")
    lieu_ouvert = next((l for l in lieux if l.id == lieu_id), None)
    if lieu_ouvert:
        _fiche_publique_dialog(store, lieu_ouvert, derive_par_lieu.get(lieu_id))

categories_disponibles = sorted({
    c for derive in derive_par_lieu.values() for c in (derive.donnees.get("categories") or [])
})
filtre_categories = st.multiselect(
    t("portfolio.filtrer_categorie"), options=categories_disponibles,
    placeholder=t("portfolio.toutes_categories"), format_func=t_categorie,
)


def _categories(lieu) -> set:
    derive = derive_par_lieu.get(lieu.id)
    return set((derive.donnees.get("categories") if derive else None) or [])


lieux_affiches = lieux
if filtre_categories:
    lieux_affiches = [l for l in lieux_affiches if _categories(l) & set(filtre_categories)]

if not lieux_affiches:
    st.info(t("portfolio.aucun_lieu_categorie"))
    st.stop()

# Même gabarit de galerie que l'Annuaire (4 colonnes, vignette homogénéisée
# via photo_html/vignette_html, chips de catégorie) — mêmes fonctions
# partagées depuis annuaire.py, pour une seule apparence de galerie à
# maintenir plutôt que deux implémentations HTML qui finissent par diverger.
cols_par_ligne = 4
for i in range(0, len(lieux_affiches), cols_par_ligne):
    cols = st.columns(cols_par_ligne)
    for col, lieu in zip(cols, lieux_affiches[i:i + cols_par_ligne]):
        derive = derive_par_lieu.get(lieu.id)
        # Portfolio = sélection restreinte et curée (pas les 50 lieux de
        # l'Annuaire) : traduire à la volée chaque carte reste raisonnable,
        # contrairement à une grille complète.
        donnees = donnees_a_afficher(store, derive)
        with col:
            with st.container(border=True):
                if derive and derive.photo_url:
                    st.markdown(photo_html(derive.photo_url), unsafe_allow_html=True)
                else:
                    emoji, couleur = default_visual(lieu.nom, donnees)
                    st.markdown(vignette_html(emoji, couleur), unsafe_allow_html=True)
                if donnees.get("categories"):
                    st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
                if derive and derive.besoins_mis_en_avant:
                    st.markdown(besoins_chips_html(derive.besoins_mis_en_avant), unsafe_allow_html=True)
                if st.button(lieu.nom, key=f"open_portfolio_{lieu.id}", use_container_width=True):
                    st.session_state["portfolio_open_lieu_id"] = lieu.id
                    st.rerun()
                st.caption(f"{lieu.pays or ''} — {lieu.region or ''}")
                # La campagne est la raison d'être de cette page : mise en
                # avant avant le résumé, dans un encadré distinct plutôt que
                # noyée après la description générale du lieu.
                if derive and derive.campagne_texte:
                    with st.container(border=True):
                        st.markdown(f"**{t('portfolio.campagne_titre')}**")
                        st.write(derive.campagne_texte)
                        if derive.campagne_objectif:
                            st.markdown(t("portfolio.objectif_label", valeur=derive.campagne_objectif))
                        if derive.campagne_contact:
                            st.markdown(t("portfolio.contact_label", valeur=derive.campagne_contact))
                if donnees.get("resume"):
                    st.caption(donnees["resume"])
