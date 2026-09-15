"""Suggestion de milieu (Rural / Semi-rural / Urbain) à partir du code postal
belge, via la classification officielle DEGURBA d'Eurostat — pas une
classification inventée : chaque commune belge y est classée ville / bourg-
banlieue / rural sur base de sa densité de population réelle (grille 1km²),
bien plus fiable que le reverse-geocoding (Nominatim) tenté précédemment et
abandonné (confondait des petites communes rurales avec des centres urbains).

data/reference/degurba_belgique.json construit une fois pour toutes en
croisant :
- Eurostat, correspondance LAU-DEGURBA 2025 (ec.europa.eu/eurostat/web/nuts/
  local-administrative-units, fichier EU-27-LAU-2025-NUTS-2024.xlsx, onglet
  BE) — le code LAU d'une commune belge EST son code INS/NIS.
- rubenv/belgium-zipcodes (github.com/rubenv/belgium-zipcodes, out/cities.csv)
  pour la correspondance code postal -> code NIS.

Couverture ~96% des codes postaux (1096/1146) : les ~50 manquants
correspondent à des codes NIS antérieurs aux fusions de communes flamandes
d'environ 2019, absents du fichier Eurostat 2025 — pas mis à jour côté
zipcodes. Un code postal absent renvoie simplement None (aucune suggestion),
jamais une erreur.

Volontairement une SUGGESTION à confirmer par le répondant pendant
l'entretien, jamais un remplissage silencieux de `milieu` — la précédente
tentative (Nominatim) avait justement été abandonnée pour avoir écrit des
valeurs fausses sans supervision.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

_REFERENCE_PATH = Path(__file__).resolve().parent.parent / "data" / "reference" / "degurba_belgique.json"
_CODE_POSTAL_BE_RE = re.compile(r"\b([1-9]\d{3})\b")

_cache: Optional[dict] = None


def _charger_reference() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_REFERENCE_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _cache = {}
    return _cache


def extraire_code_postal_be(adresse: str) -> Optional[str]:
    """Premier nombre à 4 chiffres (1000-9999) trouvé dans le texte — les
    codes postaux belges suivent tous ce format. Renvoie None si aucun
    nombre de cette forme n'apparaît (adresse trop vague, ou pays non
    belge — sans conséquence, l'appelant ne suggère alors simplement rien)."""
    if not adresse:
        return None
    m = _CODE_POSTAL_BE_RE.search(adresse)
    return m.group(1) if m else None


def suggerer_milieu(adresse: str) -> Optional[dict]:
    """{"commune": ..., "milieu_suggere": "Rural"|"Semi-rural"|"Urbain"} si un
    code postal belge connu est trouvé dans `adresse`, sinon None."""
    code_postal = extraire_code_postal_be(adresse)
    if not code_postal:
        return None
    entree = _charger_reference().get(code_postal)
    if not entree or not entree.get("milieu_suggere"):
        return None
    return {"commune": entree["commune"], "milieu_suggere": entree["milieu_suggere"]}
