"""Entretien depuis troistiers.space (API /entretien) : identité vérifiée auprès de ChangeTheGame,
conversation enregistrée et reprise, propriétaire seul, réponses dans les tables habituelles.
Base SQLite temporaire ; l'agent de collecte est simulé (pas d'appel à Claude).

Usage : python3 -m tests.test_api_entretien
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
from src.db.sqlite_store import SqliteStore
from src.db.store import CampagnePrioritaire

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


class FauxAgent:
    """Rejoue le contrat de CollecteAgent : messages en JSON, send() renvoie le texte de l'agent,
    et l'agent enregistre une réponse dans le lieu (comme le ferait un outil de collecte)."""

    def __init__(self, store, conv, user_id):
        self.store, self.conv = store, conv
        self.messages = list(conv.get("messages") or [])
        self.tool_handler = type("H", (), {"campagne_completion": lambda s: None})()

    def send(self, texte):
        self.messages.append({"role": "user", "content": texte})
        n = sum(1 for m in self.messages if m["role"] == "user")
        if n > 1:
            self.store.save_answer(self.conv["tiers_lieu_id"], self.conv["contributeur_id"], "activites", texte)
        reponse = f"Question {n} de l'agent"
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": reponse}]})
        return reponse


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "e.sqlite3"))
        store.get_or_create_tiers_lieu("quelqu-un", "La Ferme du Bois")
        store.get_or_create_tiers_lieu("quelqu-un", "Café Bonheur")
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Autodiagnostic", champ_ids=["activites"], date_debut="2000-01-01", date_fin="2999-12-31",
            code="ka122"))

        api_app.get_store = lambda: store
        ent._cache_lieux.clear()
        ent._identites.clear()
        ent._conversations_dev.lignes.clear()
        ancien_ouvrir, ancien_repondre = ent.ouvrir, ent.repondre
        ent.ouvrir = lambda *a, **k: ancien_ouvrir(*a, **k, fabrique_agent=FauxAgent)
        ent.repondre = lambda *a, **k: ancien_repondre(*a, **k, fabrique_agent=FauxAgent)
        jetons = {"jeton-de-pa-123456": "pa@exemple.org", "jeton-d-alice-123": "alice@exemple.org"}
        appels_ctg = []

        def verifier(jeton):
            appels_ctg.append(jeton)
            if jeton not in jetons:
                raise sso.JetonInvalide("non")
            return jetons[jeton], "ctg-id"
        sso.verifier_jeton_ctg = verifier

        os.environ["SITE_READ_SECRET"] = "cle-site"
        os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"
        http = TestClient(api_app.app)
        pa = {"X-Webhook-Secret": "cle-site", "X-CTG-Token": "jeton-de-pa-123456"}
        alice = {"X-Webhook-Secret": "cle-site", "X-CTG-Token": "jeton-d-alice-123"}
        api_app._appels_site.clear()

        # Accès
        check("sans clé du site → 401", http.get("/entretien/lieux?q=ferme", headers={"X-CTG-Token": "jeton-de-pa-123456"}).status_code == 401)
        check("clé du site sans jeton ctg → 401", http.get("/entretien/lieux?q=ferme", headers={"X-Webhook-Secret": "cle-site"}).status_code == 401)
        check("jeton refusé par ctg → 401", http.get("/entretien/lieux?q=ferme", headers={**pa, "X-CTG-Token": "faux-jeton-xxxx"}).status_code == 401)

        # Recherche de lieu
        r = http.get("/entretien/lieux?q=ferme", headers=pa)
        check("recherche de lieu (sans casse)", r.status_code == 200 and [l["nom"] for l in r.json()["lieux"]] == ["La Ferme du Bois"])
        check("identité vérifiée une fois puis gardée", appels_ctg.count("jeton-de-pa-123456") == 1
              and http.get("/entretien/lieux?q=cafe", headers=pa).json()["lieux"][0]["nom"] == "Café Bonheur"
              and appels_ctg.count("jeton-de-pa-123456") == 1)

        # Ouverture sur un lieu existant
        lieu_id = r.json()["lieux"][0]["id"]
        o = http.post("/entretien/conversations", json={"lieu_id": lieu_id, "role": "fondateur"}, headers=pa)
        conv = o.json()
        check("ouverture : message d'accueil de l'agent", o.status_code == 200 and conv["historique"] == [{"role": "assistant", "texte": "Question 1 de l'agent"}])
        check("ouverture : nom du lieu pré-rempli", any(c.nom == "La Ferme du Bois" for c in store.list_tiers_lieux()))

        # Un tour de conversation
        m = http.post(f"/entretien/conversations/{conv['id']}/messages", json={"texte": "Un atelier bois et un potager."}, headers=pa)
        check("réponse de l'agent ajoutée à l'historique", m.status_code == 200 and [h["role"] for h in m.json()["historique"]] == ["assistant", "user", "assistant"])
        reponses = store.get_answers(lieu_id)
        check("la réponse est enregistrée dans le lieu, comme dans l'app", reponses.get("activites") == "Un atelier bois et un potager.")

        # Reprise
        relue = http.get(f"/entretien/conversations/{conv['id']}", headers=pa).json()
        check("reprise : historique complet relu", len(relue["historique"]) == 3 and relue["nom_lieu"] == "La Ferme du Bois")
        suite = http.post(f"/entretien/conversations/{conv['id']}/messages", json={"texte": "Et des ateliers vélo."}, headers=pa).json()
        check("reprise : l'agent repart avec toute la conversation", suite["historique"][-1]["texte"] == "Question 3 de l'agent")
        check("liste des entretiens de la personne", [c["id"] for c in http.get("/entretien/conversations", headers=pa).json()["conversations"]] == [conv["id"]])

        # Propriétaire seul
        check("une autre personne ne peut pas lire la conversation → 404",
              http.get(f"/entretien/conversations/{conv['id']}", headers=alice).status_code == 404)
        check("ni y écrire → 404",
              http.post(f"/entretien/conversations/{conv['id']}/messages", json={"texte": "pirate"}, headers=alice).status_code == 404)
        check("et ne la voit pas dans sa liste", http.get("/entretien/conversations", headers=alice).json()["conversations"] == [])

        # Nouveau lieu, enquête, erreurs
        n = http.post("/entretien/conversations", json={"nouveau_lieu": "Tiers-lieu des Tilleuls", "role": "equipe"}, headers=alice)
        check("nouveau lieu créé à l'ouverture", n.status_code == 200 and n.json()["nom_lieu"] == "Tiers-lieu des Tilleuls")
        e = http.post("/entretien/conversations", json={"lieu_id": lieu_id, "role": "equipe", "mode": "campagne", "campagne": "ka122"}, headers=alice)
        check("enquête par son code", e.status_code == 200 and e.json()["campagne_id"])
        check("enquête inconnue → 404", http.post("/entretien/conversations", json={"lieu_id": lieu_id, "role": "equipe", "mode": "campagne", "campagne": "nope"}, headers=alice).status_code == 404)
        check("rôle inconnu → 400", http.post("/entretien/conversations", json={"lieu_id": lieu_id, "role": "roi"}, headers=alice).status_code == 400)
        check("lieu inconnu → 404", http.post("/entretien/conversations", json={"lieu_id": "nope", "role": "equipe"}, headers=alice).status_code == 404)
        check("sans lieu → 400", http.post("/entretien/conversations", json={"role": "equipe"}, headers=alice).status_code == 400)

        # Le vrai agent de collecte se reconstruit à partir de la conversation enregistrée.
        os.environ.setdefault("ANTHROPIC_API_KEY", "test-sans-appel")
        enreg = ent.conversations_du_store(store).lire(conv["id"])
        vrai = ent._agent_par_defaut(store, enreg, enreg["user_id"])
        check("vrai agent : conversation rechargée telle quelle", vrai.messages == enreg["messages"] and len(vrai.messages) == 6)
        check("vrai agent : lieu, contributeur et rôle de la conversation",
              vrai.tool_handler.tiers_lieu_id == lieu_id and vrai.tool_handler.contributeur_id == enreg["contributeur_id"]
              and vrai.tool_handler.role.value == "fondateur")

        ent.ouvrir, ent.repondre = ancien_ouvrir, ancien_repondre
        for k in ("SITE_READ_SECRET", "CTG_WEBHOOK_SECRET"):
            os.environ.pop(k, None)
    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
