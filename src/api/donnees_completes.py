"""Jeux de données de l'API /ask en mode accès complet : mêmes vues que l'agent
du site (rag_tools), mais sans ce que les répondants ont explicitement marqué
confidentiel.

- Réponses : les lignes `confidentiel` et celles des contributeurs bloqués sont
  écartées.
- Synthèses (lieu_derive.donnees, profil sémantique) : générées à partir de
  TOUTES les réponses, elles ont pu absorber une réponse confidentielle. Pour
  un lieu qui en a au moins une, on remplace donc la synthèse par la synthèse
  publique (donnees_publiques) ; les autres lieux gardent la synthèse complète.
"""

from __future__ import annotations

import pandas as pd

from ..agent.enrichissement import CHAMPS_DERIVES
from ..db.store import LieuDerive, Store
from ..questionnaire.schema import field_label

COLONNES_REPONSES = ["tiers_lieu", "pays", "region", "contributeur_id", "champ", "champ_id", "valeur"]


def reponses_sans_confidentiel(store: Store) -> pd.DataFrame:
    """Équivalent de rag_tools.reponses_long_dataframe, sans les réponses
    marquées confidentielles."""
    lieux = store.list_tiers_lieux()
    par_lieu = store.get_all_answers_by_contributeur_batch([l.id for l in lieux], exclure_confidentiel=True)
    lignes = []
    for lieu in lieux:
        for contributeur_id, reponses in par_lieu.get(lieu.id, {}).items():
            for champ_id, valeur in reponses.items():
                lignes.append({"tiers_lieu": lieu.nom, "pays": lieu.pays, "region": lieu.region,
                               "contributeur_id": contributeur_id, "champ": field_label(champ_id),
                               "champ_id": champ_id, "valeur": valeur})
    return pd.DataFrame(lignes, columns=COLONNES_REPONSES)


def synthese_partageable(derive: LieuDerive, a_du_confidentiel: bool) -> dict:
    """Synthèse à exposer : la complète, ou — si le lieu a des réponses
    confidentielles — la publique (clés absentes = None)."""
    if not a_du_confidentiel:
        return dict(derive.donnees)
    publiques = derive.donnees_publiques or {}
    return {cle: publiques.get(cle) for cle in CHAMPS_DERIVES}


def texte_profil_partageable(derive: LieuDerive, a_du_confidentiel: bool) -> str:
    """Texte de profil pour la recherche sémantique : le profil complet, ou une
    version reconstituée depuis la synthèse publique pour un lieu ayant des
    réponses confidentielles."""
    if not a_du_confidentiel:
        return derive.profil_semantique_texte or ""
    publiques = derive.donnees_publiques or {}
    morceaux = []
    for cle, valeur in publiques.items():
        if isinstance(valeur, list):
            valeur = ", ".join(map(str, valeur))
        if valeur:
            morceaux.append(f"{cle} : {valeur}")
    return "\n".join(morceaux)


def lieux_enrichis_sans_confidentiel(store: Store) -> pd.DataFrame:
    """Équivalent de rag_tools.lieux_enrichis_dataframe (une ligne par lieu,
    avec latitude/longitude), avec repli sur la synthèse publique pour les
    lieux qui ont des réponses confidentielles."""
    lieux = store.list_tiers_lieux()
    ids = [l.id for l in lieux]
    derives = store.get_lieu_derive_batch(ids)
    confidentiels = store.get_lieux_avec_confidentiel(ids)
    lignes = []
    for lieu in lieux:
        derive = derives.get(lieu.id)
        if not derive:
            continue
        ligne = {"tiers_lieu": lieu.nom, "pays": lieu.pays, "region": lieu.region,
                 "commune": lieu.commune, "code_postal": lieu.code_postal,
                 "latitude": lieu.latitude, "longitude": lieu.longitude}
        ligne.update(synthese_partageable(derive, lieu.id in confidentiels))
        lignes.append(ligne)
    return pd.DataFrame(lignes)
