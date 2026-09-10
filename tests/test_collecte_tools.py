"""Vérifie la mécanique de session/progression du CollecteToolHandler sans
appeler l'API Claude (utile pour valider la logique avant de brancher l'agent
conversationnel). Utilise SqliteStore sur un fichier temporaire."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.collecte_tools import CollecteToolHandler
from src.db.sqlite_store import SqliteStore
from src.questionnaire.schema import Role


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteStore(db_path=str(Path(tmp) / "test.sqlite3"))

        lieu = store.get_or_create_tiers_lieu("user-1", "Le Hangar Test")
        contributeur = store.get_or_create_contributeur("user-1", lieu.id, Role.FONDATEUR.value)
        session = store.get_or_start_session(lieu.id, contributeur.id)
        handler = CollecteToolHandler(store, lieu.id, contributeur.id, session, Role.FONDATEUR)

        section = handler.get_current_section({})
        check("Première section = localisation_identite", section["section_id"] == "localisation_identite")
        field_ids = {f["id"] for f in section["fields"]}
        check("Le champ 'pays' est bien proposé en premier lot", "pays" in field_ids)

        # Répond aux champs requis de la section pour la faire avancer
        for f in section["fields"]:
            if f["id"] == "nom_lieu":
                handler.execute("save_answer", {"champ_id": "nom_lieu", "valeur": "Le Hangar Test"})
            elif f["id"] == "pays":
                r = handler.execute("save_answer", {"champ_id": "pays", "valeur": "Belgique"})
            elif f["id"] == "adresse":
                handler.execute("save_answer", {"champ_id": "adresse", "valeur": "Rue Test 1, Namur"})
            elif f["id"] == "milieu":
                r_final = handler.execute("save_answer", {"champ_id": "milieu", "valeur": "Rural"})

        check("La section avance après les champs requis", "next_section" in r_final)
        next_section_id = r_final["next_section"]["section_id"]
        check("Section suivante = acteurs_origine", next_section_id == "acteurs_origine")

        # Simule le reste rapidement en sautant au statut juridique pour tester la localisation belge
        r = handler.execute("save_answer", {"champ_id": "statut_juridique", "valeur": "ASBL"})
        options_next = None
        # Passe par activites -> vérifie que la section alimentaire est bien proposée après avoir coché l'item
        section = handler.get_current_section({})
        while section["section_id"] != "activites":
            for f in section["fields"]:
                if f["type"] == "text":
                    handler.execute("save_answer", {"champ_id": f["id"], "valeur": "test"})
            section = handler.get_current_section({})
            if section["section_id"] == "acteurs_origine":
                handler.execute("save_answer", {"champ_id": "initie_par", "valeur": "Un collectif citoyen"})
                section = handler.get_current_section({})

        r = handler.execute("save_answer", {
            "champ_id": "activites_principales",
            "valeur": ["Activités liées à l'alimentation (production, transformation, distribution)"],
        })
        check("La section alimentaire est proposée juste après",
              r.get("next_section", {}).get("section_id") == "activites_alimentaires")

        # Vérifie qu'un partenaire externe ne voit jamais les champs RH internes
        contributeur_partenaire = store.get_or_create_contributeur("user-2", lieu.id, Role.PARTENAIRE.value)
        session_p = store.get_or_start_session(lieu.id, contributeur_partenaire.id)
        handler_p = CollecteToolHandler(store, lieu.id, contributeur_partenaire.id, session_p, Role.PARTENAIRE)
        # Force la position sur la section RH pour le test : comme tous ses champs
        # sont réservés à fondateur/équipe/steward, elle est entièrement inactive
        # pour un partenaire -> get_current_section doit l'enjamber automatiquement
        # plutôt que de renvoyer une section sans aucun champ à traiter.
        handler_p._module_id = "socle"
        handler_p._section_id = "ressources_humaines"
        section_rh = handler_p.get_current_section({})
        champs_rh_internes = {"etp_geres", "metiers_exerces", "part_femmes_equipe",
                               "organisme_formation_lien", "qvt_equipe"}
        check("Le partenaire est avancé au-delà de la section RH, entièrement inactive pour son rôle",
              section_rh["section_id"] != "ressources_humaines")
        check("Aucun champ RH interne ne fuite dans la section suivante",
              not (champs_rh_internes & {f["id"] for f in section_rh["fields"]}))

        # --- Reprise de session interrompue : un nouveau handler reconstruit à partir
        # de la session persistée doit repartir exactement où le précédent s'est arrêté.
        position_avant = (handler._module_id, handler._section_id, set(handler._completed_section_ids))
        session_reloaded = store.get_or_start_session(lieu.id, contributeur.id)
        handler_repris = CollecteToolHandler(store, lieu.id, contributeur.id, session_reloaded, Role.FONDATEUR)
        position_apres = (handler_repris._module_id, handler_repris._section_id, set(handler_repris._completed_section_ids))
        check("La session reprise repart exactement où elle s'est arrêtée", position_avant == position_apres)

        print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
