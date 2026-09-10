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

from src.annuaire import default_visual
from src.db.factory import get_store

load_dotenv()
st.set_page_config(page_title="Portfolio — Lieux hybrides et territoires", layout="wide")

st.title("Portfolio")
st.caption("Une sélection de lieux et de leurs campagnes de besoins actuelles.")

store = get_store()
lieux = store.list_lieux_portfolio()

if not lieux:
    st.info("Aucun lieu mis en avant pour l'instant.")
    st.stop()

cols_par_ligne = 3
for i in range(0, len(lieux), cols_par_ligne):
    cols = st.columns(cols_par_ligne)
    for col, lieu in zip(cols, lieux[i:i + cols_par_ligne]):
        derive = store.get_lieu_derive(lieu.id)
        donnees = derive.donnees if derive else {}
        with col:
            with st.container(border=True):
                if derive and derive.photo_url:
                    st.image(derive.photo_url, use_container_width=True)
                else:
                    emoji, couleur = default_visual(lieu.nom, donnees)
                    st.markdown(
                        f'<div style="width:100%;height:9rem;border-radius:8px;background:{couleur};'
                        f'display:flex;align-items:center;justify-content:center;font-size:2.2rem;">'
                        f'{emoji}</div>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f"### {lieu.nom}")
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
