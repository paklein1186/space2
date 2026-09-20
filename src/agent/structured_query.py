"""Opérations contraintes sur un DataFrame (head/describe/filter/groupby_count),
partagées entre l'assistant RAG interne (rag_tools.py) et l'API publique
(src/api). Module volontairement sans dépendance à Streamlit, Chroma ou
Voyage : l'API doit pouvoir l'importer sans embarquer tout ça.

Volontairement limité à un petit jeu prédéfini plutôt que d'exécuter du code
généré par le LLM — évite tout risque d'injection."""

from __future__ import annotations

import json

import pandas as pd


def rendre_hashable(df: pd.DataFrame) -> pd.DataFrame:
    """Convertit toute colonne contenant des valeurs liste (ex. réponse à un
    champ multi_choice) en chaîne jointe — pandas a besoin de valeurs
    hashables pour describe()/groupby()/isin(), et une liste ne l'est pas."""
    if df.empty:
        return df
    df = df.copy()
    for col in df.columns:
        if df[col].map(lambda v: isinstance(v, list)).any():
            df[col] = df[col].apply(lambda v: ", ".join(map(str, v)) if isinstance(v, list) else v)
    return df


def apply_condition(df: pd.DataFrame, cond: dict) -> pd.DataFrame:
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


def run_structured_query(df: pd.DataFrame, operation: str, params: dict) -> dict:
    # La colonne "valeur" de reponses_tiers_lieux (et "categories"/
    # "mots_cles" de lieux_enrichis) contient des listes pour les champs
    # multi_choice — describe()/groupby_count()/filter() lèvent tous
    # TypeError: unhashable type: 'list' dès que Claude choisit une telle
    # colonne pour grouper, dédupliquer ou comparer. Les rendre hashables
    # ici, une fois pour toutes les opérations, plutôt que de gérer le
    # cas dans chacune séparément.
    df = rendre_hashable(df)

    if operation == "head":
        n = params.get("n", 5)
        return {"rows": df.head(n).to_dict(orient="records")}

    if operation == "describe":
        return {"describe": json.loads(df.describe(include="all").to_json())}

    if operation == "filter":
        filtered = df
        for cond in params.get("conditions", []):
            filtered = apply_condition(filtered, cond)
        return {"row_count": len(filtered), "rows": filtered.head(50).to_dict(orient="records")}

    if operation == "groupby_count":
        by = params.get("by", [])
        target = params.get("target_column")
        if not by:
            return {"error": "groupby_count nécessite 'by'"}
        colonnes_inconnues = [c for c in [*by, target] if c and c not in df.columns]
        if colonnes_inconnues:
            return {
                "error": f"colonne(s) inconnue(s) pour ce dataset : {colonnes_inconnues}",
                "colonnes_disponibles": list(df.columns),
            }
        if target:
            result = df.groupby(by)[target].nunique()
        else:
            result = df.groupby(by).size()
        return {"result": json.loads(result.to_json())}

    return {"error": f"opération inconnue: {operation}"}
