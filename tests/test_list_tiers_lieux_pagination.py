"""SupabaseStore.list_tiers_lieux / list_candidats_lieux : ne doivent jamais
tronquer silencieusement à 1000 lignes — bug vécu en production après
l'import du recensement national BDTFL (3960 lieux réels, list_tiers_lieux()
n'en renvoyait que 1000 partout : Annuaire, Observatoire, flux ctg, sans la
moindre erreur pour le signaler). Un faux client Supabase simule le
comportement PostgREST réel (tronque à 1000 lignes par page si on ne pagine
pas avec .range()), pour prouver que les deux méthodes paginent bien.

Usage : python3 -m tests.test_list_tiers_lieux_pagination
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.supabase_store import SupabaseStore

PAGE_POSTGREST = 1000  # comportement réel de PostgREST sans .range() explicite


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FakeQuery:
    def __init__(self, data):
        self.data = data
        self._range = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.data = [r for r in self.data if r.get(col) == val]
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


def _lieu(i: int) -> dict:
    return {
        "id": f"id{i:05d}", "owner_user_id": "import-bdtfl-2026", "nom": f"Lieu {i}",
        "pays": "France", "region": None, "latitude": None, "longitude": None,
        "statut_progression": "en_cours", "ctg_entity_id": None, "commune": None, "code_postal": None,
    }


def _candidat(i: int) -> dict:
    return {
        "id": f"cand{i:05d}", "nom": f"Candidat {i}", "description": "d", "source_label": "s",
        "commune": None, "pays": None, "citation": None, "statut": "propose",
        "tiers_lieu_id": None, "cree_le": "2026-01-01T00:00:00Z", "traite_le": None, "traite_par": None,
    }


def main():
    lieux_bruts = [_lieu(i) for i in range(3960)]
    candidats_bruts = [_candidat(i) for i in range(1500)]
    client = FakeClient({"tiers_lieux": lieux_bruts, "candidats_lieux": candidats_bruts})
    store = SupabaseStore(url="https://fake.supabase.co", key="fake-key", client=client)

    lieux = store.list_tiers_lieux()
    check("list_tiers_lieux : les 3960 lieux, pas seulement les 1000 premiers (bug vécu)",
          len(lieux) == 3960)
    check("aucun doublon, tous les ids présents",
          {l.id for l in lieux} == {r["id"] for r in lieux_bruts})

    lieux_filtres = store.list_tiers_lieux(owner_user_id="import-bdtfl-2026")
    check("list_tiers_lieux(owner_user_id=...) : filtre toujours appliqué après pagination",
          len(lieux_filtres) == 3960 and all(l.id.startswith("id") for l in lieux_filtres))

    candidats = store.list_candidats_lieux()
    check("list_candidats_lieux : les 1500 candidats, pas seulement 1000", len(candidats) == 1500)

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
