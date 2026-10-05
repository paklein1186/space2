"""CollecteAgent._run_until_text / send_stream : le message de clôture d'une
campagne prioritaire (voir CollecteToolHandler._section_cloture_campagne)
est restitué tel quel, sans jamais dépendre de ce que le modèle choisirait de
dire à ce tour-ci — vécu en test manuel : même avec une consigne système
explicite, le modèle reformulait ou sautait carrément ce message pour
enchaîner sur autre chose. Le client Anthropic est simulé (aucun appel
réseau) ; seul le dernier tour (celui qui clôt la campagne) doit déclencher
UN SEUL appel au modèle, pas deux.

Usage : python3 -m tests.test_collecte_agent_cloture
"""

import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from src.agent.collecte_agent import CollecteAgent
from src.agent.collecte_tools import CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.db.store import CampagnePrioritaire
from src.questionnaire.schema import Role


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


class FakeBlock:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none=True):
        return dict(self.__dict__)


class FakeStreamContext:
    """Simule `client.messages.stream(...)` utilisé comme context manager
    (`with ... as stream: yield from stream.text_stream`) — notre réponse
    simulée n'est qu'un tool_use, donc text_stream est vide."""

    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(())

    def get_final_message(self):
        return self.response


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self.response

    def stream(self, **kwargs):
        self.calls += 1
        return FakeStreamContext(self.response)


class FakeClient:
    def __init__(self, response):
        self.messages = FakeMessages(response)


def _fenetre_active() -> tuple:
    maintenant = datetime.now(timezone.utc)
    return (maintenant - timedelta(days=1)).isoformat(), (maintenant + timedelta(days=30)).isoformat()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "agent_cloture.sqlite3"))
        debut, fin = _fenetre_active()
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Campagne Test Agent", champ_ids=["pays"], date_debut=debut, date_fin=fin,
            message_cloture="Merci, dossier complet.",
        ))
        lieu = store.get_or_create_tiers_lieu("u1", "Lieu Agent Test")
        contributeur = store.get_or_create_contributeur("u1", lieu.id, Role.AUTRE.value)
        session = store.get_or_start_session(lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.AUTRE,
                                      mode_entretien="campagne")
        agent = CollecteAgent(handler)

        tool_use = FakeBlock(type="tool_use", id="tu1", name="save_answer",
                             input={"champ_id": "pays", "valeur": "France"})
        agent.client = FakeClient(types.SimpleNamespace(content=[tool_use], stop_reason="tool_use"))

        reply = agent.send("On est en France.")
        check("réponse = le message de clôture configuré, verbatim",
              "Merci, dossier complet." in reply)
        check("coda fixe (Bibliothèque / ressources) toujours ajoutée", "Bibliothèque" in reply)
        check("un seul appel au modèle pour ce tour (pas de second aller-retour après le tool_result)",
              agent.client.messages.calls == 1)
        check("le message de clôture est bien celui ajouté à l'historique pour la suite",
              agent.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": reply}]})
        check("la réponse 'pays' a bien été enregistrée avant la clôture",
              store.get_answers(lieu.id, contributeur.id).get("pays") == "France")

        # --- même vérification côté send_stream (chemin utilisé par le chat
        #     normal, pas le "quick answer") : un deuxième lieu, pour repartir
        #     d'une campagne non encore répondue ---
        lieu2 = store.get_or_create_tiers_lieu("u1", "Lieu Agent Test Stream")
        contributeur2 = store.get_or_create_contributeur("u1", lieu2.id, Role.AUTRE.value)
        session2 = store.get_or_start_session(lieu2.id, contributeur2.id)
        handler2 = CollecteToolHandler(store, lieu2.id, contributeur2.id, session2, Role.AUTRE,
                                       mode_entretien="campagne")
        agent2 = CollecteAgent(handler2)
        tool_use2 = FakeBlock(type="tool_use", id="tu2", name="save_answer",
                              input={"champ_id": "pays", "valeur": "Belgique"})
        agent2.client = FakeClient(types.SimpleNamespace(content=[tool_use2], stop_reason="tool_use"))
        morceaux = list(agent2.send_stream("On est en Belgique."))
        reply2 = "".join(morceaux)
        check("send_stream : même clôture verbatim (pas de second appel API pour la reformuler)",
              "Merci, dossier complet." in reply2 and agent2.client.messages.calls == 1)

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
