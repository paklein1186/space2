"""Une campagne ne doit être considérée "entamée" pour un lieu que si au
moins une réponse a été donnée ACTIVEMENT via l'entretien conversationnel
dans le cadre de CETTE campagne (reponses.campagne_id) — jamais parce qu'un
champ partagé avec la campagne a déjà une valeur par ailleurs (import en
masse, entretien général sans rapport). Cas vécu : une campagne proposait
"Continuer" pour un lieu dont les champs recoupaient des données importées
(CSV/CommunECter), jamais répondues en vrai pour cette campagne. Sans réseau.

Usage : python3 -m tests.test_campagne_entamee_active
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.db.store import CampagnePrioritaire
from src.questionnaire.schema import Role


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def _fenetre_active() -> tuple:
    maintenant = datetime.now(timezone.utc)
    return (maintenant - timedelta(days=1)).isoformat(), (maintenant + timedelta(days=30)).isoformat()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "entamee.sqlite3"))
        debut, fin = _fenetre_active()

        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="KA122 Mobilité", champ_ids=["pays", "region"], date_debut=debut, date_fin=fin,
        ))
        campagne = next(c for c in store.list_campagnes_prioritaires() if c.titre == "KA122 Mobilité")

        # --- champs déjà renseignés par import (CSV/CommunECter), jamais via
        # l'entretien conversationnel : campagne_id reste None (comportement
        # par défaut de save_answer, comme tous les scripts d'import) ---
        lieu_importe = store.get_or_create_tiers_lieu("user-import", "Lieu Importé")
        contributeur_import = store.get_or_create_contributeur("import-csv", lieu_importe.id, Role.AUTRE.value)
        store.save_answer(lieu_importe.id, contributeur_import.id, "pays", "Belgique")
        store.save_answer(lieu_importe.id, contributeur_import.id, "region", "Namur")

        check("champs importés (2/2) : get_answers les voit bien",
              store.get_answers(lieu_importe.id).get("pays") == "Belgique")
        check("mais AUCUNE campagne 'entamée' détectée (jamais répondu activement)",
              store.get_campagne_ids_entames(lieu_importe.id) == set())

        # --- même chose pour un champ répondu dans l'entretien GÉNÉRAL
        # (mode_entretien="histoire") : partagé avec la campagne par
        # coïncidence, mais hors de son cadre ---
        lieu_general = store.get_or_create_tiers_lieu("user-2", "Lieu Histoire Générale")
        contributeur_general = store.get_or_create_contributeur("user-2", lieu_general.id, Role.AUTRE.value)
        session_general = store.get_or_start_session(lieu_general.id, contributeur_general.id)
        handler_general = CollecteToolHandler(store, lieu_general.id, contributeur_general.id, session_general,
                                               Role.AUTRE, mode_entretien="histoire")
        handler_general.execute("save_answer", {"champ_id": "pays", "valeur": "France"})
        check("réponse donnée en entretien général (hors campagne) : pas 'entamée' pour autant",
              store.get_campagne_ids_entames(lieu_general.id) == set())

        # --- réponse donnée ACTIVEMENT en mode campagne, pour CETTE
        # campagne : doit bien être détectée comme entamée ---
        lieu_actif = store.get_or_create_tiers_lieu("user-3", "Lieu Actif Campagne")
        contributeur_actif = store.get_or_create_contributeur("user-3", lieu_actif.id, Role.AUTRE.value)
        session_actif = store.get_or_start_session(lieu_actif.id, contributeur_actif.id)
        handler_actif = CollecteToolHandler(store, lieu_actif.id, contributeur_actif.id, session_actif,
                                             Role.AUTRE, mode_entretien="campagne", campagne_id=campagne.id)
        handler_actif.execute("save_answer", {"champ_id": "pays", "valeur": "Belgique"})
        check("réponse donnée activement en mode campagne : bien détectée comme entamée",
              store.get_campagne_ids_entames(lieu_actif.id) == {campagne.id})

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
