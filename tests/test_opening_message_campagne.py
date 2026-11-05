"""opening_message (collecte_agent.py), mode "campagne" : deux consignes
bien distinctes selon que la campagne a déjà été entamée pour ce lieu ou
non — sans ça, l'agent réintroduisait la campagne depuis le début et
redemandait "voulez-vous participer ?" même après 8 questions déjà
répondues (cas vécu : Agricoeur/KA122). Sans réseau.

Usage : python3 -m tests.test_opening_message_campagne
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_agent import opening_message
from src.db.sqlite_store import SqliteStore


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "x.sqlite3"))
        lieu = store.get_or_create_tiers_lieu("u1", "Lieu Campagne")

        # --- jamais entamée (campagne_progression=None, ou repondus=0) ---
        msg_fraiche = opening_message(
            store, lieu.id, nom_lieu="Lieu Campagne", mode_entretien="campagne",
            campagne_titre="KA122 Mobilité", campagne_progression=None,
        )
        check("jamais entamée : présentation complète, PAS la consigne 'continue'",
              "a choisi de commencer par la campagne prioritaire" in msg_fraiche
              and "NE réintroduis PAS" not in msg_fraiche)

        msg_zero = opening_message(
            store, lieu.id, nom_lieu="Lieu Campagne", mode_entretien="campagne",
            campagne_titre="KA122 Mobilité", campagne_progression={"repondus": 0, "total": 22, "pourcentage": 0},
        )
        check("repondus=0 explicite : même traitement que None (présentation complète)",
              "a choisi de commencer par la campagne prioritaire" in msg_zero
              and "NE réintroduis PAS" not in msg_zero)

        # --- déjà entamée (repondus > 0) : ne jamais repartir de zéro ---
        msg_reprise = opening_message(
            store, lieu.id, nom_lieu="Lieu Campagne", mode_entretien="campagne",
            campagne_titre="KA122 Mobilité", campagne_progression={"repondus": 8, "total": 22, "pourcentage": 36},
        )
        check("déjà entamée : consigne explicite de ne pas réintroduire ni redemander la participation",
              "NE réintroduis PAS" in msg_reprise and "NE redemande PAS" in msg_reprise)
        check("déjà entamée : le compte de progression (8/22) est injecté",
              "8/22" in msg_reprise)
        check("déjà entamée : le titre de la campagne est injecté",
              "KA122 Mobilité" in msg_reprise)
        check("déjà entamée : plus la phrase de présentation complète 'a choisi de commencer'",
              "a choisi de commencer par la campagne prioritaire" not in msg_reprise)

        # --- mode histoire/besoins : jamais affecté par ces paramètres ---
        msg_histoire = opening_message(
            store, lieu.id, nom_lieu="Lieu Campagne", mode_entretien="histoire",
            campagne_titre="KA122 Mobilité", campagne_progression={"repondus": 8, "total": 22, "pourcentage": 36},
        )
        check("mode histoire : campagne_titre/campagne_progression sans effet, jamais mentionnés",
              "campagne prioritaire" not in msg_histoire and "KA122" not in msg_histoire)

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
