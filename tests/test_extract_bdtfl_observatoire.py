"""extract_bdtfl_observatoire.py : agrégation (répartitions multi-choix,
totaux numériques avec virgule décimale française, proportions VRAI/FAUX)
depuis le fichier intégral du recensement BDTFL — sans écriture réelle,
juste la logique de calcul. Sans réseau.

Usage : python3 -m tests.test_extract_bdtfl_observatoire
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.extract_bdtfl_observatoire import chiffre, proportion_booleenne, repartition


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    lignes = [
        {"famille": "Coworking;Fablab", "etp": "2,5", "compagnon": "VRAI"},
        {"famille": "Coworking", "etp": "0", "compagnon": "FAUX"},
        {"famille": "", "etp": "1", "compagnon": "VRAI"},
        {"famille": "Fablab;Écolieu", "etp": "", "compagnon": ""},
    ]

    r = repartition(lignes, "famille")
    check("répartition : ne compte que les réponses non vides (3 sur 4)", r["repondants"] == 3)
    check("répartition : choix multiples éclatés, comptés indépendamment",
          {v["label"]: v["n"] for v in r["valeurs"]} == {"Coworking": 2, "Fablab": 2, "Écolieu": 1})
    check("répartition : pourcentage calculé sur le nombre de répondants, pas le total de lignes",
          next(v["pct"] for v in r["valeurs"] if v["label"] == "Coworking") == round(100 * 2 / 3, 1))

    check("répartition : colonne absente de toutes les lignes -> 0 répondant, pas une erreur",
          repartition(lignes, "colonne_absente")["repondants"] == 0)

    c = chiffre(lignes, "etp")
    check("chiffre : virgule française convertie (2,5 -> 2.5), chaîne vide ignorée",
          c == {"total": 4, "base": 3})  # 2.5 + 0 + 1 = 3.5 -> round 4, base = 3 valeurs numériques

    b = proportion_booleenne(lignes, "compagnon")
    check("proportion booléenne : VRAI/FAUX reconnus insensibles à la casse, vide ignoré",
          b == {"pct": round(100 * 2 / 3, 1), "base": 3})

    check("proportion booléenne : colonne sans VRAI/FAUX -> pct None, pas une division par zéro",
          proportion_booleenne(lignes, "colonne_absente") == {"pct": None, "base": 0})

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
