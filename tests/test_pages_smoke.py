"""Vérifie que les pages publiques Observatoire et Portfolio s'exécutent sans
exception via streamlit.testing.v1.AppTest, à la fois à vide et avec un lieu
enrichi (pour couvrir les chemins de code peuplés : graphiques, campagne).

Comme test_app_smoke.py, s'appuie sur le SqliteStore par défaut
(data/local_dev.sqlite3, hors SUPABASE_URL) plutôt que sur une base isolée —
get_store()/get_admin_store() n'exposent pas de chemin configurable.

Usage : python3 -m tests.test_pages_smoke
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["SUPABASE_SERVICE_KEY"] = ""

from streamlit.testing.v1 import AppTest

from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive
from src.questionnaire.schema import Role

PAGES = ["src/pages/1_Observatoire.py", "src/pages/2_Portfolio.py"]


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    db_path = "data/local_dev.sqlite3"
    Path(db_path).unlink(missing_ok=True)

    for page in PAGES:
        at = AppTest.from_file(page, default_timeout=30)
        at.run()
        check(f"{page} : pas d'exception (base vide)", not at.exception)

    # Base peuplée : un lieu enrichi, catégorisé, inclus au Portfolio avec une
    # campagne — couvre les graphiques et le rendu de la campagne.
    store = SqliteStore(db_path=db_path)
    lieu = store.get_or_create_tiers_lieu("user-1", "Lieu Smoke")
    store.update_tiers_lieu(lieu.id, pays="Belgique", region="Namur")
    contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.FONDATEUR.value)
    store.save_answer(lieu.id, contributeur.id, "milieu", "Rural")
    store.save_lieu_derive(LieuDerive(
        tiers_lieu_id=lieu.id,
        donnees={
            "resume": "Un lieu de test.", "categories": ["Alimentaire", "Culturel"],
            "enjeux": "Enjeu de test.", "besoins": "Besoin de test.",
            "mots_cles": ["test", "smoke"],
        },
        profil_semantique_texte="profil de test",
        prompt_version="test", model="test", source_hash="hash-test",
    ))
    store.update_portfolio_entry(lieu.id, True, "Campagne de test", "Objectif de test", "contact@test.org")

    for page in PAGES:
        at = AppTest.from_file(page, default_timeout=30)
        at.run()
        check(f"{page} : pas d'exception (base peuplée)", not at.exception)

    Path(db_path).unlink(missing_ok=True)
    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
