"""Import des réponses du formulaire "AutoDiag" (Google Forms, Trois-Tiers,
décembre 2024 à juin 2025) — diagnostic des besoins d'accompagnement des
tiers-lieux wallons. Ces réponses sont ANTÉRIEURES au questionnaire de
capitalisation (plus récent, importé via import_questionnaire.py) : jamais
utilisées pour écraser une réponse structurée déjà connue, uniquement pour
compléter ce qui manque encore — même logique que import_csv_directory.py.

Deux groupes de colonnes correspondent directement à des champs du schéma
(stade_developpement, types_soutien_souhaites/priorites_principales) —
mappés tels quels via _OPTIONS_BESOIN ci-dessous. Toutes les questions
ouvertes (raison d'être, gouvernance vécue, modèle économique...) sont
conservées en une note libre consolidée par lieu plutôt que forcées dans des
champs qui ne correspondent pas.

Usage :
    python -m src.ingest.import_autodiag_csv chemin/vers/export.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.questionnaire.schema import Role

OWNER_ID_LOCAL = "import-autodiag-tierslieux"

# get_or_create_tiers_lieu ne dédoublonne qu'à la casse/aux espaces près
# (recherche exacte insensible à la casse) — plusieurs noms de ce CSV
# diffèrent trop du nom déjà enregistré (suffixe, préfixe, renommage entre
# fin 2024 et l'import capitalisation plus récent) pour être retrouvés tels
# quels, et créeraient sinon un doublon vide au lieu de rejoindre le lieu
# déjà documenté. Vérifié un par un contre la liste réelle des lieux avant
# cet import (voir la conversation) — pas une supposition.
_ALIAS_NOM = {
    "Centre Créatif Aldringen": "Pfarrhaus Aldringen – Presbytère d'Aldringen",
    "e-Square": "L'e-Square",
    "Gare de Jurbise": "Renouveau de la Gare de Jurbise",
    "L'Esperluette - Tiers-lieu de Léglise": "L'Esperluette",
    "Le Jardin des Aubépines ( nouveau nom 2025)": "Le Jardin des Aubépines",
    "Le Monty tiers-lieu": "Le Monty",
    "Service Tiers-Lieu de Saint-Hubert": "Tiers-lieu Saint-Hubert",
    'Tiers-Lieu "La Gare"': "La Gare",
    "Tiers Lieux de Vaux-sur-Sûre": "Tiers-Lieu de Vaux-sur-Sûre",
    "La Briktrie sc": "Briktrie",
}

# Colonne (index, 0-based) -> libellé exact de l'option types_soutien_souhaites
# (voir section_diagnostic_besoins_futurs dans schema.py, dont les options ont
# été complétées avec ce même formulaire pour permettre ce mapping direct).
_OPTIONS_BESOIN = {
    42: "Plan financier et pérennisation",
    43: "Gouvernance / gestion de collectif",
    44: "Médiation de conflits",
    45: "Repenser l'organisationnel et les processus de décision",
    46: "Communication",
    47: "Activation de communauté d'usagers",
    48: "Ancrage territorial / partenariats",
    49: "Événementiel (conception ou production d'événements)",
    50: "Aide sur systèmes énergétiques/hydriques",
    51: "Centre logistique ou compostage",
    52: "Rénovation / obstacles architecturaux",
    53: "Innovation low-tech, éco-construction ou économie circulaire",
    54: "Aide juridique",
    55: "Gestion de projet",
    56: "Structure d'accueil de bénévoles",
    57: "Développement entrepreneurial / rapport à l'argent des usagers",
    58: "Lancement de services de proximité",
    59: "Usages d'outils numériques",
    60: "Gestion financière, administrative et comptabilité",
    61: "Montée en compétence de l'équipe",
    62: "Ressources pratiques et inspirations (modèles, fieldtrips...)",
    63: "Mise en réseau avec d'autres tiers-lieux",
    64: "Activités agricoles ou alimentaires",
    65: "Comment implémenter des services publics",
}

# Questions ouvertes (colonne -> intitulé abrégé) conservées en note libre
# plutôt que forcées dans un champ structuré — chaque paire (intitulé,
# réponse) devient une entrée de la note consolidée du lieu.
_QUESTIONS_OUVERTES = {
    8: "Fonctions : Espace de vie sociale et communautaire",
    9: "Fonctions : Création, artisanat et fabrication",
    10: "Fonctions : Transmission",
    11: "Fonctions : Culture et Arts",
    12: "Fonctions : Santé et soins",
    13: "Fonctions : Alimentation et circularité",
    14: "Fonctions : Service et infrastructures partagés",
    15: "Fonctions : Autres",
    17: "1.1 Raison d'être du projet, besoins du territoire",
    19: "1.2 Fondateurs, porteurs et motivations",
    21: "1.3 Vision à 5 ans",
    23: "2.1 Structure décisionnelle actuelle",
    25: "2.2 Parties prenantes et niveau d'engagement",
    27: "2.3 Communication interne",
    69: "2.4 Communication externe",
    29: "3.1 Acteurs et ressources locales identifiés",
    31: "3.2 Analyse AFOM / SWOT",
    33: "4.1 Sources de revenus actuelles ou prévues",
    35: "4.2 Besoins financiers court/moyen/long terme",
    36: "4.3 Financement des espaces et équipements collectifs",
    37: "5.1 Besoins spatiaux",
    39: "6.1 Système d'évaluation du projet",
    40: "6.2 Temps réguliers d'ajustement organisation/vision",
    41: "6.3 Formations ou accompagnements utiles à l'équipe",
    67: "Demande spécifique complémentaire",
    70: "Lauréat de l'appel à projet Région wallonne (23 lauréats)",
}


def _service_owner_id(store) -> str:
    from src.db.supabase_store import SupabaseStore

    if isinstance(store, SupabaseStore):
        from src.db.migrate_sqlite_to_supabase import get_or_create_service_user

        return get_or_create_service_user(store.client, OWNER_ID_LOCAL)
    return OWNER_ID_LOCAL


# Une des options du formulaire contient elle-même une virgule ("Tiers-lieu
# abouti, solide et renforcé"), ce qui la ferait couper en deux par un simple
# split(",") sur l'export Google Forms (qui sépare les sélections par ", ") —
# protégée par substitution avant découpage, restaurée après.
_STADE_ABOUTI = "Tiers-lieu abouti, solide et renforcé"
_STADE_ABOUTI_PROTEGE = "Tiers-lieu abouti\x00 solide et renforcé"


def _stade_developpement(cell: str) -> list:
    cell = cell.replace(_STADE_ABOUTI, _STADE_ABOUTI_PROTEGE)
    valeurs = [v.strip().replace("\x00", ",") for v in cell.split(",")]
    return [v for v in valeurs if v]


def _besoins_et_priorites(row: list) -> tuple:
    besoins, priorites = [], []
    for col, label in _OPTIONS_BESOIN.items():
        valeur = row[col].strip() if col < len(row) else ""
        if not valeur:
            continue
        besoins.append(label)
        if "Prioritaire" in valeur:
            priorites.append(label)
    return besoins, priorites


def _note_consolidee(row: list) -> str:
    lignes = []
    for col, label in _QUESTIONS_OUVERTES.items():
        valeur = row[col].strip() if col < len(row) else ""
        if valeur:
            lignes.append(f"{label}\n→ {valeur}")
    return "\n\n".join(lignes)


def import_row(store, owner_user_id: str, row: list) -> str:
    nom = row[2].strip()
    nom = _ALIAS_NOM.get(nom, nom)
    tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, nom)
    contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, Role.AUTRE.value)
    deja_repondu = store.get_answers(tiers_lieu.id, contributeur.id)

    def _save_si_absent(champ_id: str, valeur) -> None:
        if valeur not in (None, "", []) and deja_repondu.get(champ_id) is None:
            store.save_answer(tiers_lieu.id, contributeur.id, champ_id, valeur)

    annee = row[3].strip()
    if annee and annee.isdigit():
        _save_si_absent("date_ouverture", annee)

    stade = _stade_developpement(row[16])
    _save_si_absent("stade_developpement", stade)

    besoins, priorites = _besoins_et_priorites(row)
    _save_si_absent("types_soutien_souhaites", besoins)
    if priorites:
        _save_si_absent("priorites_principales", ", ".join(priorites))

    note = _note_consolidee(row)
    if note:
        store.save_free_text_note(
            tiers_lieu.id, contributeur.id, "import_autodiag",
            "Réponses au formulaire AutoDiag (Trois-Tiers, fin 2024) :\n\n" + note,
        )

    return tiers_lieu.id


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest.import_autodiag_csv chemin/vers/export.csv")
        return
    chemin = Path(sys.argv[1])
    store = get_admin_store()
    owner_user_id = _service_owner_id(store)

    with chemin.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))

    traites = 0
    for row in rows[1:]:
        if len(row) < 3 or not row[2].strip():
            continue
        import_row(store, owner_user_id, row)
        traites += 1

    print(f"{traites} lieu(x) traité(s) depuis {chemin.name}.")


if __name__ == "__main__":
    main()
