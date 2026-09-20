"""Tools Claude pour l'assistant RAG : recherche sémantique dans le corpus
documentaire (Chroma) et requêtes contraintes sur les données structurées
(fichiers déposés + réponses collectées via l'agent d'entretien). Les
opérations sur les données structurées sont volontairement limitées à un
petit jeu prédéfini (filter/groupby_count/describe/head) plutôt que de
l'exécution de code arbitraire généré par le LLM — évite tout risque
d'injection tout en couvrant les besoins d'analyse courants.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from ..annuaire import field_label
from ..db.store import Store
from .embeddings import VoyageEmbedder
from .structured_query import apply_condition as _apply_condition
from .structured_query import rendre_hashable as _rendre_hashable
from .structured_query import run_structured_query
from .vectorstore import ChromaStore

CATALOG_PATH = Path("data/catalog.json")

TOOL_DEFINITIONS = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Recherche sémantique. Utiliser doc_type='profil_lieu' pour comparer des "
            "lieux entre eux ou trouver des lieux travaillant sur une thématique donnée "
            "(1 profil consolidé par lieu). Utiliser doc_type='connaissance_bibliotheque' "
            "pour un savoir transversal ajouté manuellement depuis la Bibliothèque (pas rattaché "
            "à un lieu précis) — recoupements, pratiques générales, résultats de recherches web "
            "ponctuelles. Utiliser doc_type='connaissance_trois_tiers' pour un savoir issu de la "
            "base de connaissances publique du réseau Trois-Tiers (méthodes, dispositifs, cadres "
            "juridiques ou de financement, ressources du réseau). Utiliser les autres doc_type "
            "pour retrouver un passage précis dans les interviews, rapports, résumés de datasets "
            "ou de géodonnées déposés. Renvoie les extraits les plus pertinents avec leur source, "
            "pour permettre de citer d'où vient l'information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "doc_type": {"type": "string",
                             "enum": ["profil_lieu", "interview", "rapport", "dataset_summary", "geodata",
                                      "connaissance_bibliotheque", "connaissance_trois_tiers"],
                             "description": "optionnel, pour restreindre la recherche à un type de source"},
                "top_k": {"type": "integer", "default": 6},
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_datasets",
        "description": (
            "Liste les jeux de données structurés disponibles pour "
            "query_structured_data : fichiers déposés (CSV/Excel/JSON/géodonnées) "
            "et les données collectées par l'agent d'entretien (réponses des "
            "tiers-lieux recensés)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_structured_data",
        "description": (
            "Exécute une opération contrainte sur un jeu de données structuré "
            "(voir list_datasets pour les noms disponibles et leurs colonnes)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_name": {"type": "string"},
                "operation": {"type": "string", "enum": ["head", "describe", "filter", "groupby_count"]},
                "params": {
                    "type": "object",
                    "description": (
                        "head: {n}. filter: {conditions: [{column, op, value}]} avec op parmi "
                        "eq/ne/in/gt/lt/contains. groupby_count: {by: [colonnes], target_column?}."
                    ),
                },
            },
            "required": ["dataset_name", "operation"],
        },
    },
]


def _load_catalog() -> dict:
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {"datasets": {}, "geodata": {}}


def reponses_long_dataframe(store: Store) -> pd.DataFrame:
    """Vue longue et interrogeable des réponses collectées par l'agent
    d'entretien : une ligne par (lieu, contributeur, champ, valeur).

    Batch plutôt qu'un get_all_answers_by_contributeur par lieu (qui fait
    lui-même 2 requêtes) : avec la quarantaine de lieux recensés, la version
    en boucle faisait une centaine d'allers-retours réseau séquentiels rien
    que pour cette vue — visible en production comme une lenteur nette de
    l'Observatoire, et comme source d'erreurs réseau intermittentes sur l'un
    de ces nombreux appels (httpx.ReadError constaté)."""
    lieux = store.list_tiers_lieux()
    reponses_par_lieu = store.get_all_answers_by_contributeur_batch([lieu.id for lieu in lieux])
    rows = []
    for lieu in lieux:
        par_contributeur = reponses_par_lieu.get(lieu.id, {})
        for contributeur_id, reponses in par_contributeur.items():
            for champ_id, valeur in reponses.items():
                rows.append({
                    "tiers_lieu": lieu.nom,
                    "pays": lieu.pays,
                    "region": lieu.region,
                    "contributeur_id": contributeur_id,
                    "champ": field_label(champ_id),
                    "champ_id": champ_id,
                    "valeur": valeur,
                })
    return pd.DataFrame(rows)


def lieux_enrichis_dataframe(store: Store) -> pd.DataFrame:
    """Vue plate des données dérivées (1 ligne par lieu) : utile pour filtrer
    par mots-clés/enjeux/activités sans passer par la recherche vectorielle.

    Un aller-retour réseau PAR lieu (get_lieu_derive dans une boucle) rendait
    l'Observatoire visiblement lent dès la quarantaine de lieux recensés, et
    exposait chaque chargement de page au risque qu'un de ces N appels
    échoue (constaté en production : httpx.ReadError intermittent) — un seul
    appel groupé (get_lieu_derive_batch) élimine les deux problèmes."""
    lieux = store.list_tiers_lieux()
    derives = store.get_lieu_derive_batch([lieu.id for lieu in lieux])
    rows = []
    for lieu in lieux:
        derive = derives.get(lieu.id)
        if not derive:
            continue
        # latitude/longitude (tiers_lieux, alimentées notamment par l'import
        # CommunECter) étaient absentes de cette vue — l'assistant RAG
        # répondait ne disposer d'aucune donnée de géolocalisation alors
        # qu'elle existe bel et bien pour une partie des lieux, juste jamais
        # exposée à ce dataset.
        row = {
            "tiers_lieu": lieu.nom, "pays": lieu.pays, "region": lieu.region,
            "latitude": lieu.latitude, "longitude": lieu.longitude,
        }
        row.update(derive.donnees)
        rows.append(row)
    return pd.DataFrame(rows)


def activite_ctg_dataframe(store: Store) -> pd.DataFrame:
    """Activité publique remontée de Changethegame pour les lieux liés
    (membres, discussions, mises à jour, quêtes, besoins) — alimentée par
    l'API POST /events (src/api/app.py)."""
    colonnes = ["tiers_lieu", "type", "titre", "texte", "url", "survenu_le"]
    evenements = store.list_evenements_ctg()
    if not evenements:
        return pd.DataFrame(columns=colonnes)
    noms = {lieu.id: lieu.nom for lieu in store.list_tiers_lieux()}
    return pd.DataFrame([
        {"tiers_lieu": noms[e["tiers_lieu_id"]], **{k: e[k] for k in colonnes[1:]}}
        for e in evenements if e["tiers_lieu_id"] in noms
    ], columns=colonnes)


def bonnes_pratiques_dataframe(store: Store) -> pd.DataFrame:
    """Retours d'expérience concrets et comparables entre lieux (montages
    financiers, partenariats, dispositifs de gouvernance...), capturés par
    l'agent d'entretien via `save_free_text_note(section_id="bonne_pratique")`
    quand un répondant mentionne un résultat chiffré ou nommé — voir la règle
    dédiée dans collecte_agent.SYSTEM_PROMPT. Conçu pour les échanges
    d'expérience entre lieux via la Bibliothèque, distinct des notes libres
    génériques (anecdotes, ressenti) qui ne sont pas exposées ici."""
    notes = store.get_notes_by_section_id("bonne_pratique")
    if not notes:
        return pd.DataFrame(columns=["tiers_lieu", "pays", "region", "texte"])
    lieux = {lieu.id: lieu for lieu in store.list_tiers_lieux()}
    rows = []
    for note in notes:
        lieu = lieux.get(note["tiers_lieu_id"])
        rows.append({
            "tiers_lieu": lieu.nom if lieu else None,
            "pays": lieu.pays if lieu else None,
            "region": lieu.region if lieu else None,
            "texte": note["texte"],
        })
    return pd.DataFrame(rows)


class RagToolHandler:
    def __init__(self, store: Store, embedder: Optional[VoyageEmbedder] = None,
                 vectorstore: Optional[ChromaStore] = None):
        self.store = store
        self.embedder = embedder or VoyageEmbedder()
        self.vectorstore = vectorstore or ChromaStore()

    def search_knowledge_base(self, tool_input: dict) -> dict:
        query = tool_input["query"]
        top_k = tool_input.get("top_k", 6)
        where = {"doc_type": tool_input["doc_type"]} if tool_input.get("doc_type") else None
        embedding = self.embedder.embed_query(query)
        hits = self.vectorstore.query(embedding, top_k=top_k, where=where)
        return {"results": hits}

    def list_datasets(self, _tool_input: dict) -> dict:
        catalog = _load_catalog()
        datasets = list(catalog.get("datasets", {}).values())
        geodata = list(catalog.get("geodata", {}).values())
        datasets.append({
            "name": "reponses_tiers_lieux",
            "type": "collecte",
            "columns": ["tiers_lieu", "pays", "region", "contributeur_id", "champ", "champ_id", "valeur"],
            "description": "Réponses brutes collectées par l'agent d'entretien, une ligne par (lieu, contributeur, champ).",
        })
        datasets.append({
            "name": "lieux_enrichis",
            "type": "derive",
            "columns": ["tiers_lieu", "pays", "region", "latitude", "longitude", "resume", "activites",
                        "publics", "territoire", "gouvernance", "ressources", "besoins", "modele_economique",
                        "partenaires", "competences", "projets", "enjeux", "mots_cles"],
            "description": ("Synthèses dérivées (1 ligne par lieu), produites par l'enrichissement LLM à partir "
                             "des réponses brutes. Utile pour filtrer par mots-clés/enjeux/activités en texte. "
                             "C'est ICI (pas reponses_tiers_lieux) que se trouvent latitude/longitude quand "
                             "elles sont connues (~37 lieux, via l'import CommunECter) — colonnes tiers_lieux, "
                             "jamais posées comme question du questionnaire donc absentes de reponses_tiers_lieux."),
        })
        datasets.append({
            "name": "activite_ctg",
            "type": "derive",
            "columns": ["tiers_lieu", "type", "titre", "texte", "url", "survenu_le"],
            "description": ("Activité publique remontée de Changethegame pour les lieux qui y sont liés : "
                             "membres, discussions, mises à jour, quêtes, besoins. Vide tant qu'aucun lieu "
                             "n'est lié. À consulter pour \"que se passe-t-il autour de tel lieu ?\"."),
        })
        datasets.append({
            "name": "bonnes_pratiques",
            "type": "notes",
            "columns": ["tiers_lieu", "pays", "region", "texte"],
            "description": ("Retours d'expérience concrets et comparables entre lieux (montages financiers, "
                             "partenariats, dispositifs de gouvernance, pivots de modèle économique...), "
                             "recueillis par l'agent d'entretien quand un répondant mentionne un résultat "
                             "chiffré ou nommé. À utiliser en priorité pour répondre à une question du type "
                             "\"comment tel lieu a-t-il fait pour...\" ou pour un partage d'expérience entre "
                             "lieux — plus précis que le résumé général de lieux_enrichis sur ce type de sujet."),
        })
        return {"datasets": datasets, "geodata": geodata}

    def _load_dataframe(self, dataset_name: str) -> Optional[pd.DataFrame]:
        if dataset_name == "reponses_tiers_lieux":
            return reponses_long_dataframe(self.store)
        if dataset_name == "lieux_enrichis":
            return lieux_enrichis_dataframe(self.store)
        if dataset_name == "bonnes_pratiques":
            return bonnes_pratiques_dataframe(self.store)
        if dataset_name == "activite_ctg":
            return activite_ctg_dataframe(self.store)
        catalog = _load_catalog()
        entry = catalog.get("datasets", {}).get(dataset_name)
        if not entry:
            return None
        path = Path(entry["path"])
        suffix = path.suffix.lower()
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path)
        if suffix == ".json":
            return pd.read_json(path)
        return None

    def query_structured_data(self, tool_input: dict) -> dict:
        dataset_name = tool_input["dataset_name"]
        operation = tool_input["operation"]
        params = tool_input.get("params", {}) or {}

        df = self._load_dataframe(dataset_name)
        if df is None:
            return {"error": f"dataset inconnu: {dataset_name}"}
        return run_structured_query(df, operation, params)

    def execute(self, tool_name: str, tool_input: dict) -> dict:
        handler = getattr(self, tool_name, None)
        if handler is None:
            return {"error": f"tool inconnu: {tool_name}"}
        return handler(tool_input)
