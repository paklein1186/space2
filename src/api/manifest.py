"""Fiche de l'agent Space2 pour le registre d'agents de Changethegame (GET
/manifest). Publique, sans secret : ne contient rien de sensible (uniquement
des noms et descriptions de colonnes). Le modèle, le mode d'accès et les jeux
de données reflètent la configuration réelle ; un test vérifie que les colonnes
décrites ici sont bien celles des jeux de données servis."""

from __future__ import annotations

import os

from .ask_agent import BUDGET_SECONDES, modele_configure

# À incrémenter quand le comportement de l'agent change (jeux de données,
# limites, règles) — pas seulement quand le texte de la fiche change.
VERSION = "1.4"

_LIEU = {
    "tiers_lieu": "Nom du lieu",
    "pays": "Pays",
    "region": "Région",
    "commune": "Commune (issue du géocodage de l'adresse ; vide si inconnue)",
    "code_postal": "Code postal (issu du géocodage de l'adresse ; vide si inconnu)",
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

_ORGANISATIONS = {
    "ctg_id": "Identifiant Changethegame (guild:/quest:/company:/post: + uuid)",
    "kind": "organisation, quete, entite, post (ou lieu non créé comme lieu)",
    "nom": "Nom de l'objet",
    "description": "Description",
    "url": "Lien vers l'objet dans Changethegame",
    "website_url": "Site web externe",
    "topics": "Thèmes (liste)",
    "territories": "Territoires (liste)",
    "commune": "Commune (si connue)",
    "latitude": "Latitude (si connue)",
    "longitude": "Longitude (si connue)",
    "parent_ctg_id": "Identifiant de l'objet parent",
    "parent_nom": "Nom de l'objet parent (si connu)",
    "status": "Statut côté Changethegame",
    "updated_at": "Dernière mise à jour côté Changethegame (ISO 8601)",
}
_DESC_ORGANISATIONS = ("Objets de Changethegame qui ne sont pas des lieux : organisations, entités, quêtes et "
                       "posts (colonne `kind`). Absents de la galerie et du Portfolio.")

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
    "organisations_ctg": (_DESC_ORGANISATIONS, _ORGANISATIONS),
    "activite_ctg": (
        "Activité publique remontée de Changethegame pour les lieux qui y sont liés.", _EVENEMENTS),
}

DATASETS_PUBLICS = {
    "lieux": (
        "Un lieu par ligne : localisation et synthèse publique (générée uniquement à partir des réponses publiques).",
        {**_LIEU, "adresse": "Adresse ou commune telle que saisie par le lieu (texte libre)",
         "ctg_entity_id": "Identifiant de l'entité liée dans Changethegame", **_SYNTHESE,
         "besoins_mis_en_avant": "Besoins mis en avant par le lieu (liste)",
         "lien_externe": "Lien externe du lieu", "photo_url": "Photo du lieu"},
    ),
    "reponses_publiques": (
        "Réponses non confidentielles à des questions publiques, format long : une ligne par (lieu, champ).",
        {"tiers_lieu": "Nom du lieu", "pays": "Pays", "region": "Région",
         "champ": "Intitulé de la question", "champ_id": "Identifiant technique de la question",
         "valeur": "Réponse (texte, nombre ou liste)"},
    ),
    "organisations_ctg": (_DESC_ORGANISATIONS, _ORGANISATIONS),
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
- Retrouver un passage précis dans les interviews et rapports déposés, ainsi que dans les résumés de datasets et de géodonnées.
- Rapporter l'activité publique remontée de Changethegame pour les lieux liés.
- Retrouver les organisations, entités, quêtes et posts de Changethegame (par thème, territoire ou sens).

## Ses limites
- Les réponses explicitement marquées confidentielles et celles des contributeurs bloqués sont exclues ; pour \
un lieu ayant de telles réponses, seule sa synthèse publique est utilisée.
- Les synthèses sont générées par IA à partir des réponses des lieux : elles peuvent être incomplètes ou dater.
- Couverture inégale : certains lieux n'ont pas de pays, de coordonnées ou peu de données.
- Pas de recherche sur le web ; les connaissances ajoutées depuis la Bibliothèque de Space2 ne sont pas consultées.
- Réponse limitée à {budget} s : au-delà, la réponse en cours est rendue interrompue.
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
- Retrouver les organisations, entités, quêtes et posts de Changethegame.

## Ses limites
- Il n'utilise que des données PUBLIQUES : rien de confidentiel ni d'interne (finances, RH, gouvernance interne).
- Les réponses reposent sur des synthèses générées par IA à partir des réponses des lieux : elles peuvent être incomplètes ou dater.
- Couverture inégale : certains lieux n'ont pas de pays renseigné ou peu de données.
- Pas de recherche dans les documents (interviews, rapports) ni sur le web.
- Réponse limitée à {budget} s : au-delà, la réponse en cours est rendue interrompue.
- Il cite ses sources (noms de lieux) à chaque réponse.

Modèle : {modele}. Données : Space2 (space2.streamlit.app).
"""


def construire_manifest(acces_complet: bool = True) -> dict:
    modele = modele_configure()
    datasets = DATASETS_COMPLET if acces_complet else DATASETS_PUBLICS
    return {
        "name": "Space2 — Bibliothèque Tiers-lieux",
        "description": ("Répond aux questions sur les tiers-lieux de Belgique et de France à partir des données "
                        "de Space2" + (" (hors ce qui est marqué confidentiel)." if acces_complet
                                       else ", données publiques uniquement.")),
        "purpose": "Trouver des lieux, comparer des approches, retrouver besoins et activité.",
        "readme": (README_COMPLET if acces_complet else README_PUBLIC).format(modele=modele, budget=int(BUDGET_SECONDES)),
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
        "response_modes": {"json": "POST /ask -> {content}",
                           "sse": "POST /ask avec Accept: text/event-stream -> lignes `data: {type: start|delta|status|done|error}`"},
        "limits": {"budget_seconds": BUDGET_SECONDES},
        "datasets": [
            {"name": nom, "description": description,
             "columns": [{"name": c, "description": d} for c, d in colonnes.items()]}
            for nom, (description, colonnes) in datasets.items()
        ],
        "endpoints": {"ask": "POST /ask", "lieux": "GET /lieux", "link": "POST /lieux/{space2_id}/link",
                      "events": "POST /events", "objects": "PUT /ctg/objects", "access": "PUT /access"},
    }
