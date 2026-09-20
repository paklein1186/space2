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
from ..questionnaire.schema import champ_public, get_field  # noqa: F401 (champ_public ré-exporté)

TTL_SECONDES = 300

DATASETS = {
    "lieux": {
        "description": (
            "Un lieu par ligne : nom, pays, région, latitude/longitude quand connues, puis la "
            "synthèse publique (resume, categories, activites, publics, territoire, besoins, "
            "partenaires, competences, projets, enjeux, mots_cles, besoins_mis_en_avant). Les "
            "colonnes de synthèse sont vides pour un lieu dont les réponses publiques manquent."
        ),
    },
    "activite_ctg": {
        "description": (
            "Activité publique remontée de Changethegame pour les lieux qui y sont liés : "
            "membres, discussions, mises à jour, quêtes, besoins (type, titre, texte, url, date)."
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


CHAMPS_PROFIL = ["resume", "categories", "mots_cles", "activites", "publics", "territoire",
                 "partenaires", "competences", "projets", "enjeux", "besoins"]


def profil_public(lieu, derive, adresse=None) -> dict:
    """Vue publique d'un lieu, partagée entre le dataset `lieux` de l'agent et
    le flux GET /lieux. N'utilise que `donnees_publiques` — jamais `donnees`
    (synthèse interne, qui peut refléter des réponses confidentielles)."""
    publiques = (derive.donnees_publiques if derive else None) or {}
    profil = {
        "space2_id": lieu.id, "ctg_entity_id": lieu.ctg_entity_id, "tiers_lieu": lieu.nom,
        "pays": lieu.pays, "region": lieu.region,
        # Adresse = réponse publique (non confidentielle) telle que saisie —
        # surtout un nom de commune ; commune/code_postal viennent du
        # géocodage (voir geocoding.py, migration_010).
        "adresse": adresse, "commune": lieu.commune, "code_postal": lieu.code_postal,
        "latitude": lieu.latitude, "longitude": lieu.longitude,
    }
    for cle in CHAMPS_PROFIL:
        profil[cle] = publiques.get(cle)
    if derive:
        profil["besoins_mis_en_avant"] = list(derive.besoins_mis_en_avant or [])
        profil["lien_externe"] = derive.lien_externe
        profil["photo_url"] = derive.photo_url
        # L'appel de fonds n'est public que pour les lieux choisis pour le Portfolio.
        profil["campagne"] = ({"texte": derive.campagne_texte, "objectif": derive.campagne_objectif,
                               "contact": derive.campagne_contact}
                              if derive.inclus_portfolio and derive.campagne_texte else None)
        profil["updated_at"] = derive.donnees_publiques_maj
    else:
        profil.update({"besoins_mis_en_avant": [], "lien_externe": None, "photo_url": None,
                       "campagne": None, "updated_at": None})
    return profil


def construire_datasets(store: Store) -> dict:
    lieux = store.list_tiers_lieux()
    ids = [lieu.id for lieu in lieux]
    derives = store.get_lieu_derive_batch(ids)
    reponses = store.get_public_answers_batch(ids)
    noms = {lieu.id: lieu.nom for lieu in lieux}

    lignes_lieux, lignes_reponses = [], []
    for lieu in lieux:
        profil = profil_public(lieu, derives.get(lieu.id), (reponses.get(lieu.id) or {}).get("adresse"))
        profil.pop("space2_id"), profil.pop("campagne"), profil.pop("updated_at")
        lignes_lieux.append(profil)
        base = {"tiers_lieu": lieu.nom, "pays": lieu.pays, "region": lieu.region}
        for champ_id, valeur in (reponses.get(lieu.id) or {}).items():
            if not champ_public(champ_id):
                continue
            lignes_reponses.append({**base, "champ": get_field(champ_id).label,
                                    "champ_id": champ_id, "valeur": valeur})
    lignes_evenements = [
        {"tiers_lieu": noms[e["tiers_lieu_id"]], "type": e["type"], "titre": e["titre"],
         "texte": e["texte"], "url": e["url"], "survenu_le": e["survenu_le"]}
        for e in store.list_evenements_ctg() if e["tiers_lieu_id"] in noms
    ]
    return {
        "lieux": pd.DataFrame(lignes_lieux),
        "reponses_publiques": pd.DataFrame(
            lignes_reponses, columns=["tiers_lieu", "pays", "region", "champ", "champ_id", "valeur"]),
        "activite_ctg": pd.DataFrame(
            lignes_evenements, columns=["tiers_lieu", "type", "titre", "texte", "url", "survenu_le"]),
    }


def flux_lieux(store: Store, updated_since: Optional[str] = None) -> list:
    """Flux GET /lieux : TOUS les lieux (avec ou sans synthèse publique). Un
    lieu sans date de mise à jour (pas encore de synthèse publique) est
    toujours inclus, pour que ctg le crée dès sa première apparition."""
    lieux = store.list_tiers_lieux()
    ids = [lieu.id for lieu in lieux]
    derives = store.get_lieu_derive_batch(ids)
    adresses = store.get_public_answers_batch(ids)
    profils = [profil_public(lieu, derives.get(lieu.id), (adresses.get(lieu.id) or {}).get("adresse"))
               for lieu in lieux]
    if updated_since:
        profils = [p for p in profils if not p["updated_at"] or str(p["updated_at"]) > updated_since]
    return profils


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
