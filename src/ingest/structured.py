"""Chargement des datasets tabulaires (CSV/Excel/JSON) déposés dans
data/raw/datasets/ : constitution du catalogue et d'un résumé en langage
naturel indexable pour la recherche sémantique."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SUPPORTED_DATASET_SUFFIXES = {".csv", ".xlsx", ".xls", ".json"}


def load_dataset(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Format de dataset non supporté: {suffix}")


def dataset_summary_text(name: str, df: pd.DataFrame) -> str:
    colonnes = ", ".join(df.columns.astype(str))
    echantillon = df.head(3).to_dict(orient="records")
    return (
        f"Jeu de données '{name}' : {len(df)} lignes, colonnes : {colonnes}. "
        f"Échantillon de lignes : {echantillon}"
    )


def dataset_catalog_entry(name: str, path: Path, df: pd.DataFrame) -> dict:
    return {
        "name": name,
        "path": str(path),
        "type": "dataset",
        "columns": list(df.columns.astype(str)),
        "row_count": len(df),
    }
