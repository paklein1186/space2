"""Vérifie qu'un lieu existant est bien retrouvé (pas dupliqué) quand un
nouveau contributeur retape son nom — même avec une casse ou des espaces
différents, et même si ce n'est pas le même owner_user_id que le créateur
original. Bug réel observé en prod : un lieu "Chez Bibi" retapé "Chez bibi"
par un autre utilisateur créait un doublon vide au lieu de rejoindre le
lieu déjà enrichi."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.sqlite_store import SqliteStore


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "test.sqlite3"))

        original = store.get_or_create_tiers_lieu("import-drive", "Chez Bibi")
        rejoint_meme_casse = store.get_or_create_tiers_lieu("autre-user", "Chez Bibi")
        rejoint_casse_differente = store.get_or_create_tiers_lieu("encore-un-autre", "Chez bibi")
        rejoint_espaces = store.get_or_create_tiers_lieu("un-quatrieme", "  Chez Bibi  ")

        check("Même casse, autre owner -> même lieu", rejoint_meme_casse.id == original.id)
        check("Casse différente -> même lieu", rejoint_casse_differente.id == original.id)
        check("Espaces superflus -> même lieu", rejoint_espaces.id == original.id)
        check("Un seul lieu créé au total",
              len(store.list_tiers_lieux()) == 1)

        autre_lieu = store.get_or_create_tiers_lieu("import-drive", "Un Autre Lieu")
        check("Un nom réellement différent crée bien un nouveau lieu", autre_lieu.id != original.id)
        check("Deux lieux au total désormais", len(store.list_tiers_lieux()) == 2)

        print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
