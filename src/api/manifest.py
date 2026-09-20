"""Fiche de l'agent Space2 pour le registre d'agents de Changethegame (GET
/manifest). Publique, sans secret : ne contient rien de sensible (uniquement
des noms et descriptions de colonnes). Le modèle, le mode d'accès et les jeux
de données reflètent la configuration réelle ; un test vérifie que les colonnes
décrites ici sont bien celles des jeux de données servis."""

from __future__ import annotations

import os

from .ask_agent import MODELE_DEFAUT

# À incrémenter quand le comportement de l'agent change (jeux de données,
# limites, règles) — pas seulement quand le texte de la fiche change.
VERSION = "1.1"

_LIEU = {
    "tiers_lieu": "Nom du lieu",
    "pays": "Pays",
    "region": "Région",
    "latitude": "Latitude (degrés décimaux ; vide si inconnue)",
    "longitude": "Longitude (degrés décimaux ; vide si inconnue)",
}
_SYNTHESE = {
    "resume": "Synthèse du lieu en 1-2 phrases",
    "activites": "Activités et services proposés",
    "publics": "Publics accueillis",
    "territoire": "Ancrage territorial (localisation, milieu, mobilité)",
    "besoins": "Besoins et difficultés exprimés",
    "partenaires": "Partenariats territoriaux",
    "competences": "Compétences et savoir-faire distinctifs",
    "projets": "Projets en cours ou à venir",
    "enjeux": "Enjeux et défis principaux",
    "mots_cles": "Mots-clés (liste)",
    "categories": "Catégories du lieu : Alimentaire, Culturel, Éducation, Santé (liste)",
}
_EVENEMENTS = {
    "tiers_lieu": "Nom du lieu concerné",
    "type": "membre, discussion, mise_a_jour, quete ou besoin",
    "titre": "Titre de l'événement",
    "texte": "Contenu de l'événement",
    "url": "Lien vers l'événement dans Changethegame",
    "survenu_le": "Date de l'événement (ISO 8601)",
}

# nom -> (description du jeu, {colonne: description})
DATASETS_COMPLET = {
    "lieux_enrichis": (
        "Un lieu par ligne : localisation (latitude/longitude) et synthèses générées (activités, publics, "
        "gouvernance, ressources, modèle économique…). Filtrer par mots-clés, catégories ou proximité "
        "(opération `near`).",
        {**_LIEU, **_SYNTHESE,
         "gouvernance": "Mode de gouvernance et participation des usagers",
         "ressources": "Ressources humaines et matérielles",
         "modele_economique": "Modèle économique et sources de financement"},
    ),
    "reponses_tiers_lieux": (
        "Réponses détaillées au questionnaire, format long : une ligne par (lieu, contributeur, champ). "
        "Filtrer la colonne `champ` avec `contains` pour retrouver un sujet.",
        {"tiers_lieu": "Nom du lieu", "pays": "Pays", "region": "Région",
         "contributeur_id": "Identifiant anonyme du contributeur",
         "champ": "Intitulé de la question", "champ_id": "Identifiant technique de la question",
         "valeur": "Réponse (texte, nombre ou liste)"},
    ),
    "bonnes_pratiques": (
        "Retours d'expérience concrets (montages financiers, partenariats, gouvernance…) recueillis en entretien.",
        {"tiers_lieu": "Nom du lieu", "pays": "Pays", "region": "Région", "texte": "Retour d'expérience"},
    ),
    "activite_ctg": (
        "Activité publique remontée de Changethegame pour les lieux qui y sont liés.", _EVENEMENTS),
}

DATASETS_PUBLICS = {
    "lieux": (
        "Un lieu par ligne : localisation et synthèse publique (générée uniquement à partir des réponses publiques).",
        {**_LIEU, "ctg_entity_id": "Identifiant de l'entité liée dans Changethegame", **_SYNTHESE,
         "besoins_mis_en_avant": "Besoins mis en avant par le lieu (liste)",
         "lien_externe": "Lien externe du lieu", "photo_url": "Photo du lieu"},
    ),
    "reponses_publiques": (
        "Réponses non confidentielles à des questions publiques, format long : une ligne par (lieu, champ).",
        {"tiers_lieu": "Nom du lieu", "pays": "Pays", "region": "Région",
         "champ": "Intitulé de la question", "champ_id": "Identifiant technique de la question",
         "valeur": "Réponse (texte, nombre ou liste)"},
    ),
    "activite_ctg": DATASETS_COMPLET["activite_ctg"],
}

README_COMPLET = """# Space2 — Bibliothèque Tiers-lieux

Assistant d'analyse sur les tiers-lieux recensés par Space2 (surtout en Belgique, quelques-uns en France). \
Il a accès aux données complètes de Space2 — mêmes données et même capacité que l'assistant du site — à \
l'exception de ce que les répondants ont explicitement marqué confidentiel.

## Ce qu'il sait
- Trouver des lieux par activité, public, territoire, thématique ou proximité géographique (« lieux à moins de \
20 km de Blanmont »), et les comparer.
- Compter et croiser (par pays, région, catégorie…).
- Retrouver les réponses détaillées au questionnaire (modèle économique, gouvernance, ressources, besoins…).
- Retrouver des lieux par recherche sémantique sur leur profil, et des retours d'expérience concrets.
- Rapporter l'activité publique remontée de Changethegame pour les lieux liés.

## Ses limites
- Les réponses explicitement marquées confidentielles et celles des contributeurs bloqués sont exclues ; pour \
un lieu ayant de telles réponses, seule sa synthèse publique est utilisée.
- Les synthèses sont générées par IA à partir des réponses des lieux : elles peuvent être incomplètes ou dater.
- Couverture inégale : certains lieux n'ont pas de pays, de coordonnées ou peu de données.
- Pas de recherche dans les interviews ou rapports déposés, ni sur le web.
- Réponse limitée à 25 s : une question trop large peut recevoir « reformulez plus précisément ».
- Il cite ses sources (noms de lieux) à chaque réponse.

Modèle : {modele}. Données : Space2 (space2.streamlit.app).
"""

README_PUBLIC = """# Space2 — Bibliothèque Tiers-lieux

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


def construire_manifest(acces_complet: bool = True) -> dict:
    modele = os.environ.get("API_ASK_MODEL") or MODELE_DEFAUT
    datasets = DATASETS_COMPLET if acces_complet else DATASETS_PUBLICS
    return {
        "name": "Space2 — Bibliothèque Tiers-lieux",
        "description": ("Répond aux questions sur les tiers-lieux de Belgique et de France à partir des données "
                        "de Space2" + (" (hors ce qui est marqué confidentiel)." if acces_complet
                                       else ", données publiques uniquement.")),
        "purpose": "Trouver des lieux, comparer des approches, retrouver besoins et activité.",
        "readme": (README_COMPLET if acces_complet else README_PUBLIC).format(modele=modele),
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
        "access": "full_without_confidential" if acces_complet else "public_only",
        "datasets": [
            {"name": nom, "description": description,
             "columns": [{"name": c, "description": d} for c, d in colonnes.items()]}
            for nom, (description, colonnes) in datasets.items()
        ],
        "endpoints": {"ask": "POST /ask", "lieux": "GET /lieux", "link": "POST /lieux/{space2_id}/link",
                      "events": "POST /events", "access": "PUT /access"},
    }
