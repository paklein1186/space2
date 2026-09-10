"""Page publique : statistiques quantitatives et qualitatives agrégées sur
l'ensemble des lieux recensés. Aucune connexion requise — s'appuie sur les
policies RLS publiques de lieu_derive/tiers_lieux/reponses non confidentielles
(cf. migration_002_steward_and_liens.sql)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src.agent.rag_tools import lieux_enrichis_dataframe, reponses_long_dataframe
from src.db.factory import get_store
from src.questionnaire.schema import CATEGORIES_POSSIBLES
from src.theme import inject_theme

load_dotenv()
st.set_page_config(page_title="Observatoire — Lieux hybrides et territoires", layout="wide")
inject_theme()

st.title("Observatoire des lieux hybrides et territoires")
st.caption("Relevés statistiques, publics, sur l'ensemble des lieux recensés dans l'Annuaire.")

store = get_store()
df_lieux = lieux_enrichis_dataframe(store)

if df_lieux.empty:
    st.info("Aucun lieu enrichi pour l'instant — revenez une fois que des synthèses auront été générées.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Lieux recensés", len(df_lieux))
col2.metric("Pays représentés", int(df_lieux["pays"].nunique(dropna=True)) if "pays" in df_lieux else 0)
col3.metric("Régions représentées", int(df_lieux["region"].nunique(dropna=True)) if "region" in df_lieux else 0)

st.divider()
col_cat, col_pays = st.columns(2)
with col_cat:
    st.subheader("Répartition par catégorie")
    if "categories" in df_lieux.columns:
        cat_counts = pd.Series(
            [c for cats in df_lieux["categories"].dropna() for c in (cats or [])]
        ).value_counts().reindex(CATEGORIES_POSSIBLES).dropna()
        if not cat_counts.empty:
            st.bar_chart(cat_counts)
        else:
            st.caption("Aucune catégorie attribuée pour l'instant.")
with col_pays:
    st.subheader("Répartition par pays")
    if "pays" in df_lieux.columns and df_lieux["pays"].notna().any():
        st.bar_chart(df_lieux["pays"].value_counts(dropna=True))
    else:
        st.caption("Pays non renseigné pour l'instant.")

df_reponses = reponses_long_dataframe(store)
df_reponses_dedup = (
    df_reponses.drop_duplicates(subset=["tiers_lieu", "champ_id"]) if not df_reponses.empty else df_reponses
)

col_milieu, col_region = st.columns(2)
with col_milieu:
    st.subheader("Répartition par milieu")
    milieu_df = df_reponses_dedup[df_reponses_dedup["champ_id"] == "milieu"] if not df_reponses_dedup.empty else df_reponses_dedup
    if not milieu_df.empty:
        st.bar_chart(milieu_df["valeur"].value_counts())
    else:
        st.caption("Milieu non renseigné pour l'instant.")
with col_region:
    st.subheader("Répartition par région")
    if "region" in df_lieux.columns and df_lieux["region"].notna().any():
        st.bar_chart(df_lieux["region"].value_counts(dropna=True).head(15))
    else:
        st.caption("Région non renseignée pour l'instant.")

st.divider()
st.subheader("Mots-clés les plus fréquents")
if "mots_cles" in df_lieux.columns:
    mots = pd.Series(
        [m for mots in df_lieux["mots_cles"].dropna() for m in (mots or [])]
    ).value_counts().head(20)
    if not mots.empty:
        st.bar_chart(mots)
    else:
        st.caption("Pas encore de mots-clés générés.")

st.divider()
st.subheader("Enjeux et besoins par catégorie")
st.caption("Vue qualitative : synthèses des enjeux exprimés, groupées par catégorie.")
if "categories" in df_lieux.columns:
    au_moins_une = False
    for cat in CATEGORIES_POSSIBLES:
        sous_ensemble = df_lieux[df_lieux["categories"].apply(lambda cs: cat in (cs or []))]
        if sous_ensemble.empty:
            continue
        au_moins_une = True
        with st.expander(f"{cat} ({len(sous_ensemble)} lieu(x))"):
            for _, row in sous_ensemble.iterrows():
                if row.get("enjeux"):
                    st.markdown(f"**{row.get('tiers_lieu', '—')}** — {row['enjeux']}")
                if row.get("besoins"):
                    st.caption(f"Besoins : {row['besoins']}")
    if not au_moins_une:
        st.caption("Aucune catégorie attribuée pour l'instant.")
