"""opening_message (collecte_agent.py) : signale un lien externe déjà connu
pour le lieu, pour que l'agent ne le redemande pas en ouverture d'entretien
(voir la règle dédiée dans SYSTEM_PROMPT, analyser_lien). Sans réseau.

Usage : python3 -m tests.test_opening_message_lien
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_agent import opening_message
from src.db.sqlite_store import SqliteStore
from src.db.store import LieuDerive


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "x.sqlite3"))

        lieu_sans_rien = store.get_or_create_tiers_lieu("u1", "Lieu Sans Rien")
        msg = opening_message(store, lieu_sans_rien.id, nom_lieu="Lieu Sans Rien")
        check("tout premier échange, sans lien connu : rien à signaler", "lien externe" not in msg.lower())

        lieu_avec_lien = store.get_or_create_tiers_lieu("u1", "Lieu Avec Lien")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu_avec_lien.id, donnees={}, profil_semantique_texte="p",
            prompt_version="v", model="m", source_hash="h"))
        store.update_lieu_derive_liens(lieu_avec_lien.id, lien_externe="https://commonshub.brussels", photo_url=None)
        msg2 = opening_message(store, lieu_avec_lien.id, nom_lieu="Lieu Avec Lien")
        check("lien externe déjà connu (sans synthèse) : signalé, URL incluse, consigne de ne pas redemander",
              "https://commonshub.brussels" in msg2 and "ne redemande pas de lien" in msg2)

        lieu_complet = store.get_or_create_tiers_lieu("u1", "Lieu Complet")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu_complet.id, donnees={"resume": "Un tiers-lieu bien documenté."},
            profil_semantique_texte="p", prompt_version="v", model="m", source_hash="h"))
        store.update_lieu_derive_liens(lieu_complet.id, lien_externe="https://exemple.org", photo_url=None)
        msg3 = opening_message(store, lieu_complet.id, nom_lieu="Lieu Complet")
        check("lien connu ET synthèse existante (reprise) : les deux informations coexistent",
              "https://exemple.org" in msg3 and "Un tiers-lieu bien documenté." in msg3)

        lieu_synthese_sans_lien = store.get_or_create_tiers_lieu("u1", "Lieu Synthese Sans Lien")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu_synthese_sans_lien.id, donnees={"resume": "Résumé."},
            profil_semantique_texte="p", prompt_version="v", model="m", source_hash="h"))
        msg4 = opening_message(store, lieu_synthese_sans_lien.id, nom_lieu="Lieu Synthese Sans Lien")
        check("synthèse existante mais AUCUN lien connu : rien signalé (l'agent peut demander)",
              "lien externe" not in msg4.lower())
    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
