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
from src.i18n import t
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
        st.caption("Aucune donnée pour l'instant.")
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
with st.spinner("Chargement des données..."):
    df_lieux = lieux_enrichis_dataframe(store)

if df_lieux.empty:
    st.info("Aucun lieu enrichi pour l'instant — revenez une fois que des synthèses auront été générées.")
    st.stop()

with st.spinner("Chargement des données..."):
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
col1.metric("Lieux recensés", len(df_lieux))
col2.metric("Pays représentés", int(df_lieux["pays"].nunique(dropna=True)) if "pays" in df_lieux else 0)
col3.metric("Régions représentées", int(df_lieux["region"].nunique(dropna=True)) if "region" in df_lieux else 0)

surfaces = pd.to_numeric(_valeurs("surface_batie_m2"), errors="coerce").dropna()
col4.metric(
    "Surface bâtie connue", f"{int(surfaces.sum()):,} m²".replace(",", " ") if not surfaces.empty else "—",
    help=f"Somme sur les {len(surfaces)} lieu(x) ayant renseigné leur surface — sous-estimée, "
         "la plupart des lieux ne l'ont pas encore déclarée." if not surfaces.empty else None,
)
etp = pd.to_numeric(_valeurs("etp_geres"), errors="coerce").dropna()
col5.metric(
    "ETP gérés connus", f"{etp.sum():g}" if not etp.empty else "—",
    help=f"Somme sur les {len(etp)} lieu(x) ayant renseigné leurs ETP — sous-estimée, "
         "la plupart des lieux ne l'ont pas encore déclaré." if not etp.empty else None,
)

st.divider()
col_cat, col_pays = st.columns(2)
with col_cat:
    st.subheader("Répartition par catégorie")
    if "categories" in df_lieux.columns:
        cat_counts = pd.Series(
            [c for cats in df_lieux["categories"].dropna() for c in (cats or [])]
        ).value_counts().reindex(CATEGORIES_POSSIBLES).dropna()
        if not cat_counts.empty:
            _graphique_barres(cat_counts)
        else:
            st.caption("Aucune catégorie attribuée pour l'instant.")
with col_pays:
    st.subheader("Répartition par pays")
    if "pays" in df_lieux.columns and df_lieux["pays"].notna().any():
        _graphique_barres(df_lieux["pays"].value_counts(dropna=True))
    else:
        st.caption("Pays non renseigné pour l'instant.")

col_milieu, col_region = st.columns(2)
with col_milieu:
    st.subheader("Répartition par milieu")
    milieu_df = df_reponses_dedup[df_reponses_dedup["champ_id"] == "milieu"] if not df_reponses_dedup.empty else df_reponses_dedup
    if not milieu_df.empty:
        _graphique_barres(milieu_df["valeur"].value_counts())
    else:
        st.caption("Milieu non renseigné pour l'instant.")
with col_region:
    st.subheader("Répartition par région")
    if "region" in df_lieux.columns and df_lieux["region"].notna().any():
        _graphique_barres(df_lieux["region"].value_counts(dropna=True).head(15))
    else:
        st.caption("Région non renseignée pour l'instant.")

st.divider()
col_annee, col_statut = st.columns(2)
with col_annee:
    st.subheader("Évolution du réseau dans le temps")
    st.caption("Nombre de lieux ouverts par année (année extraite de la date déclarée).")
    dates = _valeurs("date_ouverture").dropna().astype(str)
    annees = dates.apply(lambda d: (re.search(r"(19|20)\d{2}", d) or [None]).group() if re.search(r"(19|20)\d{2}", d) else None) \
        if not dates.empty else pd.Series(dtype=object)
    annees = annees.dropna()
    if not annees.empty:
        _graphique_barres(annees.value_counts().sort_index())
        st.caption(f"Basé sur les {len(annees)} lieu(x) ayant déclaré une date d'ouverture.")
    else:
        st.caption("Aucune date d'ouverture déclarée pour l'instant.")
with col_statut:
    st.subheader("Statut juridique")
    statuts = _valeurs("statut_juridique").dropna()
    if not statuts.empty:
        _graphique_barres(statuts.value_counts())
        st.caption(f"Basé sur les {len(statuts)} lieu(x) ayant déclaré leur statut juridique.")
    else:
        st.caption("Aucun statut juridique déclaré pour l'instant.")

st.divider()
st.subheader("Fréquentation, mobilité et rayonnement")
st.caption(
    "Indicateurs récemment ajoutés au questionnaire (fréquentation, provenance des usagers, "
    "modes de déplacement) — ils s'affichent automatiquement ici au fur et à mesure que des "
    "lieux y répondent."
)


def _graphique_bandes(champ_id: str, titre: str) -> None:
    valeurs = _valeurs(champ_id).dropna()
    st.markdown(f"**{titre}**")
    if valeurs.empty:
        st.caption("Pas encore de réponse pour cet indicateur.")
        return
    ordonnee = valeurs.value_counts().reindex(BANDE_INTENSITE).dropna()
    _graphique_barres(ordonnee)
    st.caption(f"n = {len(valeurs)} lieu(x)")


col_freq, col_evol = st.columns(2)
with col_freq:
    freq = pd.to_numeric(_valeurs("frequentation_semaine_type"), errors="coerce").dropna()
    st.markdown("**Fréquentation moyenne sur une bonne semaine**")
    if not freq.empty:
        st.metric("Passages / semaine (moyenne des lieux répondants)", f"{freq.mean():.0f}")
        st.caption(f"n = {len(freq)} lieu(x)")
    else:
        st.caption("Pas encore de réponse pour cet indicateur.")
with col_evol:
    evol = _valeurs("evolution_frequentation_3ans").dropna()
    st.markdown("**Évolution de la fréquentation (3 ans)**")
    if not evol.empty:
        _graphique_barres(evol.value_counts())
        st.caption(f"n = {len(evol)} lieu(x)")
    else:
        st.caption("Pas encore de réponse pour cet indicateur.")

col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    _graphique_bandes("usagers_mode_voiture", "Part venant en voiture")
with col_m2:
    _graphique_bandes("usagers_mode_velo", "Part venant à vélo")
with col_m3:
    _graphique_bandes("usagers_mode_pied", "Part venant à pied")
with col_m4:
    _graphique_bandes("usagers_mode_transport_commun", "Part en transport en commun")

col_p1, col_p2, col_p3 = st.columns(3)
with col_p1:
    _graphique_bandes("provenance_usagers_commune", "Provenance : commune d'implantation")
with col_p2:
    _graphique_bandes("provenance_usagers_limitrophe", "Provenance : commune limitrophe")
with col_p3:
    _graphique_bandes("provenance_usagers_plus_loin", "Provenance : plus loin")

st.divider()
st.subheader("Mots-clés les plus fréquents")
if "mots_cles" in df_lieux.columns:
    mots = pd.Series(
        [m for mots in df_lieux["mots_cles"].dropna() for m in (mots or [])]
    ).value_counts().head(20)
    if not mots.empty:
        _graphique_barres(mots)
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

st.divider()
st.subheader("Besoins par sphère")
st.caption(
    "Vue synthétique des besoins déclarés à l'entretien (« 📣 Rendre visibles vos besoins "
    "actuels »), regroupés par grande sphère plutôt que listés un par un — dépliez un besoin "
    "pour voir quels lieux précisément l'ont exprimé."
)
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
if not lignes_besoins:
    st.caption("Aucun besoin déclaré pour l'instant.")
else:
    df_spheres = pd.DataFrame(lignes_besoins)
    cols_spheres = st.columns(3)
    for col, sphere in zip(cols_spheres, ORDRE_SPHERES):
        with col:
            st.markdown(f"**{sphere}**")
            sous = df_spheres[df_spheres["sphere"] == sphere]
            if sous.empty:
                st.caption("Aucun besoin déclaré dans cette sphère pour l'instant.")
                continue
            par_besoin = sorted(
                (
                    (besoin, sorted(set(groupe["lieu"])))
                    for besoin, groupe in sous.groupby("besoin")
                ),
                key=lambda t: len(t[1]), reverse=True,
            )
            for besoin, lieux_concernes in par_besoin:
                with st.expander(f"{besoin} ({len(lieux_concernes)})"):
                    st.caption(", ".join(lieux_concernes))
