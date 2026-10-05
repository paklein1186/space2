"""import_bdtfl.py : mapping direct des colonnes du fichier « fiche identité »
du recensement national BDTFL 2026 vers le schéma Space2 — pays toujours
France, latitude/longitude en virgule décimale française, note libre pour
les contacts/réseaux sociaux/structure gestionnaire. Sans réseau.

Usage : python3 -m tests.test_import_bdtfl
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingest.import_bdtfl import _coordonnee, import_row, nettoyer_nom
from src.db.sqlite_store import SqliteStore
from src.questionnaire.schema import Role

LIGNE_TYPE = {
    "NOM": "Au café couture", "ADRESSE": "7 Rue Alsace Lorraine 76000 Rouen",
    "CODPOST": "76000", "VILLE": "Rouen", "DEPARTEMENT_TL": "Seine-Maritime",
    "REGION_TL": "Normandie", "LATITUDE": "49,438538", "LONGITUDE": "1,099506",
    "INTERNET": "", "EMAIL": "contact@aucafecouturerouen.fr", "TELEPHONE": "+33950694412",
    "DESCRI_COU": "", "DATE_OUV": "", "NOM_STRC_GEST": " ", "TYPE_STRUCTURE_GEST": "Association",
    "RS_FACEBOOK": "", "RS_X": "", "RS_INSTAGRAM": "", "RS_LINKEDIN": "", "RS_MASTODON": "",
    "RS_MOVILAB": "", "LIEN_OSM_GOOGLE": "",
}


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    # --- virgule décimale française ---
    check("coordonnée '49,438538' -> 49.438538", _coordonnee("49,438538") == 49.438538)
    check("coordonnée vide -> None", _coordonnee("") is None)
    check("coordonnée illisible -> None, ne lève pas", _coordonnee("abc") is None)

    # --- nettoyage des guillemets encadrant tout le nom ---
    check("guillemets doubles encadrant tout le nom retirés", nettoyer_nom('"Le 97"') == "Le 97")
    check("apostrophe en fin de nom (pas un guillemet encadrant) conservée",
          nettoyer_nom("Le Bivouak'") == "Le Bivouak'")
    check("guillemet n'encadrant qu'un morceau du nom conservé",
          nettoyer_nom("'La Place des Ami.e.s' Plazenn ar Vignoned ") == "'La Place des Ami.e.s' Plazenn ar Vignoned")
    check("double encadrement (apostrophes doublées) réduit en un seul passage",
          nettoyer_nom("''Les Hauts Parleurs''") == "Les Hauts Parleurs")
    check("nom vide ou None -> chaîne vide", nettoyer_nom("") == "" and nettoyer_nom(None) == "")
    check("nom sans guillemets inchangé", nettoyer_nom("Le Moulin Vieux") == "Le Moulin Vieux")

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "bdtfl.sqlite3"))

        # --- import d'une ligne complète ---
        lieu_id = import_row(store, "import-bdtfl-2026", dict(LIGNE_TYPE))
        lieu = store.get_or_create_tiers_lieu("import-bdtfl-2026", "Au café couture")
        check("lieu créé avec le bon id", lieu.id == lieu_id)
        check("pays posé à France", lieu.pays == "France")
        check("région, commune, code postal posés depuis le fichier",
              lieu.region == "Normandie" and lieu.commune == "Rouen" and lieu.code_postal == "76000")
        check("latitude/longitude posées (virgule convertie en point)",
              lieu.latitude == 49.438538 and lieu.longitude == 1.099506)

        contributeur = store.get_or_create_contributeur("import-bdtfl-2026", lieu.id, Role.AUTRE.value)
        reponses = store.get_answers(lieu.id, contributeur.id)
        check("réponse adresse enregistrée telle quelle (déjà complète dans le fichier)",
              reponses.get("adresse") == "7 Rue Alsace Lorraine 76000 Rouen")
        check("réponse nom_lieu enregistrée", reponses.get("nom_lieu") == "Au café couture")

        notes = store.get_free_text_notes(lieu.id)
        check("note complémentaire enregistrée (contacts + structure), section import_bdtfl",
              len(notes) == 1 and notes[0]["section_id"] == "import_bdtfl"
              and "contact@aucafecouturerouen.fr" in notes[0]["texte"]
              and "Association" in notes[0]["texte"])

        # --- ligne sans latitude/longitude : pas de plantage, lat/lon absentes ---
        ligne_sans_geo = dict(LIGNE_TYPE, NOM="Lieu Sans Geo", LATITUDE="", LONGITUDE="")
        import_row(store, "import-bdtfl-2026", ligne_sans_geo)
        lieu2 = store.get_or_create_tiers_lieu("import-bdtfl-2026", "Lieu Sans Geo")
        check("sans latitude/longitude dans le fichier : lieu créé quand même, sans coordonnées",
              lieu2.latitude is None and lieu2.longitude is None and lieu2.commune == "Rouen")

        # --- un lieu déjà recensé n'est jamais écrasé sur ses champs TiersLieu ---
        lieu_existant = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Deja La")
        store.update_tiers_lieu(lieu_existant.id, pays="Belgique", region="Namur", commune="Gembloux")
        ligne_doublon = dict(LIGNE_TYPE, NOM="Lieu Deja La", VILLE="Paris", REGION_TL="Île-de-France")
        import_row(store, "import-bdtfl-2026", ligne_doublon)
        relu = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Deja La")
        check("lieu déjà recensé (même nom) : pays/région/commune existants jamais écrasés",
              relu.pays == "Belgique" and relu.region == "Namur" and relu.commune == "Gembloux")

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
