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

import re
from typing import Optional

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
TIMEOUT_S = 10
USER_AGENT = "Mozilla/5.0 (compatible; lieux-hybrides-territoires/1.0; +https://troistiers.space)"


NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"

# Ordre de préférence pour le nom de commune : en Belgique `municipality` est
# la commune administrative (Gembloux) alors que village/town donnent la
# localité (Grand-Leez) ; en France c'est city/town/village.
_CLES_COMMUNE = ("municipality", "city", "town", "village", "hamlet")


def extraire_commune_cp(resultat: dict) -> dict:
    """{commune, code_postal} d'un résultat Nominatim (addressdetails=1) ;
    None pour ce qui manque. Un code postal composé ("5030;5031") garde le
    premier."""
    adresse = (resultat or {}).get("address") or {}
    commune = next((adresse[c] for c in _CLES_COMMUNE if adresse.get(c)), None)
    code_postal = (adresse.get("postcode") or "").split(";")[0].strip() or None
    return {"commune": commune, "code_postal": code_postal}


def _nettoyer(adresse: str) -> str:
    # Une précision entre parenthèses ("... (à cheval sur X et Y)") fait
    # échouer le parsing d'adresse de Nominatim — vécu sur "Ma ferme" : la
    # réponse brute (utile telle quelle pour l'affichage) était géocodée
    # telle quelle, échouait silencieusement, et le lieu n'apparaissait
    # jamais sur la carte. Seule la requête de géocodage est nettoyée, la
    # réponse enregistrée reste inchangée.
    return re.sub(r"\s*\([^)]*\)", "", adresse).strip() or adresse


def geocoder_adresse_detail(adresse: str, pays: Optional[str] = None) -> Optional[dict]:
    """Renvoie {latitude, longitude, commune, code_postal} pour cette adresse,
    ou None si introuvable ou en cas d'échec réseau — ne lève jamais, un
    géocodage raté ne doit jamais empêcher l'enregistrement de la réponse."""
    adresse = (adresse or "").strip()
    if not adresse:
        return None
    adresse_geocodage = _nettoyer(adresse)
    requete = f"{adresse_geocodage}, {pays}" if pays else adresse_geocodage
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": requete, "format": "json", "limit": 1, "addressdetails": 1},
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
        return {"latitude": float(resultats[0]["lat"]), "longitude": float(resultats[0]["lon"]),
                **extraire_commune_cp(resultats[0])}
    except (KeyError, ValueError, TypeError):
        return None


def geocoder_adresse(adresse: str, pays: Optional[str] = None) -> Optional[tuple]:
    """Renvoie (latitude, longitude) pour cette adresse, ou None."""
    detail = geocoder_adresse_detail(adresse, pays)
    return (detail["latitude"], detail["longitude"]) if detail else None


def commune_cp_depuis_coordonnees(latitude: float, longitude: float) -> Optional[dict]:
    """{commune, code_postal} du point donné (reverse Nominatim), ou None.
    Sert au rattrapage des lieux qui ont déjà des coordonnées : la commune
    reste ainsi cohérente avec le point réellement servi."""
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={"lat": latitude, "lon": longitude, "format": "json", "zoom": 14, "addressdetails": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_S,
        )
        response.raise_for_status()
        return extraire_commune_cp(response.json())
    except Exception:
        return None
