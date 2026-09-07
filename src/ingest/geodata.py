"""Chargement des géodonnées (.geojson, .shp) déposées dans data/raw/geodata/.

Le chargement des shapefiles nécessite `geopandas` (et GDAL). S'il n'est pas
installé, seul le format .geojson reste supporté via un parsing JSON pur —
le pipeline continue sans bloquer le reste de l'indexation, avec un
avertissement.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

SUPPORTED_GEODATA_SUFFIXES = {".geojson", ".shp"}


def _try_geopandas():
    try:
        import geopandas as gpd

        return gpd
    except ImportError:
        return None


def load_geodata_features(path: Path) -> list:
    """Renvoie une liste de dicts {properties, geometry_type} par feature."""
    suffix = path.suffix.lower()
    gpd = _try_geopandas()

    if gpd is not None:
        gdf = gpd.read_file(str(path))
        features = []
        for _, row in gdf.iterrows():
            props = row.drop(labels=["geometry"]).to_dict()
            geom = row.geometry
            features.append({"properties": props, "geometry_type": geom.geom_type if geom else None})
        return features

    if suffix == ".shp":
        warnings.warn(
            f"geopandas n'est pas installé : impossible de charger le shapefile {path}. "
            "Installez geopandas pour indexer ce fichier."
        )
        return []

    # Fallback pur JSON pour les .geojson
    data = json.loads(path.read_text(encoding="utf-8"))
    features = []
    for feat in data.get("features", []):
        features.append({
            "properties": feat.get("properties", {}),
            "geometry_type": (feat.get("geometry") or {}).get("type"),
        })
    return features


def geodata_summary_text(name: str, features: list) -> str:
    if not features:
        return f"Couche géographique '{name}' : aucune feature exploitable."
    exemple_props = features[0]["properties"]
    return (
        f"Couche géographique '{name}' : {len(features)} lieux/objets. "
        f"Exemple d'attributs : {exemple_props}"
    )


def geodata_feature_records(name: str, features: list) -> list:
    """Un texte descriptif par feature, pour indexation individuelle si le
    volume est raisonnable (utile pour retrouver un lieu précis par recherche
    sémantique plutôt que seulement par le résumé de couche)."""
    records = []
    for i, feat in enumerate(features):
        props_text = ", ".join(f"{k}: {v}" for k, v in feat["properties"].items())
        records.append({"text": f"Couche '{name}', objet {i}: {props_text}", "index": i})
    return records
