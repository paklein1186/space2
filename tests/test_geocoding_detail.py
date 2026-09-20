"""Commune / code postal issus de Nominatim, exposés dans /lieux : extraction,
géocodage détaillé (réseau simulé), enregistrement non bloquant à la réponse
« adresse » et présence dans le flux. Sans réseau.

Usage : python3 -m tests.test_geocoding_detail
"""

import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src import geocoding
from src.api import app as api_app
from src.db.sqlite_store import SqliteStore


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def faux_get(payload):
    def _get(url, params=None, headers=None, timeout=None):
        _get.appels.append((url, params))
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    _get.appels = []
    return _get


def main():
    # --- extraction ---
    be = {"address": {"municipality": "Gembloux", "village": "Grand-Leez", "postcode": "5030;5031", "country": "Belgique",
                  "country_code": "be"}}
    check("Belgique : municipality > village, premier code postal",
          geocoding.extraire_commune_cp(be) == {"commune": "Gembloux", "code_postal": "5030"})
    fr = {"address": {"town": "Guerchy", "postcode": "89113", "country_code": "fr"}}
    check("France : town + code postal", geocoding.extraire_commune_cp(fr) == {"commune": "Guerchy", "code_postal": "89113"})
    villecien = {"address": {"village": "Villecien", "municipality": "Sens", "county": "Yonne",
                             "postcode": "89300", "country_code": "fr"}}
    check("France : Villecien (village) et non Sens (municipality = arrondissement)",
          geocoding.extraire_commune_cp(villecien) == {"commune": "Villecien", "code_postal": "89300"})
    check("France : municipality seule en dernier recours",
          geocoding.extraire_commune_cp({"address": {"municipality": "Sens", "country_code": "fr"}})["commune"] == "Sens")
    check("adresse absente → None", geocoding.extraire_commune_cp({}) == {"commune": None, "code_postal": None})

    gesves = {"address": {"village": "Faulx-Les Tombes", "country_code": "be"}}
    check("Belgique : section seule + adresse = simple nom → le nom saisi (Gesves)",
          geocoding.extraire_commune_cp(gesves, "Gesves")["commune"] == "Gesves")
    check("Belgique : adresse détaillée (chiffres/virgule) → on garde Nominatim",
          geocoding.extraire_commune_cp(gesves, "Rue X 12, 5340, Gesves")["commune"] == "Faulx-Les Tombes")
    check("Belgique : municipality trouvée → prioritaire sur l'adresse saisie",
          geocoding.extraire_commune_cp(be, "Grand-Leez")["commune"] == "Gembloux")
    check("France : l'adresse saisie n'écrase jamais Nominatim",
          geocoding.extraire_commune_cp(villecien_fr := {"address": {"village": "Villecien", "municipality": "Sens",
                                        "country_code": "fr"}}, "Sens")["commune"] == "Villecien")

    # --- géocodage détaillé ---
    reel = geocoding.requests.get
    try:
        geocoding.requests.get = faux_get([{"lat": "50.56", "lon": "4.69", **be}])
        d = geocoding.geocoder_adresse_detail("Gembloux (près de X)", "Belgique")
        check("détail : coordonnées + commune + cp",
              d == {"latitude": 50.56, "longitude": 4.69, "commune": "Gembloux", "code_postal": "5030"})
        params = geocoding.requests.get.appels[0][1]
        check("addressdetails demandé, parenthèses retirées de la requête",
              params["addressdetails"] == 1 and "(" not in params["q"])
        check("geocoder_adresse (tuple) inchangé", geocoding.geocoder_adresse("Gembloux") == (50.56, 4.69))
        geocoding.requests.get = faux_get([])
        check("introuvable → None", geocoding.geocoder_adresse_detail("Nulle part") is None)
        check("adresse vide → None sans requête", geocoding.geocoder_adresse_detail("  ") is None)
        geocoding.requests.get = faux_get(be)
        check("reverse : commune + cp du point", geocoding.commune_cp_depuis_coordonnees(50.56, 4.69)
              == {"commune": "Gembloux", "code_postal": "5030"})

        def boom(*a, **k):
            raise RuntimeError("réseau")
        geocoding.requests.get = boom
        check("échec réseau → None, ne lève pas",
              geocoding.geocoder_adresse_detail("Gembloux") is None
              and geocoding.commune_cp_depuis_coordonnees(1, 1) is None)
    finally:
        geocoding.requests.get = reel

    # --- flux /lieux ---
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "geo.sqlite3"))
        lieu = store.get_or_create_tiers_lieu("u1", "Lieu Géo")
        autre = store.get_or_create_tiers_lieu("u1", "Lieu Sans Adresse")
        store.update_tiers_lieu(lieu.id, latitude=50.56, longitude=4.69, commune="Gembloux", code_postal="5030")
        c = store.get_or_create_contributeur("c1", lieu.id, "fondateur")
        store.save_answer(lieu.id, c.id, "adresse", "Gembloux")
        c2 = store.get_or_create_contributeur("c1", autre.id, "fondateur")
        store.save_answer(autre.id, c2.id, "adresse", "Adresse confidentielle", confidentiel=True)

        os.environ["CTG_WEBHOOK_SECRET"] = "s3cret"
        api_app.get_store = lambda: store
        flux = {p["tiers_lieu"]: p for p in TestClient(api_app.app).get(
            "/lieux", headers={"X-Webhook-Secret": "s3cret"}).json()["lieux"]}
        g = flux["Lieu Géo"]
        check("flux : adresse, commune, code_postal",
              (g["adresse"], g["commune"], g["code_postal"]) == ("Gembloux", "Gembloux", "5030"))
        s = flux["Lieu Sans Adresse"]
        check("flux : adresse marquée confidentielle jamais exposée", s["adresse"] is None)
        check("flux : commune/code_postal absents → null (pas d'erreur)", s["commune"] is None and s["code_postal"] is None)
        check("flux : les coordonnées restent servies", g["latitude"] == 50.56)
    os.environ.pop("CTG_WEBHOOK_SECRET", None)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
