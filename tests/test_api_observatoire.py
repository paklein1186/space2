"""Observatoire et enquêtes pour le site : agrégats seulement, seuil de 3 lieux,
filtres pays/région, clé du site acceptée, rien de nominatif. Sans réseau ni base.

Usage : python3 -m tests.test_api_observatoire
"""

import os
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi.testclient import TestClient

from src.api import app as api_app
from src.api import observatoire as obs

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


def lieu(nom, pays, region, cats=None, mots=None, enjeux=None):
    return {"tiers_lieu": nom, "pays": pays, "region": region, "categories": cats or [],
            "mots_cles": mots or [], "enjeux": enjeux, "space2_id": nom.lower()}


DF_LIEUX = pd.DataFrame([
    lieu("Atelier A", "Belgique", "Wallonie", ["Culturel"], ["bois"], "Enjeu SECRET A"),
    lieu("Ferme B", "Belgique", "Wallonie", ["Alimentaire"], ["bois", "potager"]),
    lieu("Café C", "Belgium", "Bruxelles", ["Culturel", "Éducation"], ["café"]),
    lieu("Lieu D", "France", "Hauts-de-France", ["Santé"]),
])

DF_REPONSES = pd.DataFrame([
    {"tiers_lieu": "Atelier A", "pays": "Belgique", "region": "Wallonie", "contributeur_id": "1", "champ": "", "champ_id": "statut_juridique", "valeur": "ASBL"},
    {"tiers_lieu": "Atelier A", "pays": "Belgique", "region": "Wallonie", "contributeur_id": "2", "champ": "", "champ_id": "statut_juridique", "valeur": "ASBL"},
    {"tiers_lieu": "Ferme B", "pays": "Belgique", "region": "Wallonie", "contributeur_id": "1", "champ": "", "champ_id": "statut_juridique", "valeur": "Coopérative"},
    {"tiers_lieu": "Atelier A", "pays": "Belgique", "region": "Wallonie", "contributeur_id": "1", "champ": "", "champ_id": "surface_batie_m2", "valeur": "300"},
    {"tiers_lieu": "Café C", "pays": "Belgium", "region": "Bruxelles", "contributeur_id": "1", "champ": "", "champ_id": "surface_batie_m2", "valeur": "200"},
    {"tiers_lieu": "Café C", "pays": "Belgium", "region": "Bruxelles", "contributeur_id": "1", "champ": "", "champ_id": "date_ouverture", "valeur": "ouvert en mars 2019"},
    {"tiers_lieu": "Lieu D", "pays": "France", "region": "Hauts-de-France", "contributeur_id": "1", "champ": "", "champ_id": "statut_juridique", "valeur": "SCIC"},
])


def main():
    be = obs.agregats(DF_LIEUX, DF_REPONSES, pays=["Belgique", "belgium"])
    check("filtre pays : 3 lieux belges (écritures mêlées)", be["totaux"]["lieux"] == 3)
    check("lieu français exclu", "SCIC" not in str(be) and "France" not in str(be["repartitions"]["pays"]))
    check("catégories comptées dans l'ordre du questionnaire",
          be["repartitions"]["categories"] == [{"valeur": "Culturel", "n": 2}, {"valeur": "Éducation", "n": 1},
                                                {"valeur": "Alimentaire", "n": 1}]
          or [c["valeur"] for c in be["repartitions"]["categories"]] == ["Alimentaire", "Culturel", "Éducation"])
    check("un lieu compte une fois par champ (2 contributeurs ASBL → 1)",
          {"valeur": "ASBL", "n": 1} in be["repartitions"]["statut_juridique"])
    check("surface : somme et nombre de lieux", be["totaux"]["surface_batie_m2"] == {"total": 500, "n": 2})
    check("année tirée d'un texte libre", be["repartitions"]["annee_ouverture"] == [{"valeur": "2019", "n": 1}])
    check("mots-clés comptés", {"valeur": "bois", "n": 2} in be["repartitions"]["mots_cles"])
    check("rien de nominatif : ni noms de lieux, ni enjeux",
          not any(x in str(be) for x in ("Atelier A", "Ferme B", "Café C", "SECRET", "atelier a")))

    wal = obs.agregats(DF_LIEUX, DF_REPONSES, pays=["Belgique"], region="wallonie")
    check("sous le seuil (2 lieux) : totaux seulement, pas de répartition",
          wal["totaux"]["lieux"] == 2 and wal["repartitions"] is None and "ASBL" not in str(wal))
    check("périmètre vide : zéro, sans erreur", obs.agregats(DF_LIEUX, DF_REPONSES, pays=["Japon"])["totaux"]["lieux"] == 0)
    check("tables vides : sans erreur", obs.agregats(pd.DataFrame(columns=DF_LIEUX.columns), pd.DataFrame(), pays=None)["totaux"]["lieux"] == 0)

    # Routes : clé du site acceptée, agrégats seulement.
    api_app.get_store = lambda: types.SimpleNamespace(get_active_campagnes_prioritaires=lambda: [
        types.SimpleNamespace(id="uuid-1", code="ka122", titre="Autodiagnostic", description="Pour les lieux du GAL", date_fin="2027-01-31"),
        types.SimpleNamespace(id="uuid-2", code=None, titre="Sans code", description=None, date_fin="2027-02-01"),
    ])
    obs.donnees = lambda store: (DF_LIEUX, DF_REPONSES)
    http = TestClient(api_app.app)
    os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"
    os.environ["SITE_READ_SECRET"] = "cle-site"
    site = {"X-Webhook-Secret": "cle-site"}
    r = http.get("/observatoire", params={"pays": "Belgique,Belgium"}, headers=site)
    check("GET /observatoire avec la clé du site", r.status_code == 200 and r.json()["totaux"]["lieux"] == 3)
    check("GET /observatoire sans clé → 401", http.get("/observatoire").status_code == 401)
    c = http.get("/campagnes", headers=site)
    check("GET /campagnes : code court, sinon identifiant",
          c.status_code == 200 and [x["code"] for x in c.json()["campagnes"]] == ["ka122", "uuid-2"])
    check("GET /campagnes sans clé → 401", http.get("/campagnes").status_code == 401)
    os.environ.pop("CTG_WEBHOOK_SECRET", None)
    os.environ.pop("SITE_READ_SECRET", None)

    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
