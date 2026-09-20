"""Jeux de données PUBLICS servis à l'API /ask (Changethegame).

Différence clé avec `rag_tools.reponses_long_dataframe` : ici, aucune donnée
confidentielle ni interne ne sort — réponses `confidentiel`, réponses de
contributeurs bloqués, champs réservés aux rôles internes (finances, RH...) et
identifiants de contributeurs sont tous exclus. Le module n'importe ni
Streamlit, ni Chroma, ni Voyage."""

from __future__ import annotations

import threading
import time
from typing import Optional

import pandas as pd

from ..db.store import Store
from ..questionnaire.schema import TOUS_ROLES, get_field

TTL_SECONDES = 300

DATASETS = {
    "lieux": {
        "description": (
            "Un lieu par ligne : nom, pays, région, latitude/longitude quand connues, puis la "
            "synthèse dérivée (resume, categories, activites, publics, territoire, gouvernance, "
            "ressources, besoins, partenaires, competences, projets, enjeux, mots_cles...)."
        ),
    },
    "reponses_publiques": {
        "columns": ["tiers_lieu", "pays", "region", "champ", "champ_id", "valeur"],
        "description": (
            "Réponses brutes NON confidentielles au questionnaire, format long : une ligne par "
            "(lieu, champ). Les colonnes sont toujours ces mêmes colonnes génériques — filtre sur "
            "'champ' avec 'contains' pour retrouver un sujet précis."
        ),
    },
}


def champ_public(champ_id: str) -> bool:
    """Un champ n'est exposable que s'il existe dans le questionnaire, n'est
    pas confidentiel par défaut et est ouvert à tous les rôles — un champ
    inconnu (ancien schéma) est exclu par prudence."""
    champ = get_field(champ_id)
    if champ is None or champ.confidential_default:
        return False
    return champ.roles is None or set(TOUS_ROLES) <= set(champ.roles)


def construire_datasets(store: Store) -> dict:
    lieux = store.list_tiers_lieux()
    ids = [lieu.id for lieu in lieux]
    derives = store.get_lieu_derive_batch(ids)
    reponses = store.get_public_answers_batch(ids)

    lignes_lieux, lignes_reponses = [], []
    for lieu in lieux:
        base = {"tiers_lieu": lieu.nom, "pays": lieu.pays, "region": lieu.region}
        derive = derives.get(lieu.id)
        if derive:
            lignes_lieux.append({**base, "latitude": lieu.latitude, "longitude": lieu.longitude,
                                 **derive.donnees})
        for champ_id, valeur in (reponses.get(lieu.id) or {}).items():
            if not champ_public(champ_id):
                continue
            lignes_reponses.append({**base, "champ": get_field(champ_id).label,
                                    "champ_id": champ_id, "valeur": valeur})
    return {
        "lieux": pd.DataFrame(lignes_lieux),
        "reponses_publiques": pd.DataFrame(
            lignes_reponses, columns=["tiers_lieu", "pays", "region", "champ", "champ_id", "valeur"]),
    }


class DonneesPubliques:
    """Cache TTL des jeux de données : évite de relire toute la base à chaque
    question, tout en se rafraîchissant quand les lieux évoluent."""

    def __init__(self, store: Store, ttl: float = TTL_SECONDES):
        self.store = store
        self.ttl = ttl
        self._lock = threading.Lock()
        self._cache: Optional[dict] = None
        self._charge_a = 0.0

    def get(self) -> dict:
        with self._lock:
            if self._cache is None or time.monotonic() - self._charge_a > self.ttl:
                self._cache = construire_datasets(self.store)
                self._charge_a = time.monotonic()
            return self._cache

    def catalogue(self) -> list:
        datasets = self.get()
        return [
            {"name": nom, "columns": list(datasets[nom].columns), "row_count": len(datasets[nom]),
             "description": meta["description"]}
            for nom, meta in DATASETS.items()
        ]
