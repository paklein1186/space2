"""import_bdtfl_themes.py : les modules thématiques du recensement BDTFL 2026
(hors fiche identité) exportent un bloc "en-tête de groupe" (texte lisible,
sélections multiples déjà jointes par ';') suivi de dizaines de colonnes
individuelles par case à cocher (valeurs 0/1 uniquement, redondantes) — ce
module ne garde que les colonnes dont les valeurs ne sont jamais QUE 0/1, en
note libre par thème. Sans réseau.

Usage : python3 -m tests.test_import_bdtfl_themes
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.import_bdtfl_themes import colonnes_significatives, import_fichier, note_theme, theme_pour_fichier
from src.db.sqlite_store import SqliteStore
from src.questionnaire.schema import Role

# Même forme que le vrai fichier foncier : un en-tête de groupe (texte
# lisible) suivi de ses cases individuelles (0/1 redondantes).
HEADER = [
    "ID_UNIQUE", "NOM", "Mail", "statut_lieu", "en activité", "en projet (pas encore ouvert)",
    "statut_foncier", "Propriétaire du bâtiment (seul ou en collectif)", "Locataire du bâtiment au prix du marché",
    "duree_bail", "Moins d'1 an", "Entre 1 et 3 ans",
]
LIGNE_TYPE = {
    "ID_UNIQUE": "42", "NOM": "FabLab Test", "Mail": "contact@fablabtest.fr",
    "statut_lieu": "en activité", "en activité": "1", "en projet (pas encore ouvert)": "0",
    "statut_foncier": "Propriétaire du bâtiment (seul ou en collectif)",
    "Propriétaire du bâtiment (seul ou en collectif)": "1", "Locataire du bâtiment au prix du marché": "0",
    "duree_bail": "Entre 1 et 3 ans", "Moins d'1 an": "0", "Entre 1 et 3 ans": "1",
}


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    # --- détection fichier -> thème ---
    check("fichier reconnu -> section_id + titre",
          theme_pour_fichier(Path("bdftl-2026-03-foncier.csv")) == ("import_bdtfl_foncier", "Foncier (BDTFL)"))
    check("fichier inconnu -> None", theme_pour_fichier(Path("autre-chose.csv")) is None)

    # --- colonnes_significatives : ne garde jamais une colonne 0/1-only ---
    rows = [LIGNE_TYPE, dict(LIGNE_TYPE, **{
        "NOM": "Autre Lieu", "statut_foncier": "Locataire du bâtiment au prix du marché",
        "Propriétaire du bâtiment (seul ou en collectif)": "0", "Locataire du bâtiment au prix du marché": "1",
        "duree_bail": "Moins d'1 an", "Moins d'1 an": "1", "Entre 1 et 3 ans": "0",
    })]
    colonnes = colonnes_significatives(rows, HEADER)
    check("en-têtes de groupe conservées", {"statut_lieu", "statut_foncier", "duree_bail", "Mail"} <= set(colonnes))
    check("cases individuelles (0/1 only) exclues",
          "Propriétaire du bâtiment (seul ou en collectif)" not in colonnes
          and "Locataire du bâtiment au prix du marché" not in colonnes
          and "Moins d'1 an" not in colonnes and "Entre 1 et 3 ans" not in colonnes
          and "en activité" not in colonnes and "en projet (pas encore ouvert)" not in colonnes)
    check("colonnes d'identité (ID_UNIQUE, NOM) jamais reprises dans la note",
          "ID_UNIQUE" not in colonnes and "NOM" not in colonnes)

    # --- note_theme : texte lisible, une ligne par colonne significative ---
    note = note_theme(LIGNE_TYPE, colonnes)
    check("note contient l'en-tête de groupe avec sa valeur lisible",
          "statut_foncier : Propriétaire du bâtiment (seul ou en collectif)" in note)
    check("note contient duree_bail", "duree_bail : Entre 1 et 3 ans" in note)
    check("note ne contient aucune des cases individuelles 0/1",
          "Propriétaire du bâtiment (seul ou en collectif) : " not in note)

    # --- import_fichier bout en bout (SQLite local) ---
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "theme.sqlite3"))
        chemin_csv = Path(tmp) / "bdftl-2026-03-foncier.csv"
        import csv as csv_mod
        with chemin_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=HEADER, delimiter=";")
            writer.writeheader()
            writer.writerows(rows)

        traites = import_fichier(store, "import-bdtfl-2026", chemin_csv)
        check("2 lieux traités", traites == 2)

        lieu = store.get_or_create_tiers_lieu("import-bdtfl-2026", "FabLab Test")
        notes = store.get_free_text_notes(lieu.id)
        check("une note ajoutée, section_id = import_bdtfl_foncier",
              len(notes) == 1 and notes[0]["section_id"] == "import_bdtfl_foncier")
        check("titre du thème en tête de note, puis le détail", notes[0]["texte"].startswith("Foncier (BDTFL) :\n"))

        # --- idempotence du dédoublonnage par nom : un lieu déjà recensé
        #     (ex. créé par import_bdtfl.py, la fiche identité) est enrichi,
        #     jamais dupliqué ---
        lieu_existant = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Deja Recense")
        ligne_existant = dict(LIGNE_TYPE, NOM="Lieu Deja Recense")
        chemin_csv2 = Path(tmp) / "bdftl-2026-03-foncier-2.csv"
        with chemin_csv2.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=HEADER, delimiter=";")
            writer.writeheader()
            writer.writerow(ligne_existant)
        import_fichier(store, "import-bdtfl-2026", chemin_csv2)
        check("aucun doublon de lieu créé pour un nom déjà recensé",
              store.get_or_create_tiers_lieu("admin@x.org", "Lieu Deja Recense").id == lieu_existant.id)

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
