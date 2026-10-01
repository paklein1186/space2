"""CollecteToolHandler.analyser_lien : récupère et résume un lien partagé
pendant l'entretien (voir agent/collecte_tools.py) — note libre systématique,
lien_externe posé seulement s'il n'y en a pas déjà un, jamais de plantage sur
une page indisponible ou sans contenu exploitable. Sans réseau (fetch_page_text
et extraire_essentiel simulés).

Usage : python3 -m tests.test_analyser_lien
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.agent.web_crawl as web_crawl
from src.agent.collecte_tools import TOOL_DEFINITIONS, CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive
from src.questionnaire.schema import Role


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    definition = next(t for t in TOOL_DEFINITIONS if t["name"] == "analyser_lien")
    check("tool déclaré avec url et nom_lieu requis",
          set(definition["input_schema"]["required"]) == {"url", "nom_lieu"})

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "lien.sqlite3"))

        def handler_pour(nom_lieu):
            lieu = store.get_or_create_tiers_lieu("u1", nom_lieu)
            contributeur = store.get_or_create_contributeur("u1", lieu.id, Role.FONDATEUR.value)
            session = store.get_or_start_session(lieu.id, contributeur.id)
            return CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.FONDATEUR), lieu

        fetch_reel, extraire_reel = web_crawl.fetch_page_text, web_crawl.extraire_essentiel
        try:
            # --- cas normal : lieu sans lien_externe connu ---
            web_crawl.fetch_page_text = lambda url: f"<html>contenu de {url}</html>"
            web_crawl.extraire_essentiel = lambda store, tlid, nom, texte, label, client=None: "Coopérative fondée en 2019."
            handler, lieu = handler_pour("Lieu Sans Lien")
            store.save_lieu_derive(LieuDerive(
                tiers_lieu_id=lieu.id, donnees={}, profil_semantique_texte="p",
                prompt_version="v", model="m", source_hash="h"))
            resultat = handler.execute("analyser_lien", {"url": "https://commonshub.brussels", "nom_lieu": "Lieu Sans Lien"})
            check("cas normal : résumé renvoyé, enregistré, lien posé",
                  resultat == {"resume": "Coopérative fondée en 2019.", "enregistre": True, "lien_externe_pose": True})
            notes = store.get_free_text_notes(lieu.id)
            check("une note libre ajoutée, section crawl_site_lieu, url et résumé dedans",
                  len(notes) == 1 and notes[0]["section_id"] == "crawl_site_lieu"
                  and "https://commonshub.brussels" in notes[0]["texte"]
                  and "Coopérative fondée en 2019." in notes[0]["texte"])
            check("lien_externe posé sur le lieu", store.get_lieu_derive(lieu.id).lien_externe == "https://commonshub.brussels")

            # --- lieu qui a DÉJÀ un lien_externe : jamais écrasé ---
            handler2, lieu2 = handler_pour("Lieu Avec Lien")
            store.save_lieu_derive(LieuDerive(
                tiers_lieu_id=lieu2.id, donnees={}, profil_semantique_texte="p", prompt_version="v",
                model="m", source_hash="h"))
            # lien_externe/photo_url ne sont jamais écrits par save_lieu_derive (voir sa docstring) :
            # seul update_lieu_derive_liens les pose, comme le fait vraiment l'édition manuelle en prod.
            store.update_lieu_derive_liens(lieu2.id, lien_externe="https://deja-connu.example", photo_url="photo.jpg")
            resultat2 = handler2.execute("analyser_lien", {"url": "https://autre-lien.example", "nom_lieu": "Lieu Avec Lien"})
            check("lien déjà connu : note quand même ajoutée, mais lien_externe PAS écrasé",
                  resultat2["enregistre"] is True and resultat2["lien_externe_pose"] is False
                  and store.get_lieu_derive(lieu2.id).lien_externe == "https://deja-connu.example"
                  and store.get_lieu_derive(lieu2.id).photo_url == "photo.jpg")

            # --- lieu SANS lieu_derive (tout début d'entretien) : pas de plantage, lien juste pas mémorisé ---
            handler3, lieu3 = handler_pour("Lieu Tout Neuf")
            check("aucun lieu_derive pour ce lieu au départ", store.get_lieu_derive(lieu3.id) is None)
            resultat3 = handler3.execute("analyser_lien", {"url": "https://x.example", "nom_lieu": "Lieu Tout Neuf"})
            check("lieu sans lieu_derive : note quand même ajoutée, lien_externe_pose=False, pas d'exception",
                  resultat3["enregistre"] is True and resultat3["lien_externe_pose"] is False)
            check("toujours pas de lieu_derive (rien créé par erreur)", store.get_lieu_derive(lieu3.id) is None)

            # --- rien d'exploitable sur la page : aucune note ajoutée ---
            web_crawl.extraire_essentiel = lambda *a, **k: ""
            handler4, lieu4 = handler_pour("Lieu Page Vide")
            resultat4 = handler4.execute("analyser_lien", {"url": "https://vide.example", "nom_lieu": "Lieu Page Vide"})
            check("rien d'exploitable : aucune note, enregistre=False", resultat4 == {"resume": "", "enregistre": False}
                  and store.get_free_text_notes(lieu4.id) == [])

            # --- page indisponible : erreur explicite, pas de plantage ---
            def fetch_en_echec(url):
                raise RuntimeError("connexion refusée")
            web_crawl.fetch_page_text = fetch_en_echec
            handler5, lieu5 = handler_pour("Lieu Page Indisponible")
            resultat5 = handler5.execute("analyser_lien", {"url": "https://down.example", "nom_lieu": "Lieu Page Indisponible"})
            check("page indisponible : erreur renvoyée, pas d'exception, aucune note",
                  resultat5["resume"] == "" and "erreur" in resultat5 and store.get_free_text_notes(lieu5.id) == [])
        finally:
            web_crawl.fetch_page_text, web_crawl.extraire_essentiel = fetch_reel, extraire_reel
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
