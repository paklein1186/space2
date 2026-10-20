"""Récupère les visuels (logo/photo) depuis l'API communecter.org — même
source et même format ("ftl") que le fichier BDTFL « fiche identité » déjà
importé (import_bdtfl.py), mais avec un champ LOGO que ce fichier CSV ne
contenait pas : jamais capturé jusqu'ici, donc aucun lieu importé depuis
BDTFL n'a de photo_url posé automatiquement.

Pagination : l'API plafonne à 500 entités par page quel que soit le `limit`
demandé dans l'URL (vérifié : .../limit/4000 renvoie quand même meta.limit
= 500) — on suit meta.next (paramètre index) jusqu'à page vide.

Comme backfill_lien_externe_bdtfl.py : update_lieu_derive_liens ne crée
jamais la ligne lieu_derive (seul un lieu déjà enrichi peut recevoir sa
photo), et on ne touche jamais un photo_url déjà renseigné — considéré
édition manuelle dans tout le reste du code (voir le commentaire sur
save_lieu_derive), donc jamais écrasé par un import automatique.

Usage :
    python -m src.ingest.sync_photos_communecter
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import requests
from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.ingest.import_bdtfl import nettoyer_nom

BASE_URL = "https://www.communecter.org/api/organization/get/key/franceTierslieux/format/ftl"
PAGE_SIZE = 500
PAUSE_S = 0.2
TIMEOUT_S = 30


def _recuperer_toutes_les_entites() -> list:
    entites = []
    index = 0
    while True:
        url = f"{BASE_URL}/limit/{PAGE_SIZE}/index/{index}"
        reponse = requests.get(url, timeout=TIMEOUT_S)
        reponse.raise_for_status()
        page = reponse.json().get("entities") or {}
        if not page:
            break
        entites.extend(page.values())
        print(f"... page index={index} : {len(page)} entité(s)")
        if len(page) < PAGE_SIZE:
            break
        index += PAGE_SIZE
    return entites


def main():
    load_dotenv()
    store = get_admin_store()

    print("Récupération de l'annuaire communecter.org (paginé)...")
    entites = _recuperer_toutes_les_entites()
    print(f"{len(entites)} entité(s) récupérée(s) au total.\n")

    lieux_par_nom = {nettoyer_nom(l.nom).lower(): l for l in store.list_tiers_lieux()}

    poses = deja = sans_derive = inconnu = sans_logo = 0
    for entite in entites:
        logo = (entite.get("LOGO") or "").strip()
        if not logo:
            sans_logo += 1
            continue
        nom = nettoyer_nom(entite.get("NOM"))
        lieu = lieux_par_nom.get(nom.lower())
        if lieu is None:
            inconnu += 1
            continue
        derive = store.get_lieu_derive(lieu.id)
        if derive is None:
            sans_derive += 1
            continue
        if derive.photo_url:
            deja += 1
            continue
        store.update_lieu_derive_liens(lieu.id, lien_externe=derive.lien_externe, photo_url=logo)
        poses += 1
        time.sleep(PAUSE_S)
        if poses % 100 == 0:
            print(f"... {poses} photo(s) posée(s)")

    print(f"\n{poses} photo(s) posée(s), {deja} lieu(x) avaient déjà une photo (non touchés), "
          f"{sans_derive} lieu(x) pas encore enrichi(s) (pas de ligne lieu_derive), "
          f"{inconnu} entité(s) communecter sans lieu correspondant dans Space2, "
          f"{sans_logo} entité(s) sans logo.")


if __name__ == "__main__":
    main()
