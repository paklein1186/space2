"""Vérifie le journal d'historique, le blocage de contributeur et les litiges
(SqliteStore) : un contributeur bloqué disparaît des lectures agrégées sans
que sa donnée brute soit supprimée, et le journal capture chaque écriture.

Usage : python3 -m tests.test_moderation
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.sqlite_store import SqliteStore
from src.db.store import Litige
from src.questionnaire.schema import Role


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "moderation.sqlite3"))

        lieu = store.get_or_create_tiers_lieu("owner", "Lieu Modération")
        fondateur = store.get_or_create_contributeur("user-fondateur", lieu.id, Role.FONDATEUR.value)
        usurpateur = store.get_or_create_contributeur("user-toxique", lieu.id, Role.STEWARD.value)

        store.save_answer(lieu.id, fondateur.id, "milieu", "Rural")
        store.save_answer(lieu.id, usurpateur.id, "description_courte", "Contenu toxique")
        store.save_free_text_note(lieu.id, usurpateur.id, None, "note douteuse")

        # --- Historique : chaque écriture est journalisée, la plus récente en premier
        historique = store.get_historique(lieu.id)
        check("3 entrées dans le journal (2 réponses + 1 note)", len(historique) == 3)
        check("La plus récente (la note) est en tête", historique[0]["type"] == "note")

        # --- Avant blocage : les deux contributeurs alimentent la vue agrégée
        avant = store.get_all_answers_by_contributeur(lieu.id)
        check("2 contributeurs actifs avant blocage", len(avant) == 2)

        # --- Blocage du contributeur toxique
        store.set_contributeur_bloque(usurpateur.id, True, bloque_par="user-fondateur")
        contributeurs = store.list_contributeurs(lieu.id)
        bloque = next(c for c in contributeurs if c.id == usurpateur.id)
        check("Le contributeur est bien marqué bloqué", bloque.bloque is True)
        check("bloque_par enregistré", bloque.bloque_par == "user-fondateur")

        apres = store.get_all_answers_by_contributeur(lieu.id)
        check("Le contributeur bloqué disparaît de la vue agrégée", usurpateur.id not in apres)
        check("Le fondateur reste visible", fondateur.id in apres)

        answers_globales = store.get_answers(lieu.id)
        check("Le champ du contributeur bloqué n'apparaît plus dans get_answers",
              "description_courte" not in answers_globales)
        check("Le champ du fondateur reste résolu normalement",
              answers_globales.get("milieu") == "Rural")

        # La donnée brute elle-même n'est pas supprimée (traçabilité conservée)
        brut = store.get_free_text_notes(lieu.id)
        check("La note du contributeur bloqué existe toujours en base (non supprimée)",
              any(n["texte"] == "note douteuse" for n in brut))

        # --- Déblocage : réapparaît dans les lectures agrégées
        store.set_contributeur_bloque(usurpateur.id, False)
        contributeurs = store.list_contributeurs(lieu.id)
        debloque = next(c for c in contributeurs if c.id == usurpateur.id)
        check("Le contributeur est débloqué", debloque.bloque is False)
        check("bloque_par réinitialisé", debloque.bloque_par is None)
        reapparu = store.get_all_answers_by_contributeur(lieu.id)
        check("Le contributeur débloqué réapparaît dans la vue agrégée", usurpateur.id in reapparu)

        # --- Litiges
        litige = store.save_litige(Litige(
            tiers_lieu_id=lieu.id, description="Usurpation d'identité suspectée",
            signale_par="user-fondateur", contributeur_vise_id=usurpateur.id,
        ))
        check("Le litige est créé avec un id", bool(litige.id))
        check("Statut initial 'ouvert'", litige.statut == "ouvert")

        litiges = store.list_litiges(lieu.id)
        check("1 litige listé pour ce lieu", len(litiges) == 1)

        store.resoudre_litige(litige.id)
        litiges_apres = store.list_litiges(lieu.id)
        check("Le litige est marqué résolu", litiges_apres[0].statut == "resolu")
        check("resolu_le renseigné", litiges_apres[0].resolu_le is not None)

        print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
