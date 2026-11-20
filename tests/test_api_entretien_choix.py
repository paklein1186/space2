"""Réponse rapide (choix multiple, choix unique, oui/non, échelle) dans l'entretien mené depuis
troistiers.space : la question en attente est exposée, la réponse est validée puis enregistrée,
l'agent enchaîne. Base SQLite temporaire, agent simulé.

Usage : python3 -m tests.test_api_entretien_choix
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

ECHECS = []


def check(nom, ok):
    print(("[OK ] " if ok else "[KO ] ") + nom)
    if not ok:
        ECHECS.append(nom)


QUESTIONS = [
    {"id": "liens_entreprises", "label": "Liens avec les entreprises du territoire", "type": "multi_choice",
     "options": ["Financement d'activités", "Co-développement de projets", "Pas de lien"], "max_choices": 2},
    {"id": "milieu", "label": "Milieu", "type": "single_choice", "options": ["Rural", "Urbain"]},
    {"id": "accessible_pmr", "label": "Accessible aux personnes à mobilité réduite", "type": "boolean"},
    {"id": "satisfaction", "label": "Satisfaction", "type": "scale_1_5"},
]


class Handler:
    def __init__(self, store, conv):
        self.store, self.conv = store, conv

    def execute(self, nom, params):
        reponses = self.store.get_answers(self.conv["tiers_lieu_id"])
        if nom == "get_current_section":
            restantes = [q for q in QUESTIONS if q["id"] not in reponses]
            return {"module_id": "m", "fields": restantes}
        if nom == "save_answer":
            self.store.save_answer(self.conv["tiers_lieu_id"], self.conv["contributeur_id"], params["champ_id"], params["valeur"])
            return {"ok": True}
        raise KeyError(nom)

    def campagne_completion(self):
        return None


class FauxAgent:
    def __init__(self, store, conv, user_id):
        self.messages = list(conv.get("messages") or [])
        self.tool_handler = Handler(store, conv)

    def send(self, texte):
        self.messages.append({"role": "user", "content": texte})
        self.messages.append({"role": "assistant", "content": [{"type": "text", "text": "Merci, on continue."}]})
        return "Merci, on continue."


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "c.sqlite3"))
        lieu = store.get_or_create_tiers_lieu("x", "La Ferme du Bois")
        api_app.get_store = lambda: store
        ent._cache_lieux.clear(); ent._identites.clear(); ent._conversations_dev.lignes.clear()
        for nom in ("ouvrir", "repondre", "lire", "repondre_choix"):
            f = getattr(ent, nom)
            setattr(ent, nom, (lambda f: lambda *a, **k: f(*a, **k, fabrique_agent=FauxAgent))(f))
        sso.verifier_jeton_ctg = lambda j: ("pa@exemple.org", "id") if j == "jeton-de-pa-123456" else (_ for _ in ()).throw(sso.JetonInvalide("x"))
        os.environ["SITE_READ_SECRET"] = "cle-site"
        os.environ["CTG_WEBHOOK_SECRET"] = "secret-ctg"
        api_app._appels_site.clear()
        http = TestClient(api_app.app)
        h = {"X-Webhook-Secret": "cle-site", "X-CTG-Token": "jeton-de-pa-123456"}

        conv = http.post("/entretien/conversations", json={"lieu_id": lieu.id, "role": "fondateur"}, headers=h).json()
        q = conv["choix_rapide"]
        check("ouverture : la question à choix en attente est exposée",
              q["champ_id"] == "liens_entreprises" and q["type"] == "multi_choice" and len(q["options"]) == 3 and q["max_choices"] == 2)
        check("relecture : même question exposée", http.get(f"/entretien/conversations/{conv['id']}", headers=h).json()["choix_rapide"]["champ_id"] == "liens_entreprises")

        url = f"/entretien/conversations/{conv['id']}/choix"
        def choix(champ, valeur):
            api_app._appels_site.clear()
            return http.post(url, json={"champ_id": champ, "valeur": valeur}, headers=h)
        check("option inventée → 400", choix("liens_entreprises", ["Pots-de-vin"]).status_code == 400)
        check("trop de choix → 400", choix("liens_entreprises", QUESTIONS[0]["options"]).status_code == 400)
        check("une autre question que celle en attente → 400", choix("milieu", "Rural").status_code == 400)
        check("liste vide → 400", choix("liens_entreprises", []).status_code == 400)

        r = choix("liens_entreprises", ["Financement d'activités", "Co-développement de projets", "Financement d'activités"])
        check("choix multiple accepté", r.status_code == 200)
        check("enregistré dans le lieu, sans doublon",
              store.get_answers(lieu.id)["liens_entreprises"] == ["Financement d'activités", "Co-développement de projets"])
        hist = r.json()["historique"]
        check("affiché comme réponse de la personne, puis l'agent enchaîne",
              hist[-2] == {"role": "user", "texte": "Liens avec les entreprises du territoire : Financement d'activités, Co-développement de projets"}
              and hist[-1]["role"] == "assistant")
        check("question suivante exposée", r.json()["choix_rapide"]["champ_id"] == "milieu")

        check("choix unique hors options → 400", choix("milieu", "Montagne").status_code == 400)
        check("choix unique accepté", choix("milieu", "Rural").status_code == 200 and store.get_answers(lieu.id)["milieu"] == "Rural")
        check("oui/non : texte refusé", choix("accessible_pmr", "oui").status_code == 400)
        check("oui/non accepté", choix("accessible_pmr", True).status_code == 200 and store.get_answers(lieu.id)["accessible_pmr"] is True)
        check("échelle hors bornes → 400", choix("satisfaction", 6).status_code == 400)
        r = choix("satisfaction", 4)
        check("échelle acceptée, plus de question à choix", r.status_code == 200 and r.json()["choix_rapide"] is None)

        autre = {"X-Webhook-Secret": "cle-site", "X-CTG-Token": "jeton-d-alice-xx"}
        sso.verifier_jeton_ctg = lambda j: ("alice@exemple.org", "id2")
        ent._identites.clear()
        check("une autre personne ne peut pas répondre → 404",
              http.post(url, json={"champ_id": "x", "valeur": True}, headers=autre).status_code == 404)

        for k in ("SITE_READ_SECRET", "CTG_WEBHOOK_SECRET"):
            os.environ.pop(k, None)
    if ECHECS:
        print(f"{len(ECHECS)} échec(s)")
        sys.exit(1)
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
