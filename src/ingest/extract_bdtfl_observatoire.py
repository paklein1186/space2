"""Extrait, depuis le fichier intégral du recensement BDTFL 2026 (modules
thématiques fusionnés, un lieu par ligne), des répartitions agrégées pour de
nouvelles sections de l'Observatoire — jamais de donnée nominative, que des
comptages/pourcentages.

Pourquoi un instantané figé plutôt qu'un calcul en direct depuis la base
Space2 : ces données thématiques (foncier, réseaux, partenariats, emplois...)
n'ont jamais été importées comme réponses structurées dans Space2 — seulement
en notes libres (voir import_bdtfl_themes.py), pour ne rien perdre d'un
export à ~900 colonnes qu'un mapping 1:1 vers le schéma Space2 aurait été
disproportionné de refaire. Les 998 répondants de ce fichier sont un
échantillon représentatif (comparable en taille aux 1035 répondants du
panorama national France Tiers-Lieux), mais figé à la date du recensement —
pas une donnée qui évolue avec les entretiens Space2, d'où un fichier à part
plutôt qu'un recalcul à chaque chargement de page.

Usage :
    python3 -m src.ingest.extract_bdtfl_observatoire chemin/vers/bdtfl-2026-integrale.csv
Écrit src/data/bdtfl_observatoire_2026.json (commité, lu par l'Observatoire).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# (colonne CSV, clé de sortie, libellé affiché)
REPARTITIONS = [
    ("statut_lieu", "statut_lieu", "Statut du lieu"),
    ("initiative_origine", "initiative_origine", "Qui est à l'initiative de la création"),
    ("familles_tiers_lieux", "familles_tiers_lieux", "Familles de tiers-lieux"),
    ("activites_principales", "activites_principales", "Activités principales"),
    ("types_equipements", "types_equipements", "Équipements proposés"),
    ("publics_types", "publics_types", "Publics accueillis"),
    ("statut_foncier", "statut_foncier", "Situation foncière"),
    ("type_proprietaire", "type_proprietaire", "Type de propriétaire (en location)"),
    ("duree_bail", "duree_bail", "Durée du bail"),
    ("reseaux_regionaux", "reseaux_regionaux", "Réseaux régionaux"),
    ("reseaux_thematiques_nationaux", "reseaux_nationaux", "Réseaux thématiques nationaux"),
    ("partenariats_collectivites", "partenariats_collectivites", "Partenariats avec des collectivités"),
    ("projets_developpement_futur", "perspectives", "Perspectives de développement"),
    ("risques_12_mois", "risques", "Principaux risques identifiés (12 prochains mois)"),
    ("besoins_accompagnement", "besoins_accompagnement", "Besoins d'accompagnement"),
]

# (colonne CSV, clé de sortie, libellé, unité)
CHIFFRES = [
    ("etp_salaries", "etp_salaries", "ETP salariés", ""),
    ("etp_benevoles", "etp_benevoles", "ETP bénévoles", ""),
    ("nb_adherents_2025", "adherents", "Adhérents en 2025", ""),
    ("nb_benevoles_tres_actifs", "benevoles_tres_actifs", "Bénévoles très actifs", ""),
    ("nb_benevoles_actifs", "benevoles_actifs", "Bénévoles actifs", ""),
    ("nb_benevoles_ponctuels", "benevoles_ponctuels", "Bénévoles ponctuels", ""),
]

# (colonne CSV, clé de sortie, libellé) — proportion d'un booléen VRAI/FAUX
BOOLEENS = [
    ("tiers_lieu_compagnon", "volontaires_compagnonnage", "Volontaires pour compagnonner d'autres lieux"),
    ("heberge_service_public", "heberge_service_public", "Hébergent directement un service public"),
    ("agrement_qualiopi", "labellises_qualiopi", "Labellisés Qualiopi"),
]


def _nombre(valeur: str) -> float | None:
    valeur = (valeur or "").strip().replace(",", ".")
    if not valeur:
        return None
    try:
        return float(valeur)
    except ValueError:
        return None


def repartition(rows: list, colonne: str, top_n: int = 14) -> dict:
    compte = Counter()
    repondants = 0
    for row in rows:
        valeur = (row.get(colonne) or "").strip()
        if not valeur:
            continue
        repondants += 1
        for item in valeur.split(";"):
            item = item.strip()
            if item:
                compte[item] += 1
    return {
        "repondants": repondants,
        "valeurs": [
            {"label": label, "n": n, "pct": round(100 * n / repondants, 1)}
            for label, n in compte.most_common(top_n)
        ],
    }


def chiffre(rows: list, colonne: str) -> dict:
    valeurs = [_nombre(r.get(colonne)) for r in rows]
    valeurs = [v for v in valeurs if v is not None]
    return {"total": round(sum(valeurs)), "base": len(valeurs)}


def proportion_booleenne(rows: list, colonne: str) -> dict:
    valeurs = [(r.get(colonne) or "").strip().upper() for r in rows]
    valeurs = [v for v in valeurs if v in ("VRAI", "FAUX")]
    vrai = sum(1 for v in valeurs if v == "VRAI")
    return {"pct": round(100 * vrai / len(valeurs), 1) if valeurs else None, "base": len(valeurs)}


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.ingest.extract_bdtfl_observatoire chemin/vers/bdtfl-2026-integrale.csv")
        return
    chemin = Path(sys.argv[1])
    with chemin.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    sortie = {
        "source": "Recensement national des tiers-lieux 2026 (France Tiers-Lieux, data.gouv.fr)",
        "echantillon": len(rows),
        "date_extraction": date.today().isoformat(),
        "repartitions": {
            cle: {"titre": titre, **repartition(rows, colonne)}
            for colonne, cle, titre in REPARTITIONS
        },
        "chiffres": {
            cle: {"titre": titre, "unite": unite, **chiffre(rows, colonne)}
            for colonne, cle, titre, unite in CHIFFRES
        },
        "booleens": {
            cle: {"titre": titre, **proportion_booleenne(rows, colonne)}
            for colonne, cle, titre in BOOLEENS
        },
    }

    chemin_sortie = Path(__file__).resolve().parent.parent / "data" / "bdtfl_observatoire_2026.json"
    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    chemin_sortie.write_text(json.dumps(sortie, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Écrit : {chemin_sortie} ({len(rows)} lignes source)")


if __name__ == "__main__":
    main()
