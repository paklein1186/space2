"""Vérifie get_lieu_derive_batch (SqliteStore) : une requête batch renvoie
exactement les mêmes données qu'un get_lieu_derive par lieu, y compris pour
un lieu sans synthèse (absent du dict plutôt qu'une erreur).

Usage : python3 -m tests.test_lieu_derive_batch
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "batch.sqlite3"))

        lieu_avec_synthese = store.get_or_create_tiers_lieu("u1", "Lieu Avec Synthèse")
        lieu_sans_synthese = store.get_or_create_tiers_lieu("u1", "Lieu Sans Synthèse")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu_avec_synthese.id,
            donnees={"resume": "Un résumé.", "categories": ["Culturel"]},
            profil_semantique_texte="profil", prompt_version="v1", model="m", source_hash="h1",
        ))

        batch = store.get_lieu_derive_batch([lieu_avec_synthese.id, lieu_sans_synthese.id])
        check("2 clés dans le batch ? non — seul le lieu avec synthèse est présent",
              set(batch.keys()) == {lieu_avec_synthese.id})
        check("Le contenu batch correspond à get_lieu_derive individuel",
              batch[lieu_avec_synthese.id].donnees == store.get_lieu_derive(lieu_avec_synthese.id).donnees)
        check("Un lieu sans synthèse est absent du batch (pas une entrée None)",
              lieu_sans_synthese.id not in batch)

        vide = store.get_lieu_derive_batch([])
        check("Une liste vide renvoie un dict vide sans erreur", vide == {})

        print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
