"""_chunks / _lire_tout_en_lots / _executer_par_lots (supabase_store.py) :
tout appel .in_(...) filtré par une liste de tiers_lieu_ids est découpé en
lots d'au plus _IN_CHUNK — sans ça, un import en masse (ex. le recensement
national, 4000+ lieux) fait dépasser ce que PostgREST accepte dans l'URL
d'une requête, et plante l'Observatoire (vécu : postgrest.exceptions.
APIError dans get_lieu_derive_batch dès que tiers_lieu_ids a dépassé
quelques centaines d'ids). Sans réseau : un faux client simule l'échec
PostgREST dès qu'un lot dépasse la limite, pour prouver que le découpage
l'évite réellement.

Usage : python3 -m tests.test_supabase_batch_chunking
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.db.supabase_store as supabase_store
from src.db.supabase_store import _chunks, _executer_par_lots, _lire_tout_en_lots


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FakeRequest:
    """Simule juste ce qu'il faut de l'enchaînement fluent Supabase pour
    tester les helpers de lots : .range(a, b).execute() et .execute()
    directement, sur des données déjà filtrées par l'appelant (simule le
    .in_() + .eq() déjà appliqués avant de construire ce FakeRequest)."""

    def __init__(self, data):
        self.data = data

    def range(self, debut, fin):
        return FakeRequest(self.data[debut:fin + 1])

    def execute(self):
        return types.SimpleNamespace(data=self.data)


def main():
    # --- _chunks : découpage simple ---
    check("450 éléments en lots de 200 -> 3 lots (200, 200, 50)",
          [len(c) for c in _chunks(list(range(450)), 200)] == [200, 200, 50])
    check("liste vide -> aucun lot", list(_chunks([], 200)) == [])
    check("liste plus courte que la taille d'un lot -> un seul lot",
          [len(c) for c in _chunks(list(range(5)), 200)] == [5])

    # --- _executer_par_lots : lève si on lui passe tout d'un coup, jamais
    #     si on découpe correctement (simule la vraie limite PostgREST) ---
    LIMITE_SIMULEE = 200
    table = {i: {"tiers_lieu_id": i, "valeur": f"v{i}"} for i in range(450)}

    def fabrique_executer(lot):
        if len(lot) > LIMITE_SIMULEE:
            raise RuntimeError("simulerait un vrai postgrest.exceptions.APIError (URL trop longue)")
        return FakeRequest([table[i] for i in lot])

    ids_450 = list(range(450))
    resultat = _executer_par_lots(ids_450, fabrique_executer)
    check("_executer_par_lots : 450 lignes malgré la limite simulée à 200",
          len(resultat) == 450 and {r["tiers_lieu_id"] for r in resultat} == set(ids_450))
    check("sans découpage, le même appel échouerait (preuve que le test est valide)",
          _raise_sans_decouper(fabrique_executer, ids_450))

    # --- _lire_tout_en_lots : même chose, avec pagination (range) DANS
    #     chaque lot en plus du découpage par ids ---
    reel_page = supabase_store.PAGE
    supabase_store.PAGE = 3  # pagine vite pour un test rapide
    try:
        def fabrique_lire_tout(lot):
            if len(lot) > LIMITE_SIMULEE:
                raise RuntimeError("simulerait un vrai postgrest.exceptions.APIError (URL trop longue)")
            return FakeRequest([table[i] for i in lot])

        resultat2 = _lire_tout_en_lots(ids_450, fabrique_lire_tout)
        check("_lire_tout_en_lots : 450 lignes malgré limite ids ET pagination par lot de 3",
              len(resultat2) == 450 and {r["tiers_lieu_id"] for r in resultat2} == set(ids_450))
    finally:
        supabase_store.PAGE = reel_page

    # --- liste vide : aucun appel, résultat vide (pas d'exception) ---
    check("_executer_par_lots sur liste vide -> []", _executer_par_lots([], fabrique_executer) == [])

    print("Tous les tests passent.")


def _raise_sans_decouper(fabrique, ids) -> bool:
    try:
        fabrique(ids)
    except RuntimeError:
        return True
    return False


if __name__ == "__main__":
    main()
