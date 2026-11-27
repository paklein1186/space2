"""Fiche du lieu pour troistiers.space (27/11) : flux public complété (gouvernance, ressources, modèle économique,
nombre de contributeurs) et synthèse interne pour les membres actifs (GET /lieux/{id}/interne), fermée par défaut.

Usage : python3 -m tests.test_api_lieu_interne
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src import sso
from src.api import app as api_app
from src.api import entretien_api as ent
from src.api.public_data import flux_lieux
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "l.sqlite3"))
        publie = store.get_or_create_tiers_lieu("u1", "Ferme publiée")
        cache = store.get_or_create_tiers_lieu("u1", "Lieu à peine renseigné")
        store.update_tiers_lieu(publie.id, ctg_entity_id="guilde-ctg-1")
        interne = {"resume": "Résumé interne.", "gouvernance": "Coopérative. Assemblée mensuelle.",
                   "besoins": "Trésorerie tendue (confidentiel).", "modele_economique": "Loyer 3200 €/mois."}
        publique = {"resume": "Résumé public.", "gouvernance": "Coopérative.", "ressources": "Cuisine partagée.",
                    "modele_economique": "Ventes et location d'espaces.", "besoins": "Communication."}
        for lieu in (publie, cache):
            store.save_lieu_derive(LieuDerive(tiers_lieu_id=lieu.id, donnees=interne, profil_semantique_texte="",
                                              prompt_version="t", model="t", source_hash="h"))
            store.update_lieu_derive_publique(lieu.id, publique, "h")

        api_app.get_store = lambda: store
        ent._identites.clear()
        ancien = sso.verifier_jeton_ctg
        sso.verifier_jeton_ctg = lambda jeton: ("membre@ex.org", "ctg-1") if jeton == "jeton-ok" else (_ for _ in ()).throw(sso.JetonInvalide())
        http = TestClient(api_app.app)
        os.environ["SITE_READ_SECRET"] = "cle-site"
        site = {"X-Webhook-Secret": "cle-site"}
        try:
            # A. Flux public : 3 rubriques de plus, nombre de contributeurs ; jamais la synthèse interne.
            lieux = {l["tiers_lieu"]: l for l in flux_lieux(store)}
            p = lieux.get("Ferme publiée") or {}
            check("flux : le lieu publié y est, pas le lieu à peine renseigné", "Ferme publiée" in lieux and "Lieu à peine renseigné" not in lieux)
            check("flux : gouvernance, ressources, modèle économique (version publique)",
                  (p.get("gouvernance"), p.get("ressources"), p.get("modele_economique")) == ("Coopérative.", "Cuisine partagée.", "Ventes et location d'espaces."))
            check("flux : nombre de contributeurs présent", "nombre_contributeurs" in p)
            check("flux : rien de la synthèse interne", "3200" not in str(p) and "confidentiel" not in str(p))

            # B. Synthèse interne : fermée par défaut.
            url = f"/lieux/{publie.id}/interne"
            os.environ.pop("SITE_LIEUX_INTERNE", None)
            check("interne : fermée par défaut (403)", http.get(url, headers={**site, "X-CTG-Token": "jeton-ok"}).status_code == 403)
            os.environ["SITE_LIEUX_INTERNE"] = "true"
            check("interne : sans clé du site → 401", http.get(url, headers={"X-CTG-Token": "jeton-ok"}).status_code == 401)
            check("interne : sans jeton CTG → 401", http.get(url, headers=site).status_code == 401)
            check("interne : jeton CTG refusé → 401", http.get(url, headers={**site, "X-CTG-Token": "faux"}).status_code == 401)
            r = http.get(url, headers={**site, "X-CTG-Token": "jeton-ok"})
            check("interne : clé + jeton → la synthèse interne", r.status_code == 200 and r.json()["sections"].get("modele_economique") == "Loyer 3200 €/mois.")
            check("interne : rien d'autre que le texte des sections",
                  set(r.json()) == {"space2_id", "tiers_lieu", "sections", "genere_le"})
            check("interne : lieu non publié → 404",
                  http.get(f"/lieux/{cache.id}/interne", headers={**site, "X-CTG-Token": "jeton-ok"}).status_code == 404)
            check("interne : lieu inconnu → 404",
                  http.get("/lieux/inconnu/interne", headers={**site, "X-CTG-Token": "jeton-ok"}).status_code == 404)
        finally:
            sso.verifier_jeton_ctg = ancien
            os.environ.pop("SITE_LIEUX_INTERNE", None)
            os.environ.pop("SITE_READ_SECRET", None)
    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
