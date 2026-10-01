"""ressemble_a_une_url / ajouter_info_lieu_admin (web_crawl.py) : champ admin
sur la fiche d'un lieu qui route un lien vers le crawl, ou enregistre du texte
libre tel quel — note libre systématique, lien_externe posé seulement s'il n'y
en a pas déjà un. Sans réseau (fetch_page_text/extraire_essentiel simulés).

Usage : python3 -m tests.test_ajouter_info_lieu_admin
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import src.agent.web_crawl as web_crawl
from src.agent.web_crawl import ajouter_info_lieu_admin, ressemble_a_une_url
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    # --- détection lien vs texte libre ---
    for url in ("https://commonshub.brussels", "http://example.org/page", "www.exemple.be", "exemple.be/chemin"):
        check(f"ressemble_a_une_url({url!r}) -> True", ressemble_a_una := ressemble_a_une_url(url))
    for texte in ("Bonjour, voici une info sur le lieu.", "Fondé en 2019 par trois associations.",
                  "", "   ", "deux mots sans point"):
        check(f"ressemble_a_une_url({texte!r}) -> False", not ressemble_a_une_url(texte))

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "admin_info.sqlite3"))
        fetch_reel, extraire_reel = web_crawl.fetch_page_text, web_crawl.extraire_essentiel
        try:
            # --- texte libre : enregistré tel quel, aucun fetch ---
            web_crawl.fetch_page_text = lambda url: (_ for _ in ()).throw(AssertionError("ne doit pas être appelé"))
            lieu_texte = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Texte Libre")
            resultat = ajouter_info_lieu_admin(store, lieu_texte.id, lieu_texte.nom, "admin@x.org",
                                               "  Ce lieu a été fondé en 2019 par un collectif local.  ")
            check("texte libre : statut note_directe", resultat == {"statut": "note_directe"})
            notes = store.get_free_text_notes(lieu_texte.id)
            check("texte libre : note enregistrée telle quelle (nettoyée), section note_admin",
                  len(notes) == 1 and notes[0]["section_id"] == "note_admin"
                  and notes[0]["texte"] == "Ce lieu a été fondé en 2019 par un collectif local.")

            # --- lien : crawl + résumé + note + lien_externe posé (aucun connu) ---
            web_crawl.fetch_page_text = lambda url: f"<html>contenu de {url}</html>"
            web_crawl.extraire_essentiel = lambda store, tlid, nom, texte, label, client=None: "Coopérative active depuis 2019."
            lieu_lien = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Avec Nouveau Lien")
            store.save_lieu_derive(LieuDerive(
                tiers_lieu_id=lieu_lien.id, donnees={}, profil_semantique_texte="p",
                prompt_version="v", model="m", source_hash="h"))
            resultat2 = ajouter_info_lieu_admin(store, lieu_lien.id, lieu_lien.nom, "admin@x.org",
                                                "https://commonshub.brussels")
            check("lien : statut lien_analyse, résumé renvoyé",
                  resultat2 == {"statut": "lien_analyse", "resume": "Coopérative active depuis 2019."})
            notes2 = store.get_free_text_notes(lieu_lien.id)
            check("lien : note section crawl_site_lieu (même groupe que analyser_lien/scan admin), url + résumé dedans",
                  len(notes2) == 1 and notes2[0]["section_id"] == "crawl_site_lieu"
                  and "https://commonshub.brussels" in notes2[0]["texte"]
                  and "Coopérative active depuis 2019." in notes2[0]["texte"] and "admin" in notes2[0]["texte"])
            check("lien : lien_externe posé (aucun connu avant)",
                  store.get_lieu_derive(lieu_lien.id).lien_externe == "https://commonshub.brussels")

            # --- lien : un lien_externe existe déjà -> jamais écrasé ---
            lieu_deja = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Avec Lien Existant")
            store.save_lieu_derive(LieuDerive(
                tiers_lieu_id=lieu_deja.id, donnees={}, profil_semantique_texte="p",
                prompt_version="v", model="m", source_hash="h"))
            store.update_lieu_derive_liens(lieu_deja.id, lien_externe="https://deja-la.example", photo_url="p.jpg")
            ajouter_info_lieu_admin(store, lieu_deja.id, lieu_deja.nom, "admin@x.org", "https://nouveau.example")
            check("lien déjà connu : jamais écrasé, note quand même ajoutée",
                  store.get_lieu_derive(lieu_deja.id).lien_externe == "https://deja-la.example"
                  and len(store.get_free_text_notes(lieu_deja.id)) == 1)

            # --- lien : lieu sans lieu_derive -> pas de plantage, lien juste pas mémorisé ---
            lieu_neuf = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Tout Neuf Admin")
            resultat3 = ajouter_info_lieu_admin(store, lieu_neuf.id, lieu_neuf.nom, "admin@x.org", "https://x.example")
            check("lien sur lieu sans synthèse : note ajoutée, pas d'exception", resultat3["statut"] == "lien_analyse")
            check("toujours pas de lieu_derive créé par effet de bord", store.get_lieu_derive(lieu_neuf.id) is None)

            # --- lien : rien d'exploitable ---
            web_crawl.extraire_essentiel = lambda *a, **k: ""
            lieu_vide = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Page Vide Admin")
            resultat4 = ajouter_info_lieu_admin(store, lieu_vide.id, lieu_vide.nom, "admin@x.org", "https://vide.example")
            check("lien sans contenu exploitable : rien_d_utile, aucune note",
                  resultat4 == {"statut": "rien_d_utile"} and store.get_free_text_notes(lieu_vide.id) == [])

            # --- lien : page indisponible ---
            web_crawl.fetch_page_text = lambda url: (_ for _ in ()).throw(RuntimeError("connexion refusée"))
            lieu_down = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Indisponible Admin")
            resultat5 = ajouter_info_lieu_admin(store, lieu_down.id, lieu_down.nom, "admin@x.org", "https://down.example")
            check("page indisponible : erreur renvoyée, pas de plantage, aucune note",
                  resultat5["statut"] == "erreur" and "connexion refusée" in resultat5["erreur"]
                  and store.get_free_text_notes(lieu_down.id) == [])
        finally:
            web_crawl.fetch_page_text, web_crawl.extraire_essentiel = fetch_reel, extraire_reel
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
