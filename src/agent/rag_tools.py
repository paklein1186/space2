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
from .vectorstore import ChromaStore

CATALOG_PATH = Path("data/catalog.json")

TOOL_DEFINITIONS = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Recherche sémantique. Utiliser doc_type='profil_lieu' pour comparer des "
            "lieux entre eux ou trouver des lieux travaillant sur une thématique donnée "
            "(1 profil consolidé par lieu). Utiliser les autres doc_type pour retrouver "
            "un passage précis dans les interviews, rapports, résumés de datasets ou de "
            "géodonnées déposés. Renvoie les extraits les plus pertinents avec leur "
            "source, pour permettre de citer d'où vient l'information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "doc_type": {"type": "string",
                             "enum": ["profil_lieu", "interview", "rapport", "dataset_summary", "geodata"],
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


def _reponses_long_dataframe(store: Store) -> pd.DataFrame:
    """Vue longue et interrogeable des réponses collectées par l'agent
    d'entretien : une ligne par (lieu, contributeur, champ, valeur)."""
    rows = []
    for lieu in store.list_tiers_lieux():
        par_contributeur = store.get_all_answers_by_contributeur(lieu.id)
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


def _lieux_enrichis_dataframe(store: Store) -> pd.DataFrame:
    """Vue plate des données dérivées (1 ligne par lieu) : utile pour filtrer
    par mots-clés/enjeux/activités sans passer par la recherche vectorielle."""
    rows = []
    for lieu in store.list_tiers_lieux():
        derive = store.get_lieu_derive(lieu.id)
        if not derive:
            continue
        row = {"tiers_lieu": lieu.nom, "pays": lieu.pays, "region": lieu.region}
        row.update(derive.donnees)
        rows.append(row)
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
            "columns": ["tiers_lieu", "pays", "region", "resume", "activites", "publics", "territoire",
                        "gouvernance", "ressources", "besoins", "modele_economique", "partenaires",
                        "competences", "projets", "enjeux", "mots_cles"],
            "description": ("Synthèses dérivées (1 ligne par lieu), produites par l'enrichissement LLM à partir "
                             "des réponses brutes. Utile pour filtrer par mots-clés/enjeux/activités en texte."),
        })
        return {"datasets": datasets, "geodata": geodata}

    def _load_dataframe(self, dataset_name: str) -> Optional[pd.DataFrame]:
        if dataset_name == "reponses_tiers_lieux":
            return _reponses_long_dataframe(self.store)
        if dataset_name == "lieux_enrichis":
            return _lieux_enrichis_dataframe(self.store)
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

        if operation == "head":
            n = params.get("n", 5)
            return {"rows": df.head(n).to_dict(orient="records")}

        if operation == "describe":
            return {"describe": json.loads(df.describe(include="all").to_json())}

        if operation == "filter":
            filtered = df
            for cond in params.get("conditions", []):
                filtered = _apply_condition(filtered, cond)
            return {"row_count": len(filtered), "rows": filtered.head(50).to_dict(orient="records")}

        if operation == "groupby_count":
            by = params.get("by", [])
            target = params.get("target_column")
            if not by:
                return {"error": "groupby_count nécessite 'by'"}
            if target:
                result = df.groupby(by)[target].nunique()
            else:
                result = df.groupby(by).size()
            return {"result": json.loads(result.to_json())}

        return {"error": f"opération inconnue: {operation}"}

    def execute(self, tool_name: str, tool_input: dict) -> dict:
        handler = getattr(self, tool_name, None)
        if handler is None:
            return {"error": f"tool inconnu: {tool_name}"}
        return handler(tool_input)


def _apply_condition(df: pd.DataFrame, cond: dict) -> pd.DataFrame:
    column, op, value = cond["column"], cond["op"], cond.get("value")
    if column not in df.columns:
        return df.iloc[0:0]
    series = df[column]
    if op == "eq":
        return df[series == value]
    if op == "ne":
        return df[series != value]
    if op == "in":
        return df[series.isin(value)]
    if op == "gt":
        return df[series > value]
    if op == "lt":
        return df[series < value]
    if op == "contains":
        return df[series.apply(lambda v: (value in v) if isinstance(v, (list, tuple)) else (str(value) in str(v)))]
    raise ValueError(f"Opérateur de filtre inconnu: {op}")
