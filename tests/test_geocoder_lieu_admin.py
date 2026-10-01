"""geocoder_lieu_admin (geocoding.py) : géocodage à la demande, depuis la
fiche admin, d'un lieu sans coordonnées — y compris via le repli progressif
de geocoder_adresse_avec_repli quand l'adresse complète (rue mal formée...)
n'est pas reconnue mais que la commune seule l'est. Sans réseau.

Usage : python3 -m tests.test_geocoder_lieu_admin
"""

import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import geocoding
from src.geocoding import geocoder_lieu_admin
from src.db.sqlite_store import SqliteStore


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def faux_get(payload):
    def _get(url, params=None, headers=None, timeout=None):
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    return _get


def faux_get_selectif(reponses):
    def _get(url, params=None, headers=None, timeout=None):
        return types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: reponses.get(params["q"], []))
    return _get


def main():
    reel = geocoding.requests.get
    try:
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteStore(db_path=str(Path(tmp) / "geo_admin.sqlite3"))

            # --- lieu sans aucune réponse "adresse" : rien à géocoder ---
            lieu_sans_adresse = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Sans Adresse Du Tout")
            resultat = geocoder_lieu_admin(store, lieu_sans_adresse.id)
            check("sans adresse connue : statut sans_adresse", resultat == {"statut": "sans_adresse"})

            # --- lieu avec commune déjà connue mais sans lat/lon, et une
            #     réponse "adresse" publique disponible ---
            lieu = store.get_or_create_tiers_lieu("admin@x.org", "Badinage Artistique")
            store.update_tiers_lieu(lieu.id, commune="Gembloux", code_postal="5030")
            c = store.get_or_create_contributeur("admin@x.org", lieu.id, "fondateur")
            store.save_answer(lieu.id, c.id, "adresse", "Gembloux")

            geocoding.requests.get = faux_get([{
                "lat": "50.56", "lon": "4.69",
                "address": {"municipality": "Gembloux", "postcode": "5030", "country_code": "be"},
            }])
            resultat2 = geocoder_lieu_admin(store, lieu.id, pays="Belgique")
            check("adresse connue, commune déjà là mais pas de lat/lon : statut ok + coordonnées renvoyées",
                  resultat2 == {"statut": "ok", "latitude": 50.56, "longitude": 4.69})
            relu = store.get_or_create_tiers_lieu("admin@x.org", "Badinage Artistique")
            check("coordonnées effectivement posées sur le lieu",
                  relu.latitude == 50.56 and relu.longitude == 4.69)

            # --- adresse connue mais introuvable par Nominatim ---
            lieu_introuvable = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Adresse Introuvable")
            c2 = store.get_or_create_contributeur("admin@x.org", lieu_introuvable.id, "fondateur")
            store.save_answer(lieu_introuvable.id, c2.id, "adresse", "Nulle part connue")
            geocoding.requests.get = faux_get([])
            resultat3 = geocoder_lieu_admin(store, lieu_introuvable.id)
            check("adresse introuvable par Nominatim : statut introuvable", resultat3 == {"statut": "introuvable"})

            # --- rue mal formée dans l'adresse complète : repli sur la commune seule ---
            lieu_repli = store.get_or_create_tiers_lieu("admin@x.org", "Badinage Artistique Rue Inconnue")
            c_repli = store.get_or_create_contributeur("admin@x.org", lieu_repli.id, "fondateur")
            store.save_answer(lieu_repli.id, c_repli.id, "adresse", "Rue Bidon 123, 5030, Gembloux")
            geocoding.requests.get = faux_get_selectif({
                "Gembloux, Belgique": [{
                    "lat": "50.56", "lon": "4.69",
                    "address": {"municipality": "Gembloux", "postcode": "5030", "country_code": "be"},
                }],
            })
            resultat_repli = geocoder_lieu_admin(store, lieu_repli.id, pays="Belgique")
            check("rue inconnue mais commune reconnue : statut ok via le repli progressif",
                  resultat_repli == {"statut": "ok", "latitude": 50.56, "longitude": 4.69})

            # --- adresse confidentielle : jamais lue par get_public_answers_batch ---
            lieu_confidentiel = store.get_or_create_tiers_lieu("admin@x.org", "Lieu Adresse Confidentielle")
            c3 = store.get_or_create_contributeur("admin@x.org", lieu_confidentiel.id, "fondateur")
            store.save_answer(lieu_confidentiel.id, c3.id, "adresse", "Secrète 12", confidentiel=True)
            resultat4 = geocoder_lieu_admin(store, lieu_confidentiel.id)
            check("adresse confidentielle : traitée comme absente (sans_adresse)",
                  resultat4 == {"statut": "sans_adresse"})
        print("Tous les tests passent.")
    finally:
        geocoding.requests.get = reel


if __name__ == "__main__":
    main()
