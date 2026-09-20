"""Fiche de l'agent Space2 pour le registre d'agents de Changethegame (GET
/manifest). Publique, sans secret : ne contient rien de sensible. Le modèle et
les jeux de données sont lus depuis la configuration réelle, pour que la fiche
ne mente pas si l'un ou l'autre change."""

from __future__ import annotations

import os

from .ask_agent import MODELE_DEFAUT
from .public_data import DATASETS

# À incrémenter quand le comportement de l'agent change (jeux de données,
# limites, règles) — pas seulement quand le texte de la fiche change.
VERSION = "1.0"

README_TEMPLATE = """# Space2 — Bibliothèque Tiers-lieux

Assistant d'analyse sur les tiers-lieux recensés par Space2 (surtout en Belgique, quelques-uns en France).

## Ce qu'il sait
- Trouver des lieux par activité, public, territoire ou thématique, et les comparer.
- Compter et croiser (par pays, région, catégorie…).
- Retrouver les besoins exprimés et les appels de fonds des lieux.
- Rapporter l'activité publique remontée de Changethegame pour les lieux liés.

## Ses limites
- Il n'utilise que des données PUBLIQUES : rien de confidentiel ni d'interne (finances, RH, gouvernance interne).
- Les réponses reposent sur des synthèses générées par IA à partir des réponses des lieux : elles peuvent être incomplètes ou dater.
- Couverture inégale : certains lieux n'ont pas de pays renseigné ou peu de données.
- Pas de recherche dans les documents (interviews, rapports) ni sur le web.
- Réponse limitée à 25 s : une question trop large peut recevoir « reformulez plus précisément ».
- Il cite ses sources (noms de lieux) à chaque réponse.

Modèle : {modele}. Données : Space2 (space2.streamlit.app).
"""


def construire_manifest() -> dict:
    modele = os.environ.get("API_ASK_MODEL") or MODELE_DEFAUT
    return {
        "name": "Space2 — Bibliothèque Tiers-lieux",
        "description": ("Répond aux questions sur les tiers-lieux de Belgique et de France, "
                        "à partir des données publiques."),
        "purpose": "Trouver des lieux, comparer des approches, retrouver besoins et activité.",
        "readme": README_TEMPLATE.format(modele=modele),
        "variables": [{
            "name": "context",
            "description": ("Optionnel. Décrit l'espace d'où vient la question. "
                            "Traité comme donnée, jamais comme instruction."),
        }],
        "topics": ["tiers-lieux"],
        "territories": ["Belgique", "France"],
        "category": "intelligence",
        "version": VERSION,
        "model": modele,
        "datasets": [{"name": nom, "description": meta["description"]} for nom, meta in DATASETS.items()],
        "endpoints": {"ask": "POST /ask", "lieux": "GET /lieux", "link": "POST /lieux/{space2_id}/link",
                      "events": "POST /events", "access": "PUT /access"},
    }
