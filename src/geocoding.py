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

# Ordre de préférence pour le nom de commune, selon le pays (les conventions
# OpenStreetMap diffèrent) :
# - Belgique : `municipality` est la commune administrative (Gembloux) alors
#   que village/town donnent la localité/section (Grand-Leez) ;
# - ailleurs (France...) : la commune est city/town/village, alors que
#   `municipality` désigne l'arrondissement (vécu : Villecien, commune de
#   l'Yonne, ressortait « Sens », le chef-lieu de son arrondissement).
_CLES_COMMUNE_BELGIQUE = ("municipality", "city", "town", "village", "hamlet")
_CLES_COMMUNE_DEFAUT = ("city", "town", "village", "hamlet", "municipality")


_CLES_LOCALITE = ("village", "hamlet")


def _nom_simple(adresse: Optional[str]) -> Optional[str]:
    """L'adresse saisie si c'est un simple nom (« Gesves ») : ni chiffre, ni
    virgule, ni parenthèse — sinon None."""
    texte = (adresse or "").strip()
    if texte and not re.search(r"[\d,()]", texte) and len(texte) <= 40:
        return texte
    return None


def extraire_commune_cp(resultat: dict, adresse: Optional[str] = None) -> dict:
    """{commune, code_postal} d'un résultat Nominatim (addressdetails=1) ;
    None pour ce qui manque. Un code postal composé ("5030;5031") garde le
    premier.

    En Belgique, OpenStreetMap n'a parfois pas la commune (`municipality`)
    mais seulement la section (Gesves ressortait « Faulx-Les Tombes ») : dans
    ce cas, si l'adresse saisie par le lieu est un simple nom, c'est ce nom
    qui fait foi."""
    donnees = (resultat or {}).get("address") or {}
    belgique = donnees.get("country_code") == "be"
    cles = _CLES_COMMUNE_BELGIQUE if belgique else _CLES_COMMUNE_DEFAUT
    cle = next((c for c in cles if donnees.get(c)), None)
    commune = donnees.get(cle) if cle else None
    if belgique and (cle is None or cle in _CLES_LOCALITE):
        commune = _nom_simple(adresse) or commune
    code_postal = (donnees.get("postcode") or "").split(";")[0].strip() or None
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
                **extraire_commune_cp(resultats[0], adresse)}
    except (KeyError, ValueError, TypeError):
        return None


def geocoder_adresse(adresse: str, pays: Optional[str] = None) -> Optional[tuple]:
    """Renvoie (latitude, longitude) pour cette adresse, ou None."""
    detail = geocoder_adresse_detail(adresse, pays)
    return (detail["latitude"], detail["longitude"]) if detail else None


def commune_cp_depuis_coordonnees(latitude: float, longitude: float,
                                  adresse: Optional[str] = None) -> Optional[dict]:
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
        return extraire_commune_cp(response.json(), adresse)
    except Exception:
        return None
