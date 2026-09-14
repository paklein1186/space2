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

from src.annuaire import category_chips_html, default_visual, photo_html, vignette_html
from src.db.factory import get_store
from src.theme import apply_theme

load_dotenv()
st.set_page_config(page_title="Portfolio — Lieux hybrides et territoires", layout="wide")
apply_theme()

st.title("Portfolio")
st.caption("Une sélection de lieux et de leurs campagnes de besoins actuelles.")

store = get_store()
lieux = store.list_lieux_portfolio()

if not lieux:
    st.info("Aucun lieu mis en avant pour l'instant.")
    st.stop()

# Même gabarit de galerie que l'Annuaire (4 colonnes, vignette homogénéisée
# via photo_html/vignette_html, chips de catégorie) — mêmes fonctions
# partagées depuis annuaire.py, pour une seule apparence de galerie à
# maintenir plutôt que deux implémentations HTML qui finissent par diverger.
cols_par_ligne = 4
for i in range(0, len(lieux), cols_par_ligne):
    cols = st.columns(cols_par_ligne)
    for col, lieu in zip(cols, lieux[i:i + cols_par_ligne]):
        derive = store.get_lieu_derive(lieu.id)
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
                st.markdown(f"**{lieu.nom}**")
                st.caption(f"{lieu.pays or ''} — {lieu.region or ''}")
                if donnees.get("resume"):
                    st.write(donnees["resume"])
                if derive and derive.campagne_texte:
                    st.markdown("**Campagne en cours**")
                    st.write(derive.campagne_texte)
                    if derive.campagne_objectif:
                        st.markdown(f"🎯 **Objectif :** {derive.campagne_objectif}")
                    if derive.campagne_contact:
                        st.markdown(f"✉️ **Contact :** {derive.campagne_contact}")
                if derive and derive.lien_externe:
                    st.markdown(f"[🔗 En savoir plus]({derive.lien_externe})")
