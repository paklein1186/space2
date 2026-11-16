"""Nettoyage des valeurs avant enregistrement (collecte_tools._canonicaliser_
valeur) : entités HTML décodées, choix recalés sur l'orthographe exacte de
l'option, valeur hors options conservée telle quelle."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import _canonicaliser_valeur
from src.questionnaire.schema import get_field


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    autofin = get_field("autofin")
    check("&gt; décodé et reconnu comme option", _canonicaliser_valeur(autofin, "&gt; 75%") == "> 75%")
    check("&lt; décodé", _canonicaliser_valeur(autofin, "&lt; 25%") == "< 25%")
    check("casse/espaces recalés", _canonicaliser_valeur(autofin, "  25-50%  ") == "25-50%")
    check("hors options conservé", _canonicaliser_valeur(autofin, "environ 60%") == "environ 60%")

    revenus = get_field("revenus")
    check("multi-choix recalé élément par élément",
          _canonicaliser_valeur(revenus, ["mécénat / dons", "Location", "Autre : buvette"])
          == ["Mécénat / dons", "Location", "Autre : buvette"])

    statut = get_field("statut_juridique")  # options par pays (dict)
    check("options par pays prises en compte", _canonicaliser_valeur(statut, "asbl") == "ASBL")

    pitch = get_field("pitch")
    check("texte libre : entités décodées", _canonicaliser_valeur(pitch, "Café &amp; jardin") == "Café & jardin")
    check("champ inconnu (libre::) : décodage seul", _canonicaliser_valeur(None, "a &gt; b") == "a > b")
    check("non-texte inchangé", _canonicaliser_valeur(get_field("surface_batie_m2"), 3000) == 3000)
    check("nouveau champ engagement présent",
          get_field("engagement_capitalisation") is not None
          and _canonicaliser_valeur(get_field("engagement_capitalisation"), "oui") == "Oui")
    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
