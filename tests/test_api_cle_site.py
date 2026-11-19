"""Clé de lecture du site Trois-Tiers (SITE_READ_SECRET) : elle ouvre GET /lieux et rien d'autre.
Sans réseau ni base : le flux est remplacé par une liste fixe.

Usage : python3 -m tests.test_api_cle_site
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.api import app as api_app

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


def main():
    api_app.get_store = lambda: None
    api_app.flux_lieux = lambda store, since=None: [{"space2_id": "L1", "tiers_lieu": "Lieu test"}]
    http = TestClient(api_app.app)
    ctg, site = {"X-Webhook-Secret": "secret-ctg"}, {"X-Webhook-Secret": "cle-site"}

    os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"
    os.environ.pop("SITE_READ_SECRET", None)
    check("sans clé du site configurée : la clé du site est refusée", http.get("/lieux", headers=site).status_code == 401)
    check("la clé de ctg lit toujours /lieux", http.get("/lieux", headers=ctg).status_code == 200)

    os.environ["SITE_READ_SECRET"] = "cle-site"
    r = http.get("/lieux", headers=site)
    check("la clé du site lit /lieux", r.status_code == 200 and r.json()["lieux"][0]["tiers_lieu"] == "Lieu test")
    check("sans en-tête → 401", http.get("/lieux").status_code == 401)
    check("mauvaise clé → 401", http.get("/lieux", headers={"X-Webhook-Secret": "autre"}).status_code == 401)
    check("clé vide → 401", http.get("/lieux", headers={"X-Webhook-Secret": ""}).status_code == 401)

    # La clé du site n'ouvre rien d'autre.
    check("clé du site refusée sur PUT /access", http.put("/access", json={}, headers=site).status_code == 401)
    check("clé du site refusée sur POST /events", http.post("/events", json={}, headers=site).status_code == 401)
    check("clé du site refusée sur POST /lieux/L1/link",
          http.post("/lieux/L1/link", json={"ctg_entity_id": "E1"}, headers=site).status_code == 401)
    check("clé du site refusée sur PUT /ctg/objects", http.put("/ctg/objects", json={}, headers=site).status_code == 401)
    # POST /ask accepte la clé du site, avec son propre agent : voir tests/test_api_ask_site.py.
    check("clé du site refusée sur /diagnostic", http.get("/diagnostic", headers=site).status_code == 401)

    os.environ["CTG_WEBHOOK_SECRET"] = ""
    check("secret de ctg vide : la chaîne vide n'ouvre rien", http.get("/lieux", headers={"X-Webhook-Secret": ""}).status_code == 401)
    os.environ.pop("CTG_WEBHOOK_SECRET", None)
    os.environ.pop("SITE_READ_SECRET", None)

    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
