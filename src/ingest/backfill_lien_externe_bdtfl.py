"""Pose lien_externe (lieu_derive) depuis la colonne INTERNET du fichier
BDTFL « fiche identité », pour les lieux importés par ce recensement qui
n'en ont pas encore.

Pourquoi : import_bdtfl.py capture le site web dans la note de contact (texte
libre), jamais comme lien_externe structuré — le seul champ que regarde le
crawl admin (« Recherche web : sites des lieux », bouton « Scanner les sites
référencés », voir extraire_et_enregistrer dans web_crawl.py). Sans ce
rattrapage, ce crawl ne trouve aucun des lieux importés depuis ce fichier.

À lancer APRÈS avoir régénéré les synthèses (admin, bouton « Régénérer les
synthèses ») : update_lieu_derive_liens ne crée jamais la ligne lieu_derive,
seulement un lieu déjà enrichi (donc déjà doté d'une ligne) peut recevoir son
lien_externe ici.

Usage :
    python -m src.ingest.backfill_lien_externe_bdtfl chemin/vers/bdftl-2026-01-fiche-identite.csv
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dotenv import load_dotenv

from src.db.factory import get_admin_store
from src.ingest.import_bdtfl import nettoyer_nom

PAUSE_S = 0.2


def _normaliser(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = f"https://{url}"
    return url


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest.backfill_lien_externe_bdtfl chemin/vers/bdftl-2026-01-fiche-identite.csv")
        return
    chemin = Path(sys.argv[1])
    store = get_admin_store()

    with chemin.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f, delimiter=";"))

    lieux_par_nom = {l.nom.strip().lower(): l for l in store.list_tiers_lieux()}
    poses = deja = sans_derive = inconnu = sans_site = 0
    for row in rows:
        nom = nettoyer_nom(row.get("NOM"))
        url = (row.get("INTERNET") or "").strip()
        if not nom or not url:
            sans_site += 1
            continue
        lieu = lieux_par_nom.get(nom.lower())
        if lieu is None:
            inconnu += 1
            continue
        derive = store.get_lieu_derive(lieu.id)
        if derive is None:
            sans_derive += 1
            continue
        if derive.lien_externe:
            deja += 1
            continue
        store.update_lieu_derive_liens(lieu.id, lien_externe=_normaliser(url), photo_url=derive.photo_url)
        poses += 1
        time.sleep(PAUSE_S)
        if poses % 200 == 0:
            print(f"... {poses} lien(s) posé(s)")

    print(f"\n{poses} lien(s) posé(s), {deja} déjà connus, {sans_derive} lieu(x) pas encore enrichi(s) "
          f"(relancer après enrichissement), {inconnu} lieu(x) introuvable(s), {sans_site} ligne(s) sans site.")


if __name__ == "__main__":
    main()
