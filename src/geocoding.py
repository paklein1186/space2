"""Géocodage d'une adresse texte (telle que répondue à l'entretien) en
coordonnées lat/lon, via Nominatim (OpenStreetMap) — gratuit, sans clé API.

À ne pas confondre avec la tentative précédente (revenue en arrière) qui
utilisait Nominatim pour CLASSER un lieu rural/urbain à partir de ses
coordonnées : ce module fait l'inverse, une conversion adresse → coordonnées,
l'usage standard pour lequel un service de géocodage est fiable — la
classification rural/urbain, elle, nécessiterait une vraie donnée de densité
(Eurostat DEGURBA), pas du texte libre mal normalisé.
"""

from __future__ import annotations

from typing import Optional

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_S = 10
USER_AGENT = "Mozilla/5.0 (compatible; lieux-hybrides-territoires/1.0; +https://troistiers.space)"


def geocoder_adresse(adresse: str, pays: Optional[str] = None) -> Optional[tuple]:
    """Renvoie (latitude, longitude) pour cette adresse, ou None si
    introuvable ou en cas d'échec réseau — ne lève jamais, un géocodage raté
    ne doit jamais empêcher l'enregistrement de la réponse elle-même."""
    adresse = (adresse or "").strip()
    if not adresse:
        return None
    requete = f"{adresse}, {pays}" if pays else adresse
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": requete, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        resultats = response.json()
    except Exception:
        return None
    if not resultats:
        return None
    try:
        return float(resultats[0]["lat"]), float(resultats[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
