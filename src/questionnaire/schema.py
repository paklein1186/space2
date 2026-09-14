"""Schéma du questionnaire conditionnel pour les tiers-lieux.

Ce module ne contient aucune logique d'exécution : il déclare la structure
(modules > sections > champs) que `resolver.py` interprète pour déterminer,
à un instant donné, quels champs doivent être proposés à un répondant donné
(selon les réponses déjà données, le pays du lieu et le rôle du répondant).

Le contenu ci-dessous est une reformulation et une extension des trois
sources fournies par l'utilisateur (recensement France Tiers-Lieux, fiche
"Mesurer l'impact", auto-diagnostic Trois-Tiers) — pas une reproduction
littérale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Union


class Role(str, Enum):
    FONDATEUR = "fondateur"
    EQUIPE = "equipe"
    PARTENAIRE = "partenaire"
    USAGER = "usager"
    STEWARD = "steward"  # suit et continue à nourrir un lieu dans la durée
    AUTRE = "autre"


# Rôles pouvant voir/répondre aux champs sensibles (finances, RH détaillée).
# Le steward a le même accès large que l'équipe : il reprend le lieu en main
# et a besoin du contexte complet pour continuer à l'enrichir utilement.
ROLES_INTERNES = [Role.FONDATEUR, Role.EQUIPE, Role.STEWARD]
# Rôles pouvant voir/répondre à peu près à tout le reste.
TOUS_ROLES = [Role.FONDATEUR, Role.EQUIPE, Role.PARTENAIRE, Role.USAGER, Role.STEWARD, Role.AUTRE]

# Catégories de classification d'un lieu (attribuées par l'enrichissement LLM,
# affichées/filtrables dans l'Annuaire) — source unique partagée par
# `agent.enrichissement` et `annuaire`/`app` pour éviter toute divergence.
CATEGORIES_POSSIBLES = ["Alimentaire", "Culturel", "Éducation", "Santé"]


class FieldType(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    SINGLE_CHOICE = "single_choice"
    MULTI_CHOICE = "multi_choice"
    SCALE_1_5 = "scale_1_5"


Operator = str  # "eq" | "in" | "contains" | "truthy" | "ne"


@dataclass(frozen=True)
class Condition:
    """Un champ ou une section n'est actif que si cette condition est vraie."""

    field_id: str
    operator: Operator
    value: object = None

    def evaluate(self, answers: dict) -> bool:
        current = answers.get(self.field_id)
        if self.operator == "truthy":
            return bool(current)
        if current is None:
            return False
        if self.operator == "eq":
            return current == self.value
        if self.operator == "ne":
            return current != self.value
        if self.operator == "in":
            return current in self.value
        if self.operator == "contains":
            # `current` est une liste (multi_choice) qui doit contenir `value`
            return isinstance(current, (list, tuple, set)) and self.value in current
        raise ValueError(f"Opérateur de condition inconnu: {self.operator}")


# Options d'un champ : soit une liste générique, soit un dictionnaire
# localisé par code pays ISO (+ "default" obligatoire en repli).
Options = Union[list, dict]


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    type: FieldType
    options: Optional[Options] = None
    condition: Optional[Condition] = None
    roles: Optional[list] = None  # None = tous les rôles (TOUS_ROLES)
    required: bool = False
    confidential_default: bool = False
    help_text: Optional[str] = None
    max_choices: Optional[int] = None  # pour les multi_choice bornés (ex: "max 4 valeurs")

    def allowed_for(self, role: Role) -> bool:
        return role in (self.roles or TOUS_ROLES)

    def resolved_options(self, country_code: Optional[str]) -> Optional[list]:
        if self.options is None:
            return None
        if isinstance(self.options, list):
            return self.options
        # dict localisé
        if country_code and country_code in self.options:
            return self.options[country_code]
        return self.options.get("default", [])


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    fields: list  # list[Field]
    condition: Optional[Condition] = None
    intro: Optional[str] = None


@dataclass(frozen=True)
class Module:
    id: str
    title: str
    sections: list  # list[Section]
    optional: bool = False


# ---------------------------------------------------------------------------
# Listes d'options localisées réutilisées à plusieurs endroits
# ---------------------------------------------------------------------------

STATUT_JURIDIQUE = {
    "default": [
        "Association / organisation à but non lucratif",
        "Coopérative",
        "Collectif citoyen informel",
        "Entreprise privée (SARL, SAS ou équivalent)",
        "Établissement public ou parapublic",
        "Autre",
    ],
    "FR": [
        "Association loi 1901",
        "SCIC",
        "SCOP",
        "Collectif citoyen informel",
        "SARL / SAS / SA",
        "Établissement scolaire, universitaire ou EPST",
        "Collectivité territoriale",
        "Autre",
    ],
    "BE": [
        "ASBL",
        "Coopérative (SC / SCRL)",
        "Collectif citoyen informel",
        "SRL / SA",
        "Établissement scolaire ou universitaire",
        "Pouvoir public local (commune, CPAS, Région)",
        "Autre",
    ],
}

ORGANISME_INSERTION_FORMATION = {
    "default": ["Organisme public de l'emploi", "Organisme de formation agréé", "Aucun", "Autre"],
    "FR": ["Pôle emploi / France Travail", "Organisme de formation (Qualiopi ou non)", "Mission locale", "Aucun", "Autre"],
    "BE": ["Forem (Wallonie) / Actiris (Bruxelles) / VDAB (Flandre)", "Organisme de formation agréé Région", "CPAS", "Aucun", "Autre"],
}

SUBVENTIONNEURS_PUBLICS = {
    "default": ["Union / organisation supranationale", "État national", "Région", "Collectivité locale", "Aucun", "Autre"],
    "FR": ["Europe", "État (ANCT, DSIL, DETR...)", "Région", "Département", "Commune / intercommunalité", "Aucun", "Autre"],
    "BE": ["Europe", "Fédéral", "Région (wallonne, flamande ou Bruxelles-Capitale)", "Province", "Commune", "Aucun", "Autre"],
}

ACTEURS_TERRITORIAUX = {
    "default": [
        "Commune / municipalité",
        "Intercommunalité / structure supra-communale",
        "Région",
        "Chambre de commerce ou d'artisanat",
        "Université, haute école ou centre de recherche",
        "École, collège ou lycée",
        "Structure d'insertion professionnelle",
        "Structure médico-sociale ou de santé",
        "Structure culturelle ou artistique",
        "Organisme de formation",
        "Autre tiers-lieu",
        "Chambre d'agriculture / coopérative agricole ou groupe d'action locale",
        "Opérateur de mobilité / transport public",
        "Coopérative citoyenne d'énergie renouvelable",
        "Bailleur social",
        "Acteur de la réinsertion judiciaire",
        "Club ou fédération sportive locale",
        "Association de diaspora ou d'accueil des primo-arrivants",
        "Média local indépendant",
        "Université populaire / éducation permanente",
        "Conseil citoyen ou de quartier",
        "Groupement d'employeurs territorial",
        "Bibliothèque ou médiathèque publique",
        "Office de tourisme / agence de développement territorial",
        "Fournisseur d'accès numérique (lutte contre la fracture numérique)",
        "Centre d'action sociale (CCAS/CPAS)",
        "Aucun",
        "Autre",
    ],
}

DIFFICULTES_SOCIALES = [
    "Précarité / pauvreté",
    "Inégalités de genre",
    "Handicap",
    "Isolement générationnel",
    "Discrimination raciale",
    "Immigration / accueil des primo-arrivants",
    "Parentalité / famille",
    "Aucune",
    "Autre",
]

TRANCHES_AGE = [
    "Moins de 15 ans",
    "15 à 24 ans",
    "25 à 44 ans",
    "45 à 64 ans",
    "65 ans et plus",
    "Je ne sais pas",
]

# Bande d'intensité réutilisée pour les questions de répartition (mode de
# déplacement, provenance des usagers...) — reprend l'échelle du questionnaire
# gestionnaires ULiège plutôt qu'un pourcentage exact, plus réaliste à donner
# à l'oral dans un entretien conversationnel qu'un chiffre précis.
BANDE_INTENSITE = [
    "Nul (0%)", "Limité (< 25%)", "Peu élevé (25 à 50%)", "Assez élevé (50 à 75%)", "Très élevé (> 75%)",
]


# ---------------------------------------------------------------------------
# Module 1 — Socle (obligatoire)
# ---------------------------------------------------------------------------

section_localisation_identite = Section(
    id="localisation_identite",
    title="Localisation et identité du lieu",
    intro="Pour commencer, quelques repères sur le lieu et sur vous.",
    fields=[
        Field("nom_lieu", "Nom du tiers-lieu", FieldType.TEXT, required=True),
        Field("pays", "Pays où se situe le lieu", FieldType.SINGLE_CHOICE,
              options=["France", "Belgique", "Autre"], required=True),
        Field("region", "Région ou province d'implantation", FieldType.TEXT),
        Field("adresse", "Adresse ou commune d'implantation", FieldType.TEXT, required=True),
        Field("latitude", "Latitude (si connue, sinon laissez de côté)", FieldType.NUMBER),
        Field("longitude", "Longitude (si connue, sinon laissez de côté)", FieldType.NUMBER),
        Field("milieu", "Le lieu se situe plutôt en milieu...", FieldType.SINGLE_CHOICE,
              options=["Rural", "Semi-rural", "Urbain"], required=True),
        Field("date_ouverture", "Date (ou année) d'ouverture du lieu", FieldType.DATE),
        Field("description_courte", "En une phrase, comment décririez-vous ce lieu ?", FieldType.TEXTAREA),
        Field("avantages_localisation", "Quels avantages trouvez-vous à cette localisation ?", FieldType.TEXTAREA),
        Field("inconvenients_localisation", "Quels inconvénients trouvez-vous à cette localisation ?", FieldType.TEXTAREA),
    ],
)

section_acteurs_origine = Section(
    id="acteurs_origine",
    title="Origine du projet et valeurs",
    fields=[
        Field("initie_par", "Ce lieu a été lancé à l'initiative de...", FieldType.SINGLE_CHOICE,
              options=["Un collectif citoyen", "Une association existante", "Un entrepreneur ou une entreprise",
                       "Une université ou un établissement scolaire", "Une collectivité publique",
                       "Je ne sais pas", "Autre"]),
        Field("statut_juridique", "Statut juridique de la structure porteuse", FieldType.SINGLE_CHOICE,
              options=STATUT_JURIDIQUE, roles=ROLES_INTERNES),
        Field("valeurs", "Quelles valeurs le lieu cherche-t-il à incarner ? (jusqu'à 4)", FieldType.MULTI_CHOICE,
              options=["Accueil", "Apprentissage", "Convivialité", "Coopération", "Créativité", "Durabilité",
                       "Écologie", "Entraide", "Inclusivité", "Partage", "Transmission", "Expérimentation",
                       "Solidarité", "Féminisme", "Autre"], max_choices=4),
        Field("familles_tiers_lieux", "Dans quelle(s) famille(s) de tiers-lieux ce lieu se reconnaît-il ?",
              FieldType.MULTI_CHOICE,
              options=["Ateliers artisanaux partagés", "Bureaux partagés / coworking", "Cuisine partagée / foodlab",
                       "Fablab / makerspace / hackerspace", "Living lab / laboratoire d'innovation sociale",
                       "Tiers-lieu nourricier", "Tiers-lieu culturel / lieu intermédiaire", "Autre"]),
        Field("lance_seul", "Avez-vous choisi et commencé à occuper ce lieu seul, ou à plusieurs ?", FieldType.BOOLEAN,
              help_text="Répondez « oui » si vous avez été seul·e à l'initiative du lancement."),
        Field("modalite_lancement_collectif", "Comment le lancement s'est-il fait à plusieurs ?", FieldType.TEXTAREA,
              condition=Condition("lance_seul", "eq", False)),
    ],
)

section_activites = Section(
    id="activites",
    title="Activités et services",
    fields=[
        Field("activites_principales", "Quelles activités et services le lieu propose-t-il ?", FieldType.MULTI_CHOICE,
              required=True,
              options=["Coworking / bureaux partagés", "Fabrication numérique ou artisanale", "Activités culturelles ou artistiques",
                       "Formation professionnelle", "Activités liées à l'alimentation (production, transformation, distribution)",
                       "Hébergement", "Services liés à la santé", "Accompagnement de projets / incubation",
                       "Économie circulaire (ressourcerie, recyclerie)", "Services publics de proximité",
                       "Événementiel / vie associative", "Médiation numérique", "Autre"]),
        Field("equipements", "Quels grands types d'équipements le lieu met-il à disposition ?", FieldType.MULTI_CHOICE,
              options=["Bureautique et connexion internet", "Outils de fabrication numérique", "Ateliers manuels / bricolage",
                       "Espaces de production artistique", "Cuisine professionnelle ou partagée", "Espaces extérieurs",
                       "Hébergement (douches, lits...)", "Aucun équipement particulier", "Autre"]),
    ],
)

section_activites_alimentaires = Section(
    id="activites_alimentaires",
    title="Approfondissement — activités alimentaires",
    condition=Condition("activites_principales", "contains", "Activités liées à l'alimentation (production, transformation, distribution)"),
    fields=[
        Field("origine_produits", "D'où proviennent principalement les produits travaillés sur place ?", FieldType.SINGLE_CHOICE,
              options=["Production sur place", "Circuits courts locaux", "Approvisionnement mixte", "Approvisionnement non local", "Je ne sais pas"]),
        Field("volume_repas_paniers", "Volume approximatif (repas ou paniers distribués par mois)", FieldType.NUMBER, roles=ROLES_INTERNES),
        Field("tarification_solidaire", "Une tarification solidaire ou différenciée est-elle proposée ?", FieldType.BOOLEAN),
    ],
)

section_services_detailles = Section(
    id="services_detailles",
    title="Détail des services proposés",
    fields=[
        Field("services_proposes", "Parmi cette liste, lesquels de ces services le lieu propose-t-il ?",
              FieldType.MULTI_CHOICE,
              options=["Espaces de télétravail", "Salles de réunion", "Espaces de loisirs ou de spectacle",
                       "Service de restauration", "Fablab / makerspace / hackerspace", "Atelier(s) pour artisans",
                       "Domiciliation d'entreprises", "Accompagnement d'entreprises / accueil de structures d'accompagnement",
                       "Accueil d'associations", "Événements culturels", "Événements professionnels",
                       "Formations (para)professionnelles", "Aucun de ceux-ci", "Autre"]),
        Field("nombre_entreprises_domiciliees", "Combien d'entreprises sont domiciliées au lieu ?", FieldType.NUMBER,
              condition=Condition("services_proposes", "contains", "Domiciliation d'entreprises")),
        Field("nombre_associations_accueillies", "Combien d'associations sont accueillies au lieu ?", FieldType.NUMBER,
              condition=Condition("services_proposes", "contains", "Accueil d'associations")),
    ],
)

section_milieu_rural = Section(
    id="mobilite_rurale",
    title="Approfondissement — mobilité en milieu rural",
    condition=Condition("milieu", "eq", "Rural"),
    fields=[
        Field("distance_transport_commun", "Le lieu est-il facilement accessible en transport en commun ?", FieldType.SINGLE_CHOICE,
              options=["Oui, arrêt à proximité immédiate", "Oui mais peu fréquent", "Non, accès principalement en voiture", "Je ne sais pas"]),
        Field("mobilite_douce", "Une part notable des usagers vient-elle à pied, à vélo ou en covoiturage ?", FieldType.BOOLEAN),
    ],
)

section_milieu_urbain = Section(
    id="pression_fonciere_urbaine",
    title="Approfondissement — dynamique urbaine",
    condition=Condition("milieu", "eq", "Urbain"),
    fields=[
        Field("pression_fonciere_percue", "Percevez-vous une pression foncière ou un risque de gentrification liée au quartier ?", FieldType.SINGLE_CHOICE,
              options=["Oui, fortement", "Oui, modérément", "Non", "Je ne sais pas"]),
    ],
)

section_foncier = Section(
    id="foncier",
    title="Foncier et occupation des locaux",
    fields=[
        Field("statut_occupation", "Vis-à-vis du bâtiment, la structure est...", FieldType.SINGLE_CHOICE, required=True,
              options=["Propriétaire", "Locataire au prix du marché", "Locataire à prix modéré",
                       "Occupante à titre gracieux", "Occupante sans titre / temporaire", "Autre"], roles=ROLES_INTERNES),
        Field("surface_batie_m2", "Surface bâtie approximative (m²)", FieldType.NUMBER),
        Field("proprietaire_type", "Si le lieu n'est pas propriétaire, qui possède le bâtiment ?", FieldType.SINGLE_CHOICE,
              condition=Condition("statut_occupation", "ne", "Propriétaire"), roles=ROLES_INTERNES,
              options=["Collectivité publique", "Bailleur social", "Propriétaire privé", "Opérateur public", "Autre"]),
        Field("lieu_inoccupe_avant", "Ce lieu était-il inoccupé juste avant votre arrivée ?", FieldType.BOOLEAN),
        Field("ancienne_occupation", "Quelle était son occupation précédente ?", FieldType.TEXT,
              condition=Condition("lieu_inoccupe_avant", "eq", False)),
    ],
)

section_publics = Section(
    id="publics",
    title="Publics accueillis",
    fields=[
        Field("profils_socio_pro", "Quels profils fréquentent le lieu quotidiennement ?", FieldType.MULTI_CHOICE,
              options=["Indépendants / entrepreneurs", "Salariés en télétravail", "Artisans / commerçants",
                       "Étudiants", "Demandeurs d'emploi", "Retraités", "Familles avec enfants",
                       "Personnes en situation de précarité", "Bénévoles", "Autre"]),
        Field("tranches_age_publics", "Quelles tranches d'âge sont représentées parmi les usagers réguliers ?", FieldType.MULTI_CHOICE,
              options=TRANCHES_AGE),
        Field("accueil_publics_migrants", "Le lieu accueille-t-il régulièrement des publics migrants ou réfugiés ?", FieldType.BOOLEAN),
        Field("accessibilite_pmr", "Le lieu est-il accessible aux personnes à mobilité réduite ?", FieldType.BOOLEAN),
        Field("problematiques_sociales", "Le lieu porte-t-il des projets sur l'une de ces problématiques ?", FieldType.MULTI_CHOICE,
              options=DIFFICULTES_SOCIALES),
        Field("motivations_usagers", "Pourquoi vos usagers viennent-ils principalement ? (plusieurs réponses possibles)",
              FieldType.MULTI_CHOICE,
              options=["Pas de place à domicile", "Ambiance et contacts sociaux", "Télétravail",
                       "Soutien à la démarche du lieu", "Collaborer avec d'autres usagers",
                       "Recevoir des collaborateurs externes", "Recevoir des clients",
                       "Installer son activité / son entreprise", "Mener des réunions", "Domicilier son activité",
                       "Éviter de domicilier son activité à domicile", "Animations extraprofessionnelles",
                       "Formations (para)professionnelles", "Autre"]),
        Field("statuts_usagers_dominants", "Parmi ces statuts, lesquels sont bien représentés parmi les usagers ?",
              FieldType.MULTI_CHOICE,
              options=["Indépendant à titre principal", "Indépendant à titre complémentaire", "Freelance",
                       "Salarié", "Étudiant", "Sans emploi", "Membre d'une association", "Dirigeant d'entreprise",
                       "Riverain", "Autre"]),
        Field("domaines_professionnels_top3", "Quels sont les 2-3 domaines professionnels les plus représentés parmi les usagers ?",
              FieldType.TEXTAREA),
        Field("profil_usagers_evolution", "Par rapport à il y a trois ans, voyez-vous une évolution notable dans le profil des usagers ?",
              FieldType.MULTI_CHOICE,
              options=["Davantage de salariés", "Davantage de freelances", "Davantage d'indépendants à titre principal",
                       "Davantage d'indépendants à titre complémentaire", "Pas de changement notable",
                       "Le lieu n'existait pas il y a 3 ans"]),
        Field("frequence_dominante_usagers", "À quelle fréquence la majorité de vos usagers reviennent-ils au lieu ?",
              FieldType.SINGLE_CHOICE,
              options=["Quotidienne", "2 à 4 fois par semaine", "Une fois par semaine",
                       "Quelques fois par mois", "Une fois par mois ou moins", "Je ne sais pas"]),
    ],
)

section_publics_migrants = Section(
    id="publics_migrants_detail",
    title="Approfondissement — accueil de publics migrants",
    condition=Condition("accueil_publics_migrants", "eq", True),
    fields=[
        Field("langues_parlees", "Quelles langues sont couramment parlées ou accueillies sur place ?", FieldType.TEXT),
        Field("dispositif_interpretariat", "Un dispositif d'interprétariat ou de médiation linguistique existe-t-il ?", FieldType.BOOLEAN),
    ],
)

section_rh = Section(
    id="ressources_humaines",
    title="Équipe et ressources humaines",
    fields=[
        Field("etp_geres", "Combien d'équivalents temps plein sont mobilisés pour la gestion du lieu ?", FieldType.NUMBER,
              roles=ROLES_INTERNES),
        Field("metiers_exerces", "Quels métiers ou missions sont exercés au sein de l'équipe ?", FieldType.MULTI_CHOICE,
              roles=ROLES_INTERNES,
              options=["Coordination générale", "Communication", "Accueil / conciergerie", "Facilitation / animation",
                       "Fabmanager / atelier", "Entretien / maintenance", "Médiation", "Comptabilité / administratif", "Autre"]),
        Field("part_femmes_equipe", "Quel est le pourcentage de femmes dans l'équipe salariée ?", FieldType.NUMBER, roles=ROLES_INTERNES),
        Field("organisme_formation_lien", "Le lieu est-il enregistré ou en lien avec un organisme d'insertion/formation reconnu ?",
              FieldType.SINGLE_CHOICE, options=ORGANISME_INSERTION_FORMATION, roles=ROLES_INTERNES),
        Field("qvt_equipe", "Comment décririez-vous la qualité de vie au travail de l'équipe salariée ?", FieldType.TEXTAREA,
              roles=ROLES_INTERNES),
    ],
)

section_gouvernance = Section(
    id="gouvernance",
    title="Gouvernance",
    fields=[
        Field("mode_gouvernance", "Comment le lieu est-il géré ?", FieldType.SINGLE_CHOICE,
              options=["Une structure porteuse unique", "Une structure porteuse avec des usagers impliqués",
                       "Plusieurs structures co-porteuses", "Autre"]),
        Field("participation_usagers", "Comment les usagers participent-ils à la vie du lieu ?", FieldType.MULTI_CHOICE,
              options=["Animation d'événements", "Coup de main sur les aménagements", "Participation aux instances de décision",
                       "Temps informels partagés", "Aucune participation", "Autre"]),
        Field("repartition_societariat", "Comment le sociétariat est-il réparti (usagers, salariés, collectivités, investisseurs) ?",
              FieldType.TEXTAREA,
              condition=Condition("statut_juridique", "in",
                                   ["SCIC", "SCOP", "Coopérative", "Coopérative (SC / SCRL)"]),
              roles=ROLES_INTERNES),
        Field("politique_redistribution", "Existe-t-il une politique de redistribution des excédents ?", FieldType.BOOLEAN,
              condition=Condition("statut_juridique", "in",
                                   ["SCIC", "SCOP", "Coopérative", "Coopérative (SC / SCRL)"]),
              roles=ROLES_INTERNES),
    ],
)

section_partenariats = Section(
    id="partenariats",
    title="Partenariats territoriaux",
    fields=[
        Field("acteurs_mobilises", "Quels acteurs du territoire le lieu mobilise-t-il ?", FieldType.MULTI_CHOICE,
              options=ACTEURS_TERRITORIAUX),
        Field("qualite_partenariats", "Comment qualifieriez-vous la qualité de ces partenariats aujourd'hui ?", FieldType.TEXTAREA),
        Field("liens_entreprises", "Quels liens existent avec des entreprises du territoire ?", FieldType.MULTI_CHOICE,
              options=["Financement d'activités", "Co-développement de projets", "Consommation de services/biens proposés",
                       "Association à la gouvernance", "Pas de lien", "Autre"]),
        Field("usagers_partenariats_evenements",
              "Vos usagers ont-ils eux-mêmes des partenariats ou organisent-ils des événements avec d'autres acteurs locaux ?",
              FieldType.BOOLEAN),
        Field("usagers_partenariats_detail", "Pouvez-vous préciser ?", FieldType.TEXTAREA,
              condition=Condition("usagers_partenariats_evenements", "eq", True)),
        Field("usagers_activites_annexes_quartier",
              "Vos usagers profitent-ils de leur venue pour faire d'autres activités (achats, démarches, loisirs...) dans le quartier ?",
              FieldType.BOOLEAN),
        Field("usagers_activites_annexes_detail", "Lesquelles reviennent le plus souvent ?", FieldType.TEXTAREA,
              condition=Condition("usagers_activites_annexes_quartier", "eq", True)),
    ],
)

section_modele_economique = Section(
    id="modele_economique",
    title="Modèle économique",
    fields=[
        Field("sources_financement_fonctionnement", "Quelles sont les principales sources de financement du fonctionnement (par ordre d'importance) ?",
              FieldType.MULTI_CHOICE, roles=ROLES_INTERNES,
              options=["Subvention(s) publique(s)", "Adhésions / cotisations", "Location d'espaces", "Ateliers / formations",
                       "Restauration / débit de boissons", "Dons / mécénat", "Vente de produits", "Prêt bancaire", "Autre"]),
        Field("subventionneurs_publics", "Si des subventions publiques sont perçues, de quels niveaux proviennent-elles ?",
              FieldType.MULTI_CHOICE, options=SUBVENTIONNEURS_PUBLICS, roles=ROLES_INTERNES,
              condition=Condition("sources_financement_fonctionnement", "contains", "Subvention(s) publique(s)")),
        Field("dependance_financeur_unique", "Un financeur représente-t-il une part dominante (>50%) des ressources ?",
              FieldType.BOOLEAN, roles=ROLES_INTERNES),
        Field("difficulte_financiere_actuelle", "Le lieu traverse-t-il actuellement une difficulté financière ?",
              FieldType.BOOLEAN, roles=ROLES_INTERNES),
    ],
)

section_difficulte_financiere = Section(
    id="difficulte_financiere_detail",
    title="Approfondissement — difficulté financière",
    condition=Condition("difficulte_financiere_actuelle", "eq", True),
    fields=[
        Field("nature_difficulte", "Quelle est la nature principale de cette difficulté ?", FieldType.SINGLE_CHOICE,
              roles=ROLES_INTERNES,
              options=["Trésorerie court terme", "Dépendance excessive à une subvention", "Sous-effectif / surcharge de travail",
                       "Baisse de fréquentation ou d'activité", "Autre"]),
        Field("urgence_difficulte", "Quel est le degré d'urgence de cette situation ?", FieldType.SCALE_1_5, roles=ROLES_INTERNES),
    ],
)

module_socle = Module(
    id="socle",
    title="Portrait du lieu",
    optional=False,
    sections=[
        section_localisation_identite,
        section_acteurs_origine,
        section_activites,
        section_activites_alimentaires,
        section_services_detailles,
        section_milieu_rural,
        section_milieu_urbain,
        section_foncier,
        section_publics,
        section_publics_migrants,
        section_rh,
        section_gouvernance,
        section_partenariats,
        section_modele_economique,
        section_difficulte_financiere,
    ],
)


# ---------------------------------------------------------------------------
# Module 2 — Impact (optionnel)
# ---------------------------------------------------------------------------

section_impact_mobilite = Section(
    id="impact_mobilite",
    title="Impact — mobilité et énergie",
    fields=[
        Field("part_deplacements_doux", "Quelle part des usagers vient à pied, à vélo ou en covoiturage ?", FieldType.SINGLE_CHOICE,
              options=["Faible", "Modérée", "Élevée", "Je ne sais pas"]),
        Field("bilan_carbone_fait", "Un bilan carbone du lieu (énergie, mobilité, alimentation) a-t-il déjà été réalisé ?", FieldType.BOOLEAN),
        Field("part_energie_renouvelable", "Une part de l'énergie utilisée est-elle renouvelable ?", FieldType.BOOLEAN),
        Field("usagers_mode_voiture", "Quelle part des usagers privilégie la voiture pour venir ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
        Field("usagers_mode_velo", "Quelle part des usagers privilégie le vélo pour venir ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
        Field("usagers_mode_pied", "Quelle part des usagers vient à pied ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
        Field("usagers_mode_transport_commun", "Quelle part des usagers vient en transport en commun ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
    ],
)

section_impact_biodiversite = Section(
    id="impact_biodiversite",
    title="Impact — renaturation et biodiversité",
    fields=[
        Field("espaces_verts_valorises", "Des espaces verts sont-ils créés ou valorisés sur le site (jardins, compost...) ?", FieldType.BOOLEAN),
        Field("actions_biodiversite", "Décrivez brièvement les actions liées à la biodiversité, si elles existent.", FieldType.TEXTAREA),
    ],
)

section_impact_satisfaction = Section(
    id="impact_satisfaction",
    title="Impact — satisfaction et fidélisation",
    fields=[
        Field("satisfaction_usagers", "Comment évalueriez-vous la satisfaction générale des usagers ?", FieldType.SCALE_1_5),
        Field("taux_fidelisation", "Les usagers reviennent-ils régulièrement sur la durée, ou le renouvellement est-il rapide ?",
              FieldType.SINGLE_CHOICE, options=["Forte fidélisation", "Fidélisation modérée", "Fort renouvellement", "Je ne sais pas"]),
        Field("frequentation_semaine_type",
              "Sur une « bonne » semaine ouvrable, combien de passages estimez-vous en moyenne "
              "(une même personne comptée à chaque jour où elle vient) ?", FieldType.NUMBER),
        Field("evolution_frequentation_3ans", "Par rapport à il y a trois ans, comment la fréquentation a-t-elle évolué ?",
              FieldType.SINGLE_CHOICE,
              options=["Nette hausse", "Légère hausse", "Stable", "Légère baisse", "Nette baisse",
                       "Le lieu n'existait pas il y a 3 ans"]),
    ],
)

section_impact_resilience = Section(
    id="impact_resilience",
    title="Impact — résilience et rayonnement",
    fields=[
        Field("role_crises_locales", "Le lieu a-t-il joué un rôle particulier lors d'une crise locale (sanitaire, climatique, économique) ?",
              FieldType.TEXTAREA),
        Field("essaimage", "Le lieu a-t-il inspiré ou aidé à créer d'autres projets ou tiers-lieux ?", FieldType.TEXTAREA),
        Field("souverainete_numerique", "Le lieu privilégie-t-il des outils numériques libres ou souverains dans son fonctionnement ?",
              FieldType.BOOLEAN),
        Field("transmission_intergenerationnelle", "Existe-t-il des formes de transmission de savoirs entre générations, même informelles ?",
              FieldType.TEXTAREA),
        Field("provenance_usagers_commune", "Quelle part des usagers vient de la commune d'implantation du lieu ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
        Field("provenance_usagers_limitrophe", "Quelle part des usagers vient d'une commune limitrophe ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
        Field("provenance_usagers_plus_loin", "Quelle part des usagers vient de plus loin ?",
              FieldType.SINGLE_CHOICE, options=BANDE_INTENSITE),
        Field("evolution_provenance_usagers", "Par rapport à il y a trois ans, la provenance géographique des usagers a-t-elle changé ?",
              FieldType.SINGLE_CHOICE,
              options=["Usagers plus locaux qu'avant", "Usagers viennent de plus loin qu'avant",
                       "Pas de changement notable", "Le lieu n'existait pas il y a 3 ans"]),
        Field("rayonnement_large",
              "Le lieu accueille-t-il des événements ou réunions organisés par/pour des personnes venant d'assez loin ?",
              FieldType.BOOLEAN),
        Field("rayonnement_exemples", "Pouvez-vous donner un exemple ?", FieldType.TEXTAREA,
              condition=Condition("rayonnement_large", "eq", True)),
    ],
)

module_impact = Module(
    id="impact",
    title="Mesurer l'impact",
    optional=True,
    sections=[
        section_impact_mobilite,
        section_impact_biodiversite,
        section_impact_satisfaction,
        section_impact_resilience,
    ],
)


# ---------------------------------------------------------------------------
# Module 3 — Diagnostic & besoins (optionnel)
# ---------------------------------------------------------------------------

section_diagnostic_vision = Section(
    id="diagnostic_vision",
    title="Diagnostic — vision et positionnement",
    fields=[
        Field("raison_etre", "Quelle est la raison d'être du projet ? À quels besoins du territoire répond-il ?", FieldType.TEXTAREA),
        Field("vision_5_ans", "Quelle est votre vision du lieu dans 5 ans ?", FieldType.TEXTAREA),
        Field("obstacles_anticipes", "Quels obstacles anticipez-vous pour réaliser cette vision ?", FieldType.TEXTAREA),
        Field("besoin_aide_vision", "À quel point une aide sur la vision/le positionnement vous serait-elle utile ?", FieldType.SCALE_1_5),
    ],
)

section_diagnostic_gouvernance = Section(
    id="diagnostic_gouvernance",
    title="Diagnostic — gouvernance vécue",
    fields=[
        Field("freins_decision", "Quels freins ou tensions avez-vous rencontrés dans la prise de décision ?", FieldType.TEXTAREA),
        Field("equite_repartition", "La répartition des responsabilités est-elle perçue comme équitable ?", FieldType.SINGLE_CHOICE,
              options=["Oui", "Plutôt oui", "Plutôt non", "Non", "Je ne sais pas"]),
        Field("besoin_aide_gouvernance", "À quel point une aide sur la gouvernance vous serait-elle utile ?", FieldType.SCALE_1_5),
    ],
)

section_diagnostic_swot = Section(
    id="diagnostic_swot",
    title="Diagnostic — atouts, faiblesses, opportunités, menaces",
    fields=[
        Field("atouts", "Quels sont les principaux atouts du projet ?", FieldType.TEXTAREA),
        Field("menaces", "Quelles menaces pourraient compromettre sa pérennité ?", FieldType.TEXTAREA),
        Field("besoin_aide_analyse", "À quel point une aide sur cette analyse vous serait-elle utile ?", FieldType.SCALE_1_5),
    ],
)

section_diagnostic_besoins_futurs = Section(
    id="diagnostic_besoins_futurs",
    title="Diagnostic — besoins des 3 prochaines années",
    fields=[
        Field("types_soutien_souhaites", "De quels types de soutien auriez-vous besoin ces 3 prochaines années ?",
              FieldType.MULTI_CHOICE,
              options=["Plan financier et pérennisation", "Gouvernance / gestion de collectif", "Médiation de conflits",
                       "Communication", "Activation de communauté d'usagers", "Ancrage territorial / partenariats",
                       "Aide juridique", "Gestion de projet", "Montée en compétence de l'équipe",
                       "Mise en réseau avec d'autres tiers-lieux", "Aide sur systèmes énergétiques/hydriques",
                       "Rénovation / obstacles architecturaux", "Aucun besoin identifié", "Autre"]),
        Field("priorites_principales", "Parmi ces besoins, quelles sont vos 2 à 3 priorités ?", FieldType.TEXTAREA),
    ],
)

section_learning_expedition = Section(
    id="learning_expedition_europe",
    title="Programme — Learning Expedition Europe",
    intro="Un appel à candidatures est en cours pour une learning expedition entre tiers-lieux à travers l'Europe.",
    fields=[
        Field("interet_learning_expedition",
              "Seriez-vous intéressé·e à déposer un dossier de candidature pour participer à une "
              "learning expedition entre tiers-lieux en Europe ?", FieldType.SINGLE_CHOICE,
              options=["Oui, je souhaite déposer un dossier", "Pas pour l'instant", "Je ne sais pas encore"]),
        Field("candidat_referent", "Qui serait la personne référente pour ce dossier (nom, fonction) ?",
              FieldType.TEXT,
              condition=Condition("interet_learning_expedition", "eq", "Oui, je souhaite déposer un dossier")),
        Field("candidat_motivation",
              "En quelques mots, qu'espérez-vous retirer de cette learning expedition pour votre lieu ?",
              FieldType.TEXTAREA,
              condition=Condition("interet_learning_expedition", "eq", "Oui, je souhaite déposer un dossier")),
        Field("candidat_experience_internationale",
              "Votre équipe a-t-elle déjà une expérience d'échange avec des tiers-lieux à l'étranger ?",
              FieldType.BOOLEAN,
              condition=Condition("interet_learning_expedition", "eq", "Oui, je souhaite déposer un dossier")),
        Field("candidat_disponibilite",
              "Sur quelle période votre équipe serait-elle disponible pour ce déplacement ?", FieldType.TEXT,
              condition=Condition("interet_learning_expedition", "eq", "Oui, je souhaite déposer un dossier")),
    ],
)

module_diagnostic = Module(
    id="diagnostic",
    title="Diagnostic et besoins d'accompagnement",
    optional=True,
    sections=[
        section_diagnostic_vision,
        section_diagnostic_gouvernance,
        section_diagnostic_swot,
        section_diagnostic_besoins_futurs,
        section_learning_expedition,
    ],
)


QUESTIONNAIRE = [module_socle, module_impact, module_diagnostic]


def all_fields():
    for module in QUESTIONNAIRE:
        for section in module.sections:
            for f in section.fields:
                yield module, section, f


def get_module(module_id: str) -> Optional[Module]:
    return next((m for m in QUESTIONNAIRE if m.id == module_id), None)


def get_section(module_id: str, section_id: str) -> Optional[Section]:
    module = get_module(module_id)
    if not module:
        return None
    return next((s for s in module.sections if s.id == section_id), None)


_FIELDS_BY_ID = {f.id: f for _, _, f in all_fields()}


def get_field(champ_id: str) -> Optional[Field]:
    """Lookup global d'un champ par id, indépendamment de sa section — utilisé
    par les campagnes prioritaires (collecte_tools.py) qui référencent des
    champs par id sans connaître leur module/section d'origine."""
    return _FIELDS_BY_ID.get(champ_id)
