"""Page publique : statistiques quantitatives et qualitatives agrégées sur
l'ensemble des lieux recensés. Aucune connexion requise — s'appuie sur les
policies RLS publiques de lieu_derive/tiers_lieux/reponses non confidentielles
(cf. migration_002_steward_and_liens.sql).

Sélectionnée via st.Page dans src/app.py (menu de navigation unifié) : le
set_page_config()/apply_theme()/load_dotenv() de app.py s'appliquent déjà
avant que cette page ne s'exécute, donc pas besoin de les refaire ici — les
répéter lèverait une erreur (set_page_config ne peut être appelé qu'une
fois par run)."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

from src.agent.rag_tools import lieux_enrichis_dataframe, reponses_long_dataframe
from src.db.factory import get_admin_store, get_store
from src.i18n import t, t_categorie
from src.questionnaire.schema import BANDE_INTENSITE, CATEGORIES_POSSIBLES

st.title(t("observatoire.title"))
st.caption(t("observatoire.caption"))


def _graphique_barres(series: pd.Series) -> None:
    """Graphique en barres horizontales en HTML/CSS pur (aucune dépendance
    externe) — remplace st.bar_chart, qui repose sur Altair et plante en
    production : l'hébergeur (Streamlit Community Cloud) fait tourner cette
    app sous Python 3.14 malgré runtime.txt épinglé sur 3.11 et un reboot
    complet demandé, et le schéma vegalite d'Altair utilise une fonctionnalité
    de typing (PEP 728, TypedDict(closed=True)) qui casse sous ce Python —
    non résolu côté plateforme à ce jour, donc contourné ici plutôt que
    d'attendre un correctif hors de notre contrôle."""
    if series.empty:
        st.caption(t("observatoire.aucune_donnee"))
        return
    maximum = series.max()
    lignes = []
    for label, valeur in series.items():
        largeur = 0 if not maximum else round(100 * valeur / maximum)
        libelle = html.escape(str(label))
        lignes.append(
            '<div style="display:flex; align-items:center; gap:0.5rem; margin-bottom:6px;">'
            f'<div style="flex:0 0 42%; font-size:0.85rem; text-align:right; overflow:hidden; '
            f'text-overflow:ellipsis; white-space:nowrap;" title="{libelle}">{libelle}</div>'
            '<div style="flex:1; background:var(--sp-border-soft); border-radius:4px; height:16px;">'
            f'<div style="width:{largeur}%; background:var(--sp-accent); height:100%; border-radius:4px;"></div>'
            '</div>'
            f'<div style="flex:0 0 2.5rem; font-size:0.8rem; opacity:0.8;">{valeur}</div>'
            '</div>'
        )
    st.markdown(f'<div style="font-family:inherit;">{"".join(lignes)}</div>', unsafe_allow_html=True)


def _store_pour_agregats():
    """Statistiques publiques : utilise le store admin (service_role) plutôt
    que le store public pour cette page. Raison — pas un choix de facilité :
    reponses_long_dataframe() passe par get_all_answers_by_contributeur(),
    qui filtre d'abord les contributeurs bloqués via une lecture de la table
    `contributeurs` ; or RLS n'y autorise un utilisateur qu'à voir SES
    PROPRES lignes (user_id = auth.uid()) — pour un visiteur anonyme,
    auth.uid() est nul, cette lecture ne renvoie donc jamais aucune ligne, et
    le filtre "contributeur actif" exclut alors TOUTES les réponses par
    excès de prudence. Résultat concret constaté : les graphiques "Milieu",
    "Statut juridique", "Année d'ouverture" restaient vides pour tout
    visiteur non connecté, alors que `reponses` a bien une policy RLS
    publique — seule la vérification de blocage, en amont, coupait tout.
    Seuls des agrégats (comptages, distributions) quittent cette page,
    jamais de donnée nominative, donc contourner RLS ici reste sûr. Repli
    sur le store public si la clé service_role n'est pas configurée, pour ne
    jamais faire planter une page publique pour cette seule raison."""
    try:
        return get_admin_store()
    except RuntimeError:
        return get_store()


store = _store_pour_agregats()
with st.spinner(t("observatoire.chargement")):
    df_lieux = lieux_enrichis_dataframe(store)

if df_lieux.empty:
    st.info(t("observatoire.aucun_lieu_enrichi"))
    st.stop()

with st.spinner(t("observatoire.chargement")):
    df_reponses = reponses_long_dataframe(store)
# Une même question a pu être répondue par plusieurs contributeurs d'un même
# lieu (parfois avec des valeurs différentes) : un lieu ne doit compter
# qu'une fois par champ dans les agrégats, pas une fois par contributeur.
df_reponses_dedup = (
    df_reponses.drop_duplicates(subset=["tiers_lieu", "champ_id"]) if not df_reponses.empty else df_reponses
)


def _valeurs(champ_id: str) -> pd.Series:
    """Valeurs déclarées pour un champ donné, une seule fois par lieu."""
    if df_reponses_dedup.empty:
        return pd.Series(dtype=object)
    return df_reponses_dedup[df_reponses_dedup["champ_id"] == champ_id]["valeur"]


col1, col2, col3, col4, col5 = st.columns(5)
col1.metric(t("observatoire.lieux_recenses"), len(df_lieux))
col2.metric(t("observatoire.pays_representes"), int(df_lieux["pays"].nunique(dropna=True)) if "pays" in df_lieux else 0)
col3.metric(t("observatoire.regions_representees"), int(df_lieux["region"].nunique(dropna=True)) if "region" in df_lieux else 0)

surfaces = pd.to_numeric(_valeurs("surface_batie_m2"), errors="coerce").dropna()
col4.metric(
    t("observatoire.surface_batie"), f"{int(surfaces.sum()):,} m²".replace(",", " ") if not surfaces.empty else "—",
    help=t("observatoire.surface_batie_help", n=len(surfaces)) if not surfaces.empty else None,
)
etp = pd.to_numeric(_valeurs("etp_geres"), errors="coerce").dropna()
col5.metric(
    t("observatoire.etp_geres"), f"{etp.sum():g}" if not etp.empty else "—",
    help=t("observatoire.etp_geres_help", n=len(etp)) if not etp.empty else None,
)

st.divider()
col_cat, col_pays = st.columns(2)
with col_cat:
    st.subheader(t("observatoire.repartition_categorie"))
    if "categories" in df_lieux.columns:
        cat_counts = pd.Series(
            [c for cats in df_lieux["categories"].dropna() for c in (cats or [])]
        ).value_counts().reindex(CATEGORIES_POSSIBLES).dropna()
        cat_counts.index = [t_categorie(c) for c in cat_counts.index]
        if not cat_counts.empty:
            _graphique_barres(cat_counts)
        else:
            st.caption(t("observatoire.aucune_categorie"))
with col_pays:
    st.subheader(t("observatoire.repartition_pays"))
    if "pays" in df_lieux.columns and df_lieux["pays"].notna().any():
        _graphique_barres(df_lieux["pays"].value_counts(dropna=True))
    else:
        st.caption(t("observatoire.pays_non_renseigne"))

col_milieu, col_region = st.columns(2)
with col_milieu:
    st.subheader(t("observatoire.repartition_milieu"))
    milieu_df = df_reponses_dedup[df_reponses_dedup["champ_id"] == "milieu"] if not df_reponses_dedup.empty else df_reponses_dedup
    if not milieu_df.empty:
        _graphique_barres(milieu_df["valeur"].value_counts())
    else:
        st.caption(t("observatoire.milieu_non_renseigne"))
with col_region:
    st.subheader(t("observatoire.repartition_region"))
    if "region" in df_lieux.columns and df_lieux["region"].notna().any():
        _graphique_barres(df_lieux["region"].value_counts(dropna=True).head(15))
    else:
        st.caption(t("observatoire.region_non_renseignee"))

st.divider()
col_annee, col_statut = st.columns(2)
with col_annee:
    st.subheader(t("observatoire.evolution_reseau"))
    st.caption(t("observatoire.evolution_reseau_caption"))
    dates = _valeurs("date_ouverture").dropna().astype(str)
    annees = dates.apply(lambda d: (re.search(r"(19|20)\d{2}", d) or [None]).group() if re.search(r"(19|20)\d{2}", d) else None) \
        if not dates.empty else pd.Series(dtype=object)
    annees = annees.dropna()
    if not annees.empty:
        _graphique_barres(annees.value_counts().sort_index())
        st.caption(t("observatoire.base_sur_date_ouverture", n=len(annees)))
    else:
        st.caption(t("observatoire.aucune_date_ouverture"))
with col_statut:
    st.subheader(t("observatoire.statut_juridique"))
    statuts = _valeurs("statut_juridique").dropna()
    if not statuts.empty:
        _graphique_barres(statuts.value_counts())
        st.caption(t("observatoire.base_sur_statut", n=len(statuts)))
    else:
        st.caption(t("observatoire.aucun_statut"))

st.divider()
st.subheader(t("observatoire.frequentation_titre"))
st.caption(t("observatoire.frequentation_caption"))


def _graphique_bandes(champ_id: str, titre: str) -> None:
    valeurs = _valeurs(champ_id).dropna()
    st.markdown(f"**{titre}**")
    if valeurs.empty:
        st.caption(t("observatoire.pas_encore_reponse"))
        return
    ordonnee = valeurs.value_counts().reindex(BANDE_INTENSITE).dropna()
    _graphique_barres(ordonnee)
    st.caption(t("observatoire.n_lieux", n=len(valeurs)))


col_freq, col_evol = st.columns(2)
with col_freq:
    freq = pd.to_numeric(_valeurs("frequentation_semaine_type"), errors="coerce").dropna()
    st.markdown(f"**{t('observatoire.frequentation_moyenne_titre')}**")
    if not freq.empty:
        st.metric(t("observatoire.passages_semaine"), f"{freq.mean():.0f}")
        st.caption(t("observatoire.n_lieux", n=len(freq)))
    else:
        st.caption(t("observatoire.pas_encore_reponse"))
with col_evol:
    evol = _valeurs("evolution_frequentation_3ans").dropna()
    st.markdown(f"**{t('observatoire.evolution_frequentation_titre')}**")
    if not evol.empty:
        _graphique_barres(evol.value_counts())
        st.caption(t("observatoire.n_lieux", n=len(evol)))
    else:
        st.caption(t("observatoire.pas_encore_reponse"))

col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    _graphique_bandes("usagers_mode_voiture", t("observatoire.mode_voiture"))
with col_m2:
    _graphique_bandes("usagers_mode_velo", t("observatoire.mode_velo"))
with col_m3:
    _graphique_bandes("usagers_mode_pied", t("observatoire.mode_pied"))
with col_m4:
    _graphique_bandes("usagers_mode_transport_commun", t("observatoire.mode_transport_commun"))

col_p1, col_p2, col_p3 = st.columns(3)
with col_p1:
    _graphique_bandes("provenance_usagers_commune", t("observatoire.provenance_commune"))
with col_p2:
    _graphique_bandes("provenance_usagers_limitrophe", t("observatoire.provenance_limitrophe"))
with col_p3:
    _graphique_bandes("provenance_usagers_plus_loin", t("observatoire.provenance_plus_loin"))

st.divider()
st.subheader(t("observatoire.mots_cles_titre"))
if "mots_cles" in df_lieux.columns:
    mots = pd.Series(
        [m for mots in df_lieux["mots_cles"].dropna() for m in (mots or [])]
    ).value_counts().head(20)
    if not mots.empty:
        _graphique_barres(mots)
    else:
        st.caption(t("observatoire.pas_de_mots_cles"))

st.divider()
st.subheader(t("observatoire.enjeux_besoins_titre"))
st.caption(t("observatoire.enjeux_besoins_caption"))
if "categories" in df_lieux.columns:
    au_moins_une = False
    for cat in CATEGORIES_POSSIBLES:
        sous_ensemble = df_lieux[df_lieux["categories"].apply(lambda cs: cat in (cs or []))]
        if sous_ensemble.empty:
            continue
        au_moins_une = True
        with st.expander(f"{t_categorie(cat)} ({t('observatoire.lieu_x', n=len(sous_ensemble))})"):
            for _, row in sous_ensemble.iterrows():
                if row.get("enjeux"):
                    st.markdown(f"**{row.get('tiers_lieu', '—')}** — {row['enjeux']}")
                if row.get("besoins"):
                    st.caption(t("observatoire.besoins_label", texte=row["besoins"]))
    if not au_moins_une:
        st.caption(t("observatoire.aucune_categorie"))

st.divider()
st.subheader(t("observatoire.besoins_sphere_titre"))
st.caption(t("observatoire.besoins_sphere_caption"))
# Regroupement en trois sphères (cadre systémique large, pas une catégorie du
# questionnaire) : Sociosphère (gouvernance, collectif, réseau, cadre légal),
# Technosphère (argent, outils, infrastructure, savoir-faire technique),
# Biosphère (vivant, énergie, alimentation, écologie). "Aucun besoin
# identifié" et "Autre" ne sont pas de vrais besoins classifiables, exclus.
SPHERES_BESOINS = {
    "Gouvernance / gestion de collectif": "Sociosphère",
    "Médiation de conflits": "Sociosphère",
    "Repenser l'organisationnel et les processus de décision": "Sociosphère",
    "Communication": "Sociosphère",
    "Activation de communauté d'usagers": "Sociosphère",
    "Ancrage territorial / partenariats": "Sociosphère",
    "Événementiel (conception ou production d'événements)": "Sociosphère",
    "Aide juridique": "Sociosphère",
    "Gestion de projet": "Sociosphère",
    "Structure d'accueil de bénévoles": "Sociosphère",
    "Montée en compétence de l'équipe": "Sociosphère",
    "Mise en réseau avec d'autres tiers-lieux": "Sociosphère",
    "Comment implémenter des services publics": "Sociosphère",
    "Plan financier et pérennisation": "Technosphère",
    "Développement entrepreneurial / rapport à l'argent des usagers": "Technosphère",
    "Lancement de services de proximité": "Technosphère",
    "Usages d'outils numériques": "Technosphère",
    "Gestion financière, administrative et comptabilité": "Technosphère",
    "Ressources pratiques et inspirations (modèles, fieldtrips...)": "Technosphère",
    "Rénovation / obstacles architecturaux": "Technosphère",
    "Centre logistique ou compostage": "Technosphère",
    "Aide sur systèmes énergétiques/hydriques": "Biosphère",
    "Innovation low-tech, éco-construction ou économie circulaire": "Biosphère",
    "Activités agricoles ou alimentaires": "Biosphère",
}
ORDRE_SPHERES = ["Sociosphère", "Technosphère", "Biosphère"]

besoins_df = (
    df_reponses_dedup[df_reponses_dedup["champ_id"] == "types_soutien_souhaites"]
    if not df_reponses_dedup.empty else df_reponses_dedup
)
lignes_besoins = [
    {"lieu": row["tiers_lieu"], "besoin": besoin, "sphere": SPHERES_BESOINS[besoin]}
    for _, row in besoins_df.iterrows()
    for besoin in (row["valeur"] or [])
    if besoin in SPHERES_BESOINS
]
SPHERE_I18N_KEYS = {
    "Sociosphère": "observatoire.sociosphere",
    "Technosphère": "observatoire.technosphere",
    "Biosphère": "observatoire.biosphere",
}

if not lignes_besoins:
    st.caption(t("observatoire.aucun_besoin_declare"))
else:
    df_spheres = pd.DataFrame(lignes_besoins)
    cols_spheres = st.columns(3)
    for col, sphere in zip(cols_spheres, ORDRE_SPHERES):
        with col:
            st.markdown(f"**{t(SPHERE_I18N_KEYS[sphere])}**")
            sous = df_spheres[df_spheres["sphere"] == sphere]
            if sous.empty:
                st.caption(t("observatoire.aucun_besoin_sphere"))
                continue
            par_besoin = sorted(
                (
                    (besoin, sorted(set(groupe["lieu"])))
                    for besoin, groupe in sous.groupby("besoin")
                ),
                key=lambda paire: len(paire[1]), reverse=True,
            )
            for besoin, lieux_concernes in par_besoin:
                with st.expander(f"{besoin} ({len(lieux_concernes)})"):
                    st.caption(", ".join(lieux_concernes))
