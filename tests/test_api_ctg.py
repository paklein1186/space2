"""Intégration ctg : synthèse publique (aucune fuite), flux GET /lieux, lien
lieu <-> entité ctg, événements -> RAG, accès externes. Sans réseau.

Usage : python3 -m tests.test_api_ctg
"""

import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from src.agent.enrichissement_public import enrichir_public
from src.agent.rag_tools import activite_ctg_dataframe
from src.api import app as api_app
from src.api.public_data import DonneesPubliques
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive
from src.questionnaire.schema import all_fields, champ_public


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FauxClient:
    def __init__(self, json_texte):
        self.json_texte, self.prompts = json_texte, []
        self.messages = self

    def create(self, **kwargs):
        self.prompts.append(kwargs["messages"][0]["content"])
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=self.json_texte)],
            usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))


def main():
    champs = [f for _, _, f in all_fields()]
    publics = [f for f in champs if champ_public(f.id)]
    interne = next(f for f in champs if f.roles is not None and not champ_public(f.id))

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "ctg.sqlite3"))
        lieu = store.get_or_create_tiers_lieu("u1", "Lieu Un")
        sans_synthese = store.get_or_create_tiers_lieu("u1", "Lieu Sans Synthèse")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu.id, donnees={"resume": "SECRET_INTERNE dans la synthèse interne"},
            profil_semantique_texte="p", prompt_version="v1", model="m", source_hash="h"))
        c = store.get_or_create_contributeur("c1", lieu.id, "fondateur")
        store.save_answer(lieu.id, c.id, publics[0].id, "réponse publique")
        store.save_answer(lieu.id, c.id, publics[1].id, "CONFIDENTIEL_XYZ", confidentiel=True)
        store.save_answer(lieu.id, c.id, interne.id, "INTERNE_XYZ")

        # --- synthèse publique ---
        faux = FauxClient('{"resume": "Résumé public.", "categories": ["Culturel", "Inventée"], "mots_cles": ["a"]}')
        check("synthèse publique calculée", enrichir_public(store, lieu.id, client=faux))
        prompt = faux.prompts[0]
        check("le prompt contient la réponse publique", "réponse publique" in prompt)
        check("le prompt exclut confidentiel et interne",
              "CONFIDENTIEL_XYZ" not in prompt and "INTERNE_XYZ" not in prompt)
        derive = store.get_lieu_derive(lieu.id)
        check("catégories filtrées sur la liste autorisée", derive.donnees_publiques["categories"] == ["Culturel"])
        check("la synthèse interne n'est pas écrasée", "SECRET_INTERNE" in derive.donnees["resume"])
        check("recalcul ignoré si rien n'a changé", not enrichir_public(store, lieu.id, client=faux))
        check("lieu sans réponse publique : rien", not enrichir_public(store, sans_synthese.id, client=faux))

        # --- dataset agent : jamais la synthèse interne ---
        lieux_df = DonneesPubliques(store, ttl=0).get()["lieux"]
        check("dataset lieux : synthèse publique", "Résumé public." in set(lieux_df["resume"].dropna()))
        check("dataset lieux : pas de synthèse interne", "SECRET_INTERNE" not in str(lieux_df.to_dict()))

        os.environ["CTG_WEBHOOK_SECRET"] = "s3cret"
        api_app.get_store = lambda: store
        http = TestClient(api_app.app)
        h = {"X-Webhook-Secret": "s3cret"}

        # --- flux ---
        check("flux sans secret → 401", http.get("/lieux").status_code == 401)
        flux = http.get("/lieux", headers=h).json()["lieux"]
        par_nom = {p["tiers_lieu"]: p for p in flux}
        check("flux : tous les lieux, même sans synthèse", set(par_nom) == {"Lieu Un", "Lieu Sans Synthèse"})
        check("flux : synthèse publique", par_nom["Lieu Un"]["resume"] == "Résumé public.")
        check("flux : jamais la synthèse interne", "SECRET_INTERNE" not in str(flux))
        check("flux : campagne absente hors Portfolio", par_nom["Lieu Un"]["campagne"] is None)
        recent = par_nom["Lieu Un"]["updated_at"]
        check("updated_since futur : seul le lieu sans date reste",
              [p["tiers_lieu"] for p in http.get("/lieux", params={"updated_since": "2999-01-01"},
                                                headers=h).json()["lieux"]] == ["Lieu Sans Synthèse"])
        check("updated_since passé : les deux",
              len(http.get("/lieux", params={"updated_since": "2000-01-01"}, headers=h).json()["lieux"]) == 2)
        check("date de mise à jour renseignée", bool(recent))

        # --- lien ---
        check("lien : lieu inconnu → 404",
              http.post("/lieux/nope/link", json={"ctg_entity_id": "E1"}, headers=h).status_code == 404)
        check("lien OK", http.post(f"/lieux/{lieu.id}/link", json={"ctg_entity_id": "E1"},
                                   headers=h).status_code == 200)
        check("lien : même entité sur un autre lieu → 409",
              http.post(f"/lieux/{sans_synthese.id}/link", json={"ctg_entity_id": "E1"},
                        headers=h).status_code == 409)
        check("lien visible dans le flux",
              {p["tiers_lieu"]: p for p in http.get("/lieux", headers=h).json()["lieux"]}
              ["Lieu Un"]["ctg_entity_id"] == "E1")

        # --- événements ---
        ev = {"ctg_event_id": "ev1", "ctg_entity_id": "E1", "type": "discussion", "titre": "Salut",
              "texte": "Un échange public.", "url": "https://ctg.example/d/1",
              "occurred_at": "2026-09-20T10:00:00Z"}
        rep = http.post("/events", json={"events": [ev, {**ev, "ctg_event_id": "ev2", "ctg_entity_id": "E404"}]},
                        headers=h).json()
        check("événement accepté / inconnu rejeté", rep["accepted"] == 1 and len(rep["rejected"]) == 1)
        http.post("/events", json={"events": [{**ev, "titre": "Modifié"}]}, headers=h)
        lignes = activite_ctg_dataframe(store)
        check("idempotent sur ctg_event_id (1 ligne, mise à jour)",
              len(lignes) == 1 and lignes.iloc[0]["titre"] == "Modifié")
        check("visible dans le dataset agent",
              len(DonneesPubliques(store, ttl=0).get()["activite_ctg"]) == 1)
        check("url non http → 422", http.post("/events", json={"events": [{**ev, "url": "javascript:x"}]},
                                             headers=h).status_code == 422)
        check("type inconnu → 422", http.post("/events", json={"events": [{**ev, "type": "spam"}]},
                                             headers=h).status_code == 422)
        check("date invalide → 422", http.post("/events", json={"events": [{**ev, "occurred_at": "hier"}]},
                                              headers=h).status_code == 422)

        # --- accès ---
        check("accès inconnu par défaut", not store.has_acces_externe("Membre@Example.org"))
        check("PUT /access OK", http.put("/access", json={"members": [
            {"email": "Membre@Example.org", "guilde_id": "g1"}]}, headers=h).json() == {"updated": 1})
        check("accès actif (insensible à la casse)", store.has_acces_externe("membre@example.org"))
        http.put("/access", json={"members": [{"email": "membre@example.org", "statut": "revoque"}]}, headers=h)
        check("accès révoqué", not store.has_acces_externe("membre@example.org"))
        check("email invalide → 422", http.put("/access", json={"members": [{"email": "pas-un-email"}]},
                                              headers=h).status_code == 422)
        check("accès sans secret → 401", http.put("/access", json={"members": []}).status_code == 401)
    os.environ.pop("CTG_WEBHOOK_SECRET", None)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
