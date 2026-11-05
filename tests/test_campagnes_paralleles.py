"""Deux campagnes prioritaires actives en même temps (collecte_tools.py) :
sans campagne_id, leurs champs/intros se fusionnent (comportement historique,
une seule campagne à la fois dans les faits) ; avec campagne_id (choix
explicite du répondant, voir app.py), CollecteToolHandler se restreint à
CETTE seule campagne — champs, intro, et message de clôture. Sans réseau,
sans appel LLM.

Usage : python3 -m tests.test_campagnes_paralleles
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


def _fenetre_active() -> tuple:
    maintenant = datetime.now(timezone.utc)
    return (maintenant - timedelta(days=1)).isoformat(), (maintenant + timedelta(days=30)).isoformat()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "paralleles.sqlite3"))
        debut, fin = _fenetre_active()

        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="KA122 Mobilité", champ_ids=["pays", "region"], date_debut=debut, date_fin=fin,
            message_cloture="Merci, dossier KA122 complet.", code="ka122",
        ))
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Recensement Fablabs", champ_ids=["adresse"], date_debut=debut, date_fin=fin,
            message_cloture="Merci, recensement Fablabs complet.", code="fablabs",
        ))
        campagnes = {c.titre: c for c in store.list_campagnes_prioritaires()}
        check("round-trip : code conservé", campagnes["KA122 Mobilité"].code == "ka122")
        check("round-trip : code conservé (2e campagne)", campagnes["Recensement Fablabs"].code == "fablabs")

        lieu = store.get_or_create_tiers_lieu("user-1", "Lieu Parallele")
        contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.AUTRE.value)

        # --- sans campagne_id : comportement historique, fusion des deux ---
        session1 = store.get_or_start_session(lieu.id, contributeur.id)
        handler1 = CollecteToolHandler(store, lieu.id, contributeur.id, session1, Role.AUTRE,
                                       mode_entretien="campagne")
        section1 = handler1.get_current_section({})
        check("sans campagne_id : champs des deux campagnes fusionnés",
              {f["id"] for f in section1["fields"]} == {"pays", "region", "adresse"})
        check("sans campagne_id : intro mentionne les deux campagnes",
              "KA122 Mobilité" in section1["intro"] and "Recensement Fablabs" in section1["intro"])

        # --- avec campagne_id : restreint à CETTE campagne seule ---
        lieu2 = store.get_or_create_tiers_lieu("user-1", "Lieu Parallele 2")
        contributeur2 = store.get_or_create_contributeur("user-1", lieu2.id, Role.AUTRE.value)
        session2 = store.get_or_start_session(lieu2.id, contributeur2.id)
        handler2 = CollecteToolHandler(store, lieu2.id, contributeur2.id, session2, Role.AUTRE,
                                       mode_entretien="campagne", campagne_id=campagnes["KA122 Mobilité"].id)
        section2 = handler2.get_current_section({})
        check("avec campagne_id=KA122 : seulement ses champs à elle",
              {f["id"] for f in section2["fields"]} == {"pays", "region"})
        check("avec campagne_id=KA122 : intro ne mentionne QUE cette campagne",
              "KA122 Mobilité" in section2["intro"] and "Recensement Fablabs" not in section2["intro"])

        # Répondre tous les champs de CETTE campagne -> clôture avec SON
        # message à elle, jamais celui de l'autre campagne active.
        handler2.execute("save_answer", {"champ_id": "pays", "valeur": "Belgique"})
        r = handler2.execute("save_answer", {"champ_id": "region", "valeur": "Namur"})
        check("clôture déclenchée dès que CETTE campagne (pas l'autre) est complète",
              r["section_complete"] is True and "next_section" in r)
        cloture = r["next_section"]
        check("message de clôture : celui de KA122, jamais celui de Fablabs",
              "Merci, dossier KA122 complet." in cloture["intro"]
              and "Fablabs" not in cloture["intro"])

        # --- la 3e campagne (Fablabs), elle, reste entièrement intacte ---
        lieu3 = store.get_or_create_tiers_lieu("user-1", "Lieu Parallele 3")
        contributeur3 = store.get_or_create_contributeur("user-1", lieu3.id, Role.AUTRE.value)
        session3 = store.get_or_start_session(lieu3.id, contributeur3.id)
        handler3 = CollecteToolHandler(store, lieu3.id, contributeur3.id, session3, Role.AUTRE,
                                       mode_entretien="campagne", campagne_id=campagnes["Recensement Fablabs"].id)
        section3 = handler3.get_current_section({})
        check("avec campagne_id=Fablabs : seulement son champ à elle (adresse)",
              {f["id"] for f in section3["fields"]} == {"adresse"})

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
