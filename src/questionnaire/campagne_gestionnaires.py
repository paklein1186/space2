"""Campagnes « Enquête gestionnaires » — reprise conversationnelle du
questionnaire gestionnaires (version du 11/08/2026, fichier « Questionnaire
gestionnaires_v11082026_ELA.docx »), en deux versions :
coworkings et tiers-lieux, plus le bloc « impact économique et emploi »
proposé en annexe du document.

Une campagne n'est qu'une liste ordonnée de champs du schéma. Les questions
déjà présentes dans l'entretien général (localisation, statut d'occupation,
modes de déplacement, provenance, rayonnement…) sont réutilisées telles
quelles : un lieu qui y a déjà répondu ne les revoit pas. Les grilles
détaillées (une question par ligne : statuts des usagers, raisons de venue…)
vivent dans le module hors parcours `module_enquetes` de schema.py.

Différences entre les deux versions : lignes propres à chacune dans l'offre
du lieu (options communes, voir services_proposes), les statuts (riverains),
les raisons de venue, et la fréquentation (par semaine pour un coworking, par
mois pour un tiers-lieu).

`python3 -m src.questionnaire.campagne_gestionnaires --debut AAAA-MM-JJ --fin
AAAA-MM-JJ` crée les deux campagnes en base (ou les met à jour, par code)."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import (
    EVOLUTION_PROFIL_3_ANS, EVOLUTION_PROVENANCE_3_ANS, MOTIFS_VENUE, PARTS_FREQUENCE_VENUE,
    STATUTS_USAGERS_PARTS,
)


def _ids(lignes) -> list:
    return [champ_id for champ_id, _ in lignes]


MOTIFS_COMMUNS = _ids(MOTIFS_VENUE[:11])
MOTIFS_COWORKING = MOTIFS_COMMUNS + ["motif_animations_extraprofessionnelles", "motif_formations_professionnelles"]
MOTIFS_TIERS_LIEU = MOTIFS_COMMUNS + ["motif_evenements_recreatifs", "motif_ateliers_formations",
                                      "motif_acheter_produits", "motif_boire_manger"]
STATUTS_COWORKING = [c for c in _ids(STATUTS_USAGERS_PARTS) if c != "part_statut_riverain"]
STATUTS_TIERS_LIEU = _ids(STATUTS_USAGERS_PARTS)

BLOC_ECONOMIE_EMPLOI = [
    "chiffre_affaires_annuel",
    "resultat_annuel",
    "ca_activites_hebergees",
    "resultat_activites_hebergees",
    "ca_resultat_par_activite",
    "etp_geres",
    "metiers_tiers_lieu",
    "metiers_tiers_lieu_autre",
    "nombre_structures_hebergees",
    "etp_activites_hebergees",
    "nombre_benevoles_annee",
    "nombre_adherents_actuels",
]


def _champ_ids(statuts: list, motifs: list, frequentation: str, evolution_frequentation: str) -> list:
    return [
        # Le lieu
        "nom_lieu",
        "adresse",
        "avantages_localisation",
        "inconvenients_localisation",
        "statut_occupation",
        "lance_seul",
        "modalite_lancement_collectif",
        "lieu_inoccupe_avant",
        "ancienne_occupation",
        "initiateurs_projet",
        "services_proposes",
        "nombre_entreprises_domiciliees",
        "nombre_associations_accueillies",
        # Les usagers : fréquence, mobilité, provenance
        *_ids(PARTS_FREQUENCE_VENUE),
        "frequence_usagers_commentaire",
        "usagers_mode_voiture",
        "usagers_mode_velo",
        "usagers_mode_pied",
        "usagers_mode_transport_commun",
        "usagers_mode_autre",
        "provenance_usagers_commune",
        "provenance_usagers_limitrophe",
        "provenance_usagers_plus_loin",
        # Avant toute question d'évolution : sans objet si le lieu est récent.
        "lieu_existait_3_ans",
        *_ids(EVOLUTION_PROVENANCE_3_ANS),
        "rayonnement_large",
        "rayonnement_exemples",
        # Profil des usagers
        *statuts,
        "part_statut_autre",
        "domaines_professionnels_top3",
        *_ids(EVOLUTION_PROFIL_3_ANS),
        *motifs,
        "motif_autre",
        # Ancrage local
        "partenariats_acteurs_locaux",
        "partenariats_acteurs_locaux_detail",
        "usagers_partenariats_evenements",
        "usagers_partenariats_detail",
        "usagers_activites_annexes_quartier",
        "usagers_activites_annexes_detail",
        # Fréquentation
        frequentation,
        evolution_frequentation,
        # Impact économique et emploi (annexe du document)
        *BLOC_ECONOMIE_EMPLOI,
        # Question de clôture du questionnaire
        "interet_table_ronde_gestionnaires",
    ]


@dataclass(frozen=True)
class DefinitionCampagne:
    code: str
    titre: str
    description: str
    message_cloture: str
    champ_ids: tuple


_DESCRIPTION_COMMUNE = (
    "Cette enquête auprès des gestionnaires vise à mieux connaître {objet} : leur "
    "localisation, leurs usagers (fréquence de venue, mobilité, provenance, profils, raisons de venue), "
    "leur ancrage local et leur impact économique et sur l'emploi.\n"
    "Comptez 30 à 45 minutes ; la plupart des questions demandent une estimation, pas un chiffre exact. "
    "Vous pouvez répondre brièvement et reprendre plus tard.\n"
    "Pour qui : les gestionnaires {cible}."
)

_MESSAGE_CLOTURE = (
    "Merci, votre questionnaire est complet. Vos réponses alimenteront l'analyse des {objet} et pourront "
    "nourrir une table ronde entre gestionnaires."
)

COWORKINGS = DefinitionCampagne(
    code="gestionnaires-coworkings",
    titre="Enquête gestionnaires — coworkings",
    description=_DESCRIPTION_COMMUNE.format(objet="les coworkings", cible="de coworkings"),
    message_cloture=_MESSAGE_CLOTURE.format(objet="coworkings"),
    champ_ids=tuple(_champ_ids(STATUTS_COWORKING, MOTIFS_COWORKING,
                               "frequentation_semaine_type", "evolution_frequentation_semaine")),
)

TIERS_LIEUX = DefinitionCampagne(
    # Code d'origine conservé : le lien ?campagne=gestionnaires-tiers-lieux-ruraux
    # a déjà été diffusé avant que l'enquête ne s'adresse à tous les tiers-lieux.
    code="gestionnaires-tiers-lieux-ruraux",
    titre="Enquête gestionnaires — tiers-lieux",
    description=_DESCRIPTION_COMMUNE.format(objet="les tiers-lieux", cible="de tiers-lieux"),
    message_cloture=_MESSAGE_CLOTURE.format(objet="tiers-lieux"),
    champ_ids=tuple(_champ_ids(STATUTS_TIERS_LIEU, MOTIFS_TIERS_LIEU,
                               "frequentation_mois_type", "evolution_frequentation_mois")),
)

CAMPAGNES = (COWORKINGS, TIERS_LIEUX)

# Données souvent déjà connues (imports : nom et adresse pour presque tous
# les lieux) qu'on fait valider plutôt que sauter : sans ça, une adresse
# importée incomplète ou un statut d'occupation daté passerait tel quel
# dans les résultats de l'enquête. Voir CollecteToolHandler.
CHAMPS_A_CONFIRMER = ("nom_lieu", "adresse", "statut_occupation", "etp_geres")
CHAMPS_A_CONFIRMER_PAR_CODE = {d.code: CHAMPS_A_CONFIRMER for d in CAMPAGNES}


def creer_ou_mettre_a_jour(store, definition: DefinitionCampagne, date_debut: str, date_fin: str):
    """Crée la campagne (ou met à jour celle qui porte déjà ce code)."""
    from ..db.store import CampagnePrioritaire

    existante = next((c for c in store.list_campagnes_prioritaires() if c.code == definition.code), None)
    campagne = existante or CampagnePrioritaire(titre=definition.titre, champ_ids=[], date_debut=date_debut,
                                                 date_fin=date_fin, code=definition.code)
    campagne.titre = definition.titre
    campagne.champ_ids = list(definition.champ_ids)
    campagne.description = definition.description
    campagne.message_cloture = definition.message_cloture
    campagne.date_debut = date_debut
    campagne.date_fin = date_fin
    store.save_campagne_prioritaire(campagne)
    return next(c for c in store.list_campagnes_prioritaires() if c.code == definition.code)


if __name__ == "__main__":
    import argparse

    from dotenv import load_dotenv

    from ..db.factory import get_admin_store

    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--debut", required=True, help="date de début, AAAA-MM-JJ")
    parser.add_argument("--fin", required=True, help="date de fin, AAAA-MM-JJ")
    args = parser.parse_args()
    store = get_admin_store()
    for definition in CAMPAGNES:
        c = creer_ou_mettre_a_jour(store, definition, f"{args.debut}T00:00:00+00:00", f"{args.fin}T23:59:59+00:00")
        print(f"Campagne « {c.titre} » ({c.code}) : {len(c.champ_ids)} questions, du {c.date_debut} au {c.date_fin}")
