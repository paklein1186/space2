"""SupabaseStore.get_reponses_pour_champs : ne doit jamais tronquer
silencieusement à 1000 lignes — bug vécu en production (tableau admin "Voir
les répondants" d'une campagne prioritaire) : avec l'import BDTFL, la table
`reponses` dépasse largement 1000 lignes pour les champs d'une campagne
(KA122 : 26 champs), et un répondant ayant pourtant bien répondu (ex. "Bigre
test") n'apparaissait pas, ou apparaissait avec des champs manquants, selon
l'ordre renvoyé par défaut par PostgREST sans .range(). Un faux client
simule cette troncature réelle, pour prouver que la pagination l'évite.

Usage : python3 -m tests.test_reponses_pour_champs_pagination
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.supabase_store import SupabaseStore

PAGE_POSTGREST = 1000


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self._range = None

    def select(self, *a, **k):
        return self

    def in_(self, col, valeurs):
        valeurs = set(valeurs)
        self.data = [r for r in self.data if r.get(col) in valeurs]
        return self

    def order(self, *a, **k):
        return self

    def range(self, debut, fin):
        self._range = (debut, fin)
        return self

    def execute(self):
        rows = self.data
        if self._range:
            debut, fin = self._range
            rows = rows[debut:fin + 1]
        else:
            # Simule PostgREST : silencieusement tronqué à PAGE_POSTGREST
            # lignes quand l'appelant ne pagine pas explicitement avec .range().
            rows = rows[:PAGE_POSTGREST]
        return types.SimpleNamespace(data=rows)


class FakeTable:
    def __init__(self, data):
        self.data = data

    def select(self, *a, **k):
        return FakeQuery(self.data)


class FakeClient:
    def __init__(self, tables: dict):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.get(name, []))


def _reponse(i: int, tiers_lieu_id: str, champ_id: str, valeur) -> dict:
    return {
        "id": f"rep{i:05d}", "tiers_lieu_id": tiers_lieu_id,
        "contributeur_id": "contrib-1", "champ_id": champ_id, "valeur": valeur,
    }


def main():
    champ_ids = ["pitch", "resilience", "pays"]
    # Beaucoup de "bruit" sur d'autres champs (import massif, hors campagne)
    # pour dépasser PAGE_POSTGREST avant même d'atteindre les réponses du
    # répondant ciblé, comme en production après l'import BDTFL.
    bruit = [_reponse(i, f"lieu{i:05d}", "autre_champ", "x") for i in range(1200)]
    reponses_bigre = [
        _reponse(9000, "bigre-test", "pitch", "Un pitch complet."),
        _reponse(9001, "bigre-test", "resilience", "Très résilient."),
        _reponse(9002, "bigre-test", "pays", "France"),
    ]
    toutes = bruit + reponses_bigre
    client = FakeClient({"reponses": toutes})
    store = SupabaseStore(url="https://fake.supabase.co", key="fake-key", client=client)

    lignes = store.get_reponses_pour_champs(champ_ids)
    check("liste vide de champs -> liste vide, pas de requête",
          store.get_reponses_pour_champs([]) == [])
    lignes_bigre = [l for l in lignes if l["tiers_lieu_id"] == "bigre-test"]
    check("les 3 réponses de 'bigre-test' sont bien présentes malgré le bruit (bug vécu)",
          len(lignes_bigre) == 3)
    check("les champs couverts sont exactement ceux de la campagne",
          {l["champ_id"] for l in lignes_bigre} == set(champ_ids))

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
