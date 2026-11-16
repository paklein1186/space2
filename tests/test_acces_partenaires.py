"""Accès partenaires à une campagne (page ?partenaire=<code>) : seuls les emails
inscrits au préalable par un admin, valides, pour CETTE campagne, y ont
accès ; les réponses confidentielles ne remontent jamais dans la vue
partenaire. Sans réseau, sans appel LLM.

Usage : python3 -m tests.test_acces_partenaires
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.acces_partenaires import campagne_demandee, campagnes_visibles, parser_emails
from src.db.sqlite_store import SqliteStore
from src.db.store import CampagnePrioritaire
from src.questionnaire.schema import Role


def check(label, condition):
    print(f"[{'OK ' if condition else 'FAIL'}] {label}")
    assert condition, label


def main():
    valides, invalides = parser_emails(" Anne.Dupont@Region.be\nanne.dupont@region.be, bob@ville.fr;pas-un-email\nx@y")
    check("emails normalisés, dédoublonnés, triés", valides == ["anne.dupont@region.be", "bob@ville.fr"])
    check("emails invalides signalés tels que saisis", invalides == ["pas-un-email", "x@y"])
    check("saisie vide : rien", parser_emails("") == ([], []))

    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "partenaires.sqlite3"))
        for titre, code in (("KA122", "ka122"), ("Autodiagnostic", "autodiag")):
            store.save_campagne_prioritaire(CampagnePrioritaire(
                titre=titre, code=code, champ_ids=["pays", "pitch"],
                date_debut="2026-01-01T00:00:00+00:00", date_fin="2030-12-31T23:59:59+00:00",
            ))
        par_code = {c.code: c for c in store.list_campagnes_prioritaires()}
        ka, autodiag = par_code["ka122"], par_code["autodiag"]

        store.set_acces_partenaires(ka.id, ["Anne.Dupont@Region.be", "bob@ville.fr"])
        check("liste enregistrée en minuscules", store.list_acces_partenaires(ka.id)
              == ["anne.dupont@region.be", "bob@ville.fr"])

        vues = campagnes_visibles(store, "ANNE.DUPONT@region.be", est_admin=False)
        check("partenaire inscrit : voit uniquement SA campagne", [c.code for c in vues] == ["ka122"])
        check("lien vers sa campagne résolu", campagne_demandee(vues, "ka122").id == ka.id)
        check("lien vers une autre campagne : refusé", campagne_demandee(vues, "autodiag") is None)
        check("lien par uuid d'une autre campagne : refusé", campagne_demandee(vues, autodiag.id) is None)
        check("email non inscrit : aucune campagne", campagnes_visibles(store, "intrus@ville.fr", False) == [])
        check("sans email vérifié : aucune campagne", campagnes_visibles(store, None, False) == [])
        check("admin : toutes les campagnes", len(campagnes_visibles(store, "admin@space2", True)) == 2)

        store.set_acces_partenaires(ka.id, ["bob@ville.fr"])
        check("retrait d'un email : accès perdu aussitôt",
              campagnes_visibles(store, "anne.dupont@region.be", False) == [])

        store.delete_campagne_prioritaire(ka.id)
        check("suppression de la campagne : accès supprimés avec",
              store.campagne_ids_pour_partenaire("bob@ville.fr") == [])

        # Réponses confidentielles : jamais dans la vue partenaire.
        lieu = store.get_or_create_tiers_lieu("user-1", "Lieu Partenaire Test")
        contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.FONDATEUR.value)
        store.save_answer(lieu.id, contributeur.id, "pays", "Belgique")
        store.save_answer(lieu.id, contributeur.id, "pitch", "Secret", confidentiel=True)
        tout = {r["champ_id"] for r in store.get_reponses_pour_champs(["pays", "pitch"])}
        public = {r["champ_id"] for r in store.get_reponses_pour_champs(["pays", "pitch"],
                                                                           exclure_confidentiel=True)}
        check("vue admin : réponse confidentielle incluse", tout == {"pays", "pitch"})
        check("vue partenaire : réponse confidentielle écartée", public == {"pays"})

        # Répondants d'une campagne : uniquement ceux qui ont répondu DANS
        # cette campagne, pas ceux qui ont juste des champs en commun.
        autre = store.get_or_create_contributeur("user-2", lieu.id, Role.EQUIPE.value)
        store.save_answer(lieu.id, autre.id, "pitch", "En campagne", campagne_id=autodiag.id)
        check("répondant de la campagne : celui qui a répondu en mode campagne",
              store.get_repondants_campagne(autodiag.id) == {(lieu.id, autre.id)})
        check("champs communs remplis hors campagne : pas compté comme répondant",
              (lieu.id, contributeur.id) not in store.get_repondants_campagne(autodiag.id))

    print("Tous les tests passent.")


if __name__ == "__main__":
    main()
