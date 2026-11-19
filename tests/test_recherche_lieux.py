"""Recherche texte de l'annuaire (src/recherche_lieux.py), sans réseau :
accents et casse ignorés, commune / région / pays / code postal cherchés,
fautes de frappe tolérées, exacts avant approximatifs, temps de réponse
correct sur ~4000 lieux.

Usage : python3 -m tests.test_recherche_lieux
"""

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.recherche_lieux import lieu_au_nom_exact, normaliser, rechercher_lieux


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


@dataclass
class L:
    nom: str
    commune: Optional[str] = None
    region: Optional[str] = None
    pays: Optional[str] = None
    code_postal: Optional[str] = None


def noms(resultat):
    return [l.nom for l in resultat[0]]


def main():
    lieux = [
        L("Feÿ", "Feÿ", "Grand Est", "France", "57420"),
        L("Le Phare", "Andenne", "Namur", "Belgique", "5300"),
        L("Fab Lab Sud31-Val d'Ariège", "Toulouse", "Occitanie", "France"),
        L("Commons Hub", "Bruxelles - Brussel", "Bruxelles-Capitale", "Belgique"),
        L("La Halle", "Huy", "Liège", "Belgique"),
        L("Domaine des Possibles", "Chastre", "Brabant wallon", "Belgique"),
        L("Cœur de village", "Œuilly", "Hauts-de-France", "France"),
    ]
    check("normalisation : accents, tréma, ligature, ponctuation",
          normaliser("  Feÿ — L'Œuf  Ariège ") == "fey l oeuf ariege")
    check("« fey » trouve « Feÿ »", noms(rechercher_lieux(lieux, "fey")) == ["Feÿ"])
    check("« FEŸ » trouve « Feÿ »", noms(rechercher_lieux(lieux, "FEŸ")) == ["Feÿ"])
    check("ville : « andenne » trouve Le Phare", noms(rechercher_lieux(lieux, "andenne")) == ["Le Phare"])
    check("région sans accent : « liege » trouve La Halle (pas le Fab Lab d'Ariège)",
          noms(rechercher_lieux(lieux, "liege")) == ["La Halle"])
    check("pays : « belgique » trouve les 4 lieux belges", len(rechercher_lieux(lieux, "belgique")[0]) == 4)
    check("code postal", noms(rechercher_lieux(lieux, "5300")) == ["Le Phare"])
    check("plusieurs mots : tous requis", noms(rechercher_lieux(lieux, "phare namur")) == ["Le Phare"])
    check("faute de frappe : « bruxeles » trouve Commons Hub", noms(rechercher_lieux(lieux, "bruxeles")) == ["Commons Hub"])
    check("faute de frappe : « posibles » trouve le Domaine", noms(rechercher_lieux(lieux, "posibles")) == ["Domaine des Possibles"])
    check("début de mot avec faute : « chastr » / « chsatre »",
          noms(rechercher_lieux(lieux, "chastr")) == noms(rechercher_lieux(lieux, "chsatre")) == ["Domaine des Possibles"])
    check("ligature : « coeur » trouve Cœur de village", noms(rechercher_lieux(lieux, "coeur")) == ["Cœur de village"])
    check("mots courts : pas d'approximation (« hux » ne trouve pas Huy)", rechercher_lieux(lieux, "hux") == ([], True))
    check("rien de proche : aucun résultat", rechercher_lieux(lieux, "zanzibar") == ([], True))
    check("recherche vide : tous les lieux", rechercher_lieux(lieux, "  ") == (lieux, False))

    deux = [L("Bruxeles Lab"), L("Commons Hub", "Bruxelles")]
    check("résultat exact : les approchants sont écartés",
          rechercher_lieux(deux, "bruxelles") == ([deux[1]], False))
    check("faute de frappe signalée comme approximative", rechercher_lieux(lieux, "bruxeles")[1] is True)

    check("nom exact, accents ignorés : ouvre la fiche", lieu_au_nom_exact(lieux, "fey").nom == "Feÿ")
    check("nom partiel : pas d'ouverture directe", lieu_au_nom_exact(lieux, "phare") is None)
    check("homonymes : pas d'ouverture directe", lieu_au_nom_exact([L("La Gare"), L("La Gare")], "la gare") is None)

    gros = [L(f"Tiers-lieu numéro {i}", f"Commune {i % 900}", f"Région {i % 20}", "France") for i in range(4000)]
    debut = time.monotonic()
    for q in ("bruxeles", "communne 12", "tiers lieu"):
        rechercher_lieux(gros, q)
    duree = (time.monotonic() - debut) / 3
    check(f"~4000 lieux : {duree:.2f}s par recherche (< 1s)", duree < 1)
    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
