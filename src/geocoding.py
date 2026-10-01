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


def geocoder_adresse_avec_repli(adresse: str, pays: Optional[str] = None) -> Optional[dict]:
    """Comme `geocoder_adresse_detail`, mais retente avec des versions de plus
    en plus générales (segments de tête retirés un à un : typiquement rue,
    puis code postal, pour ne garder que la commune/le village/le hameau) si
    l'adresse complète n'est pas reconnue par Nominatim — un numéro ou un nom
    de rue mal formé fait sinon échouer tout le géocodage alors que la
    localité seule, elle, est quasi toujours reconnue. Place dans ce cas le
    lieu au centre de cette localité plutôt que nulle part."""
    detail = geocoder_adresse_detail(adresse, pays)
    if detail:
        return detail
    segments = [s.strip() for s in adresse.split(",") if s.strip()]
    for debut in range(1, len(segments)):
        repli = ", ".join(segments[debut:])
        detail = geocoder_adresse_detail(repli, pays)
        if detail:
            return detail
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


def geocoder_lieu_admin(store, tiers_lieu_id: str, pays: Optional[str] = None,
                        commune_connue: Optional[str] = None) -> dict:
    """Géocode à la demande un lieu qui n'a jamais eu de coordonnées. Utilise
    la réponse « adresse » quand elle existe ; sinon, un lieu créé en
    acceptant un candidat d'extraction (`creer_lieu_depuis_candidat`) n'en a
    jamais eu — seule sa commune est connue (posée directement sur la fiche,
    sans jamais passer par une réponse « adresse ») — d'où `commune_connue`,
    à défaut géocodée elle-même pour placer au moins le lieu au centre de ce
    village/cette commune plutôt que nulle part (cas vécu : 13 lieux issus de
    l'extraction, dont Badinage Artistique, tous sans la moindre réponse
    « adresse »). Déclenchement unitaire et immédiat depuis la fiche admin —
    à la différence de `geocode_backfill`, un script de rattrapage en masse,
    limité à une requête Nominatim par seconde sur l'ensemble des lieux.
    Utilise le repli progressif de `geocoder_adresse_avec_repli` (rue mal
    formée → on retombe sur la commune/le village). Pose latitude/longitude
    (+ commune/code_postal quand disponibles, sans jamais bloquer dessus) sur
    le lieu. Renvoie {"statut": "ok", "latitude", "longitude"} |
    {"statut": "sans_adresse"} | {"statut": "introuvable"}."""
    adresses = store.get_public_answers_batch([tiers_lieu_id])
    adresse = (adresses.get(tiers_lieu_id) or {}).get("adresse") or ""
    requete = adresse.strip() or (commune_connue or "").strip()
    if not requete:
        return {"statut": "sans_adresse"}
    detail = geocoder_adresse_avec_repli(requete, pays)
    if not detail:
        return {"statut": "introuvable"}
    store.update_tiers_lieu(tiers_lieu_id, latitude=detail["latitude"], longitude=detail["longitude"])
    try:
        store.update_tiers_lieu(tiers_lieu_id, commune=detail.get("commune"), code_postal=detail.get("code_postal"))
    except Exception:
        pass
    return {"statut": "ok", "latitude": detail["latitude"], "longitude": detail["longitude"]}
