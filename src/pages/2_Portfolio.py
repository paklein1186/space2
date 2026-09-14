"""Page publique : vitrine en lecture seule des lieux sélectionnés par un
administrateur pour y présenter leur campagne de besoins. Aucune connexion
requise — la curation (cocher "inclure au Portfolio", éditer la campagne) se
fait depuis l'Annuaire, section Administration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
from dotenv import load_dotenv

from src.annuaire import (
    SECTIONS_SYNTHESE,
    category_chips_html,
    default_visual,
    photo_html,
    texte_en_points,
    vignette_html,
)
from src.db.factory import get_store
from src.theme import apply_theme

load_dotenv()
st.set_page_config(page_title="Portfolio — Lieux hybrides et territoires", layout="wide")
apply_theme()


@st.dialog("Fiche du lieu", width="large")
def _fiche_publique_dialog(lieu, derive) -> None:
    """Version publique (sans connexion) de la fiche de l'Annuaire : mêmes
    informations de synthèse, sans les sections de modération/administration
    qui n'ont pas de sens pour un visiteur anonyme. La campagne, raison
    d'être de cette page, est mise en avant avant le reste plutôt que
    mélangée aux autres sections."""
    donnees = derive.donnees if derive else {}
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

    if derive and derive.campagne_texte:
        st.divider()
        with st.container(border=True):
            st.markdown("#### 📣 Campagne en cours")
            st.write(derive.campagne_texte)
            col_obj, col_contact = st.columns(2)
            with col_obj:
                if derive.campagne_objectif:
                    st.markdown(f"🎯 **Objectif :** {derive.campagne_objectif}")
            with col_contact:
                if derive.campagne_contact:
                    st.markdown(f"✉️ **Contact :** {derive.campagne_contact}")

    if donnees.get("resume"):
        st.divider()
        st.write(donnees["resume"])

    if derive:
        # derive.sources[cle] non vide = section réellement alimentée par des
        # réponses (pas la formule de remplissage du prompt d'enrichissement
        # pour homogénéiser la longueur) — même logique que la fiche privée,
        # sans avoir besoin de résoudre les sources en détail (pas de
        # popover "Sources" ici, superflu pour un visiteur public).
        sections_a_afficher = [(cle, titre) for cle, titre in SECTIONS_SYNTHESE[1:] if derive.sources.get(cle)]
        if sections_a_afficher:
            st.divider()
            cols = st.columns(3)
            for i, (cle, titre) in enumerate(sections_a_afficher):
                texte = donnees.get(cle) or "—"
                with cols[i % 3]:
                    st.markdown(f"**{titre}**")
                    st.caption(texte_en_points(texte))

    if derive and derive.lien_externe:
        st.divider()
        st.markdown(f"[🔗 En savoir plus]({derive.lien_externe})")


st.title("Portfolio")
st.caption("Une sélection de lieux et de leurs campagnes de besoins actuelles.")

store = get_store()
lieux = store.list_lieux_portfolio()

if not lieux:
    st.info("Aucun lieu mis en avant pour l'instant.")
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
        _fiche_publique_dialog(lieu_ouvert, derive_par_lieu.get(lieu_id))

categories_disponibles = sorted({
    c for derive in derive_par_lieu.values() for c in (derive.donnees.get("categories") or [])
})
filtre_categories = st.multiselect(
    "Filtrer par catégorie", options=categories_disponibles, placeholder="Toutes les catégories",
)


def _categories(lieu) -> set:
    derive = derive_par_lieu.get(lieu.id)
    return set((derive.donnees.get("categories") if derive else None) or [])


lieux_affiches = lieux
if filtre_categories:
    lieux_affiches = [l for l in lieux_affiches if _categories(l) & set(filtre_categories)]

if not lieux_affiches:
    st.info("Aucun lieu ne correspond à cette catégorie.")
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
        donnees = derive.donnees if derive else {}
        with col:
            with st.container(border=True):
                if derive and derive.photo_url:
                    st.markdown(photo_html(derive.photo_url), unsafe_allow_html=True)
                else:
                    emoji, couleur = default_visual(lieu.nom, donnees)
                    st.markdown(vignette_html(emoji, couleur), unsafe_allow_html=True)
                if donnees.get("categories"):
                    st.markdown(category_chips_html(donnees["categories"]), unsafe_allow_html=True)
                if st.button(lieu.nom, key=f"open_portfolio_{lieu.id}", use_container_width=True):
                    st.session_state["portfolio_open_lieu_id"] = lieu.id
                    st.rerun()
                st.caption(f"{lieu.pays or ''} — {lieu.region or ''}")
                # La campagne est la raison d'être de cette page : mise en
                # avant avant le résumé, dans un encadré distinct plutôt que
                # noyée après la description générale du lieu.
                if derive and derive.campagne_texte:
                    with st.container(border=True):
                        st.markdown("**📣 Campagne en cours**")
                        st.write(derive.campagne_texte)
                        if derive.campagne_objectif:
                            st.markdown(f"🎯 **Objectif :** {derive.campagne_objectif}")
                        if derive.campagne_contact:
                            st.markdown(f"✉️ **Contact :** {derive.campagne_contact}")
                if donnees.get("resume"):
                    st.caption(donnees["resume"])
