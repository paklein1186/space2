"""Clôture d'une campagne prioritaire (collecte_tools.py) : une fois tous ses
champs répondus, un message de clôture (celui de la campagne, ou un repli
générique) est renvoyé une seule fois — jamais répété, et jamais déclenché en
mode "besoins" (qui réutilise le même mécanisme de file prioritaire sans être
une vraie campagne). Sans réseau, sans appel LLM.

Usage : python3 -m tests.test_campagne_cloture
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
        store = SqliteStore(db_path=str(Path(tmp) / "cloture.sqlite3"))
        debut, fin = _fenetre_active()

        # --- campagne avec message de clôture propre ---
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Spaces for Life — KA122 Mobilité", champ_ids=["pays", "region"],
            date_debut=debut, date_fin=fin, message_cloture="Merci, votre dossier KA122 est complet.",
        ))
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Campagne sans message explicite", champ_ids=["pays"], date_debut=debut, date_fin=fin,
        ))
        par_titre = {c.titre: c for c in store.list_campagnes_prioritaires()}
        check("round-trip store : message_cloture renseigné conservé",
              par_titre["Spaces for Life — KA122 Mobilité"].message_cloture
              == "Merci, votre dossier KA122 est complet.")
        check("round-trip store : message_cloture absent -> None, pas une erreur",
              par_titre["Campagne sans message explicite"].message_cloture is None)

        lieu = store.get_or_create_tiers_lieu("user-1", "Lieu Campagne Test")
        contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.AUTRE.value)
        session = store.get_or_start_session(lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.AUTRE,
                                      mode_entretien="campagne")

        section = handler.get_current_section({})
        check("section prioritaire proposée en premier", section["section_id"] == PRIORITY_MODULE_ID)
        champ_ids = {f["id"] for f in section["fields"]}
        check("pays et region tous les deux à répondre", champ_ids == {"pays", "region"})

        r1 = handler.execute("save_answer", {"champ_id": "pays", "valeur": "Belgique"})
        check("après 1 champ sur 2 : pas encore complet", r1["section_complete"] is False)
        check("pas de next_section tant qu'il reste des champs prioritaires", "next_section" not in r1)

        r2 = handler.execute("save_answer", {"champ_id": "region", "valeur": "Namur"})
        check("après le dernier champ : section_complete true", r2["section_complete"] is True)
        check("next_section renvoyé directement (pas de round-trip supplémentaire)", "next_section" in r2)
        cloture = r2["next_section"]
        check("section de clôture : zéro champ", cloture["fields"] == [])
        check("marqueur cloture_campagne présent (plus fiable pour l'agent qu'une inférence sur fields vide)",
              cloture.get("cloture_campagne") is True)
        check("a_dire_maintenant porte le même texte que intro",
              cloture["a_dire_maintenant"] == cloture["intro"])
        check("message de clôture de la campagne repris tel quel", "Merci, votre dossier KA122 est complet." in cloture["intro"])
        check("rappel fixe (base de données / Bibliothèque) toujours ajouté",
              "Bibliothèque" in cloture["intro"] and "ressources" in cloture["intro"])

        section_suivante = handler.get_current_section({})
        check("appel suivant : la clôture n'est plus jamais reproposée",
              section_suivante.get("section_id") != PRIORITY_MODULE_ID
              or "Merci, votre dossier KA122 est complet." not in (section_suivante.get("intro") or ""))

        # --- campagne sans message de clôture propre : repli générique ---
        store2 = SqliteStore(db_path=str(Path(tmp) / "cloture2.sqlite3"))
        store2.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Campagne sans message", champ_ids=["pays"], date_debut=debut, date_fin=fin,
        ))
        lieu2 = store2.get_or_create_tiers_lieu("user-1", "Lieu Sans Message")
        contributeur2 = store2.get_or_create_contributeur("user-1", lieu2.id, Role.AUTRE.value)
        session2 = store2.get_or_start_session(lieu2.id, contributeur2.id)
        handler2 = CollecteToolHandler(store2, lieu2.id, contributeur2.id, session2, Role.AUTRE,
                                       mode_entretien="campagne")
        handler2.get_current_section({})
        r3 = handler2.execute("save_answer", {"champ_id": "pays", "valeur": "France"})
        check("sans message_cloture configuré : repli générique non vide",
              "next_section" in r3 and r3["next_section"]["intro"].startswith("Merci, vous avez répondu"))

        # --- mode "besoins" : même mécanisme de file prioritaire, mais
        #     jamais de message de clôture (pas une vraie campagne) ---
        store3 = SqliteStore(db_path=str(Path(tmp) / "besoins.sqlite3"))
        lieu3 = store3.get_or_create_tiers_lieu("user-1", "Lieu Besoins Test")
        contributeur3 = store3.get_or_create_contributeur("user-1", lieu3.id, Role.AUTRE.value)
        session3 = store3.get_or_start_session(lieu3.id, contributeur3.id)
        handler3 = CollecteToolHandler(store3, lieu3.id, contributeur3.id, session3, Role.AUTRE,
                                       mode_entretien="besoins")
        section3 = handler3.get_current_section({})
        check("mode besoins : section prioritaire aussi proposée en premier",
              section3["section_id"] == PRIORITY_MODULE_ID)
        for f in list(section3["fields"]):
            valeur = ["Autre"] if f["type"] == "multi_choice" else "texte de test"
            r_besoins = handler3.execute("save_answer", {"champ_id": f["id"], "valeur": valeur})
        check("mode besoins : jamais de section de clôture, même épuisé",
              "next_section" not in r_besoins or r_besoins["next_section"]["section_id"] != PRIORITY_MODULE_ID
              or r_besoins["next_section"]["fields"] != [])

        # --- un champ retiré du schéma PENDANT une conversation déjà ouverte
        # (ex. rgpd/image retirés de KA122 en production) ne doit jamais
        # faire croire à tort que la campagne est terminée s'il reste une
        # vraie question active non répondue.
        store4 = SqliteStore(db_path=str(Path(tmp) / "champ_retire.sqlite3"))
        lieu4 = store4.get_or_create_tiers_lieu("user-1", "Lieu Champ Retire Test")
        contributeur4 = store4.get_or_create_contributeur("user-1", lieu4.id, Role.AUTRE.value)
        session4 = store4.get_or_start_session(lieu4.id, contributeur4.id)
        handler4 = CollecteToolHandler(store4, lieu4.id, contributeur4.id, session4, Role.AUTRE,
                                       mode_entretien="campagne")
        # Simule un champ qui existait au démarrage de CETTE conversation
        # mais a depuis été retiré du schéma (get_field() renvoie None).
        handler4._priority_field_ids = ["champ_disparu_du_schema", "pays"]
        handler4._priority_active = True
        section4 = handler4.get_current_section({})
        check("champ retiré du schéma : la vraie question restante est quand même proposée",
              section4["section_id"] == PRIORITY_MODULE_ID
              and any(f["id"] == "pays" for f in section4["fields"]))
        check("champ retiré du schéma : purgé de la liste suivie, jamais reconsidéré",
              "champ_disparu_du_schema" not in handler4._priority_field_ids)

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
