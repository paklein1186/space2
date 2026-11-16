"""Campagne « Autodiagnostic des tiers-lieux » — reprise conversationnelle du
formulaire Google Forms de recensement des besoins de Trois-Tiers.

Une campagne n'est qu'une liste ordonnée de champs du schéma (voir
CampagnePrioritaire.champ_ids) : toutes les questions du formulaire existent
dans schema.py, celles qui manquaient y ont été ajoutées pour être aussi
disponibles dans l'entretien général. Ce module fixe l'ordre et les textes ;
`python3 -m src.questionnaire.campagne_autodiag` crée la campagne en base
(ou la met à jour si une campagne de même code existe déjà).

Ordre : le pays d'abord (sauté s'il est déjà connu pour ce lieu), car les
choix proposés ensuite en dépendent — statut juridique (ASBL en Belgique,
association loi 1901 en France…), acteurs du territoire, et la question sur
l'appel à projets wallon, posée seulement pour un lieu belge."""

from __future__ import annotations

from .schema import FONCTIONS_PAR_FAMILLE

CODE = "autodiag"
TITRE = "Autodiagnostic des tiers-lieux"

DESCRIPTION = (
    "Un autodiagnostic proposé par Trois-Tiers pour mieux comprendre les enjeux actuels de votre "
    "tiers-lieu (obstacles, freins, interrogations) et vous orienter vers les compétences, outils, "
    "formations et accompagnements qui y répondent.\n"
    "C'est aussi l'occasion de poser un regard structuré sur votre projet, et de contribuer à "
    "identifier des chantiers communs avec d'autres tiers-lieux.\n"
    "Sept thèmes : intention et positionnement, gouvernance et communauté, contexte, modèle "
    "économique, lieu et aménagement, suivi et évaluation, soutiens souhaités. Comptez 30 à 60 "
    "minutes ; vous pouvez répondre brièvement ou en détail, et reprendre plus tard.\n"
    "Pour qui : les porteurs et équipes de tiers-lieux, en Belgique et en France."
)

MESSAGE_CLOTURE = (
    "Merci, votre autodiagnostic est complet. Trois-Tiers s'en servira pour vous proposer des "
    "ressources et des accompagnements adaptés à vos priorités."
)

CHAMP_IDS = [
    # Identification — le pays d'abord : les choix suivants en dépendent.
    "pays",
    "statut_juridique",
    "laureat_appel_rw",
    "date_ouverture",
    "contact",
    # 0. Fonctions du lieu (choix multiples par famille)
    *[champ_id for champ_id, _, _ in FONCTIONS_PAR_FAMILLE],
    "fonctions_autres",
    "stade_developpement",
    # 1. Intention et positionnement
    "raison_etre",
    "besoin_aide_vision",
    "porteurs_motivations",
    "besoin_aide_equipe",
    "vision_5_ans",
    "obstacles_anticipes",
    "besoin_aide_feuille_de_route",
    # 2. Gouvernance et communauté
    "mode_prise_decision",
    "freins_decision",
    "equite_repartition",
    "besoin_aide_gouvernance",
    "parties_prenantes_engagement",
    "participation_usagers",
    "besoin_aide_parties_prenantes",
    "communication_interne",
    "besoin_aide_communication_interne",
    "communication_externe",
    "besoin_aide_communication_externe",
    # 3. Diagnostic et contexte
    "acteurs_mobilises",
    "qualite_partenariats",
    "besoin_aide_partenariats",
    "swot_realise",
    "atouts",
    "menaces",
    "besoin_aide_analyse",
    # 4. Modèle économique et financement
    "sources_financement_fonctionnement",
    "revenus_suffisance_risques",
    "besoin_aide_modele_economique",
    "besoins_financiers_termes",
    "previsionnel_financier_formalise",
    "financement_equipements_collectifs",
    # 5. Lieu et aménagement
    "statut_occupation",
    "besoins_spatiaux",
    "besoin_aide_amenagement",
    # 6. Suivi et évaluation
    "systeme_evaluation",
    "temps_prise_de_recul",
    "besoins_formation_equipe",
    # 7. Soutiens souhaités ces 3 prochaines années
    "types_soutien_souhaites",
    "soutiens_prioritaires",
    "demande_specifique",
]


def creer_ou_mettre_a_jour(store, date_debut: str, date_fin: str):
    """Crée la campagne (ou met à jour celle qui porte déjà le code CODE)."""
    from ..db.store import CampagnePrioritaire

    existante = next((c for c in store.list_campagnes_prioritaires() if c.code == CODE), None)
    campagne = existante or CampagnePrioritaire(titre=TITRE, champ_ids=[], date_debut=date_debut,
                                                 date_fin=date_fin, code=CODE)
    campagne.titre = TITRE
    campagne.champ_ids = list(CHAMP_IDS)
    campagne.description = DESCRIPTION
    campagne.message_cloture = MESSAGE_CLOTURE
    campagne.date_debut = date_debut
    campagne.date_fin = date_fin
    store.save_campagne_prioritaire(campagne)
    return next(c for c in store.list_campagnes_prioritaires() if c.code == CODE)


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    from ..db.factory import get_admin_store

    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--debut", required=True, help="date de début, AAAA-MM-JJ")
    parser.add_argument("--fin", required=True, help="date de fin, AAAA-MM-JJ")
    args = parser.parse_args()
    c = creer_ou_mettre_a_jour(get_admin_store(), f"{args.debut}T00:00:00+00:00", f"{args.fin}T23:59:59+00:00")
    print(f"Campagne « {c.titre} » ({c.code}) : {len(c.champ_ids)} questions, du {c.date_debut} au {c.date_fin}")
