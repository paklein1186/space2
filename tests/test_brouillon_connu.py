"""brouillon_connu (collecte_tools.py) : un champ de campagne prioritaire qui
recoupe une donnée déjà connue (ex. "pitch" ~ description_courte) porte un
brouillon exploitable par l'agent, plutôt que d'être posé à froid — repris
d'abord sur une réponse déjà enregistrée, en repli sur le résumé synthétisé
(lieu_derive.donnees['resume']), absent si ni l'un ni l'autre n'existe. Sans
réseau, sans appel LLM.

Usage : python3 -m tests.test_brouillon_connu
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.db.store import CampagnePrioritaire, LieuDerive
from src.questionnaire.schema import Role


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def _fenetre_active() -> tuple:
    maintenant = datetime.now(timezone.utc)
    return (maintenant - timedelta(days=1)).isoformat(), (maintenant + timedelta(days=30)).isoformat()


def _champ_pitch(section: dict) -> dict:
    return next(f for f in section["fields"] if f["id"] == "pitch")


def main():
    debut, fin = _fenetre_active()

    with tempfile.TemporaryDirectory() as tmp:
        # --- description_courte déjà répondue : priorité sur le résumé ---
        store = SqliteStore(db_path=str(Path(tmp) / "brouillon1.sqlite3"))
        store.save_campagne_prioritaire(CampagnePrioritaire(
            titre="KA122", champ_ids=["pitch"], date_debut=debut, date_fin=fin,
        ))
        lieu = store.get_or_create_tiers_lieu("user-1", "Lieu Avec Description")
        contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.AUTRE.value)
        store.save_answer(lieu.id, contributeur.id, "description_courte", "Un atelier partagé en centre-bourg.")
        store.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu.id,
            donnees={"resume": "Résumé auto-généré, ne devrait pas être utilisé ici."},
            profil_semantique_texte="x", prompt_version="v1", model="m", source_hash="h",
        ))
        session = store.get_or_start_session(lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.AUTRE,
                                      mode_entretien="campagne")
        pitch = _champ_pitch(handler.get_current_section({}))
        check("description_courte déjà répondue -> reprise telle quelle comme brouillon",
              pitch.get("brouillon_connu") == "Un atelier partagé en centre-bourg.")

        # --- pas de description_courte, mais un résumé synthétisé existe ---
        store2 = SqliteStore(db_path=str(Path(tmp) / "brouillon2.sqlite3"))
        store2.save_campagne_prioritaire(CampagnePrioritaire(
            titre="KA122", champ_ids=["pitch"], date_debut=debut, date_fin=fin,
        ))
        lieu2 = store2.get_or_create_tiers_lieu("user-1", "Lieu Avec Resume Seul")
        contributeur2 = store2.get_or_create_contributeur("user-1", lieu2.id, Role.AUTRE.value)
        store2.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu2.id,
            donnees={"resume": "Tiers-lieu nourricier en Wallonie, ancré dans le Pays des 4 Bras."},
            profil_semantique_texte="x", prompt_version="v1", model="m", source_hash="h",
        ))
        session2 = store2.get_or_start_session(lieu2.id, contributeur2.id)
        handler2 = CollecteToolHandler(store2, lieu2.id, contributeur2.id, session2, Role.AUTRE,
                                       mode_entretien="campagne")
        pitch2 = _champ_pitch(handler2.get_current_section({}))
        check("pas de description_courte -> repli sur le résumé synthétisé",
              pitch2.get("brouillon_connu") == "Tiers-lieu nourricier en Wallonie, ancré dans le Pays des 4 Bras.")

        # --- ni l'un ni l'autre : pas de brouillon_connu, pas d'erreur ---
        store3 = SqliteStore(db_path=str(Path(tmp) / "brouillon3.sqlite3"))
        store3.save_campagne_prioritaire(CampagnePrioritaire(
            titre="KA122", champ_ids=["pitch"], date_debut=debut, date_fin=fin,
        ))
        lieu3 = store3.get_or_create_tiers_lieu("user-1", "Lieu Sans Rien")
        contributeur3 = store3.get_or_create_contributeur("user-1", lieu3.id, Role.AUTRE.value)
        session3 = store3.get_or_start_session(lieu3.id, contributeur3.id)
        handler3 = CollecteToolHandler(store3, lieu3.id, contributeur3.id, session3, Role.AUTRE,
                                       mode_entretien="campagne")
        pitch3 = _champ_pitch(handler3.get_current_section({}))
        check("ni description_courte ni résumé -> pas de clé brouillon_connu",
              "brouillon_connu" not in pitch3)

        # --- un champ SANS mapping (ex. pays) ne porte jamais ce champ ---
        store4 = SqliteStore(db_path=str(Path(tmp) / "brouillon4.sqlite3"))
        store4.save_campagne_prioritaire(CampagnePrioritaire(
            titre="Campagne simple", champ_ids=["pays"], date_debut=debut, date_fin=fin,
        ))
        lieu4 = store4.get_or_create_tiers_lieu("user-1", "Lieu Champ Non Mappe")
        contributeur4 = store4.get_or_create_contributeur("user-1", lieu4.id, Role.AUTRE.value)
        store4.save_lieu_derive(LieuDerive(
            tiers_lieu_id=lieu4.id, donnees={"resume": "Peu importe, pays n'est pas mappé."},
            profil_semantique_texte="x", prompt_version="v1", model="m", source_hash="h",
        ))
        session4 = store4.get_or_start_session(lieu4.id, contributeur4.id)
        handler4 = CollecteToolHandler(store4, lieu4.id, contributeur4.id, session4, Role.AUTRE,
                                       mode_entretien="campagne")
        champ_pays = next(f for f in handler4.get_current_section({})["fields"] if f["id"] == "pays")
        check("champ hors mapping (pays) -> jamais de brouillon_connu même si un résumé existe",
              "brouillon_connu" not in champ_pays)

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
