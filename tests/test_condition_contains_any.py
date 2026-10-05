"""Condition "contains_any" (schema.py) : actif si le champ multi_choice
répondu intersecte au moins une des valeurs attendues — utilisé par le champ
"fundraising" de la campagne KA122 (actif si eco_coince contient "Accès au
financement" OU "Investissement / foncier"). Sans réseau, sans base.

Usage : python3 -m tests.test_condition_contains_any
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.questionnaire.schema import Condition


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    cond = Condition("eco_coince", "contains_any", ["Accès au financement", "Investissement / foncier"])

    check("une seule valeur attendue présente -> actif",
          cond.evaluate({"eco_coince": ["Trésorerie", "Accès au financement"]}))
    check("l'autre valeur attendue, seule -> actif",
          cond.evaluate({"eco_coince": ["Investissement / foncier"]}))
    check("aucune valeur attendue -> inactif",
          not cond.evaluate({"eco_coince": ["Trésorerie", "Coûts RH"]}))
    check("champ non répondu -> inactif", not cond.evaluate({}))
    check("champ répondu mais vide -> inactif", not cond.evaluate({"eco_coince": []}))
    check("valeur qui n'est pas une liste -> inactif, ne lève pas",
          not cond.evaluate({"eco_coince": "Trésorerie"}))
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
