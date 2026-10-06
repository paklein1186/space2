"""quitter_campagne (collecte_tools.py) : quand le répondant décline une campagne
prioritaire, la section prioritaire ne revient plus et l'entretien enchaîne en
mode classique, sans message de clôture. Sans réseau, sans appel LLM.

Usage : python3 -m tests.test_quitter_campagne
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import PRIORITY_MODULE_ID, CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.db.store import CampagnePrioritaire
from src.questionnaire.schema import Role


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "quitter.sqlite3"))
        maintenant = datetime.now(timezone.utc)
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Campagne test", champ_ids=["pays", "region"],
            date_debut=(maintenant - timedelta(days=1)).isoformat(),
            date_fin=(maintenant + timedelta(days=30)).isoformat(),
            message_cloture="Message de clôture",
        ))

        lieu = store.get_or_create_tiers_lieu("user-1", "Lieu Quitter Test")
        contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.AUTRE.value)
        session = store.get_or_start_session(lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.AUTRE,
                                      mode_entretien="campagne")

        check("campagne proposée avant refus",
              handler.get_current_section({})["section_id"] == PRIORITY_MODULE_ID)

        resultat = handler.execute("quitter_campagne", {})
        check("quitter_campagne répond ok", resultat.get("ok") is True)

        section = handler.get_current_section({})
        check("après refus : la section prioritaire ne revient plus",
              section["section_id"] != PRIORITY_MODULE_ID)
        check("après refus : pas de message de clôture de campagne",
              not section.get("cloture_campagne"))


    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
