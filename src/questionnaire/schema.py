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
    # Nombre de sections en tête de liste toujours proposées dans l'ordre
    # déclaré ci-dessous, avant que le tirage pseudo-aléatoire par session
    # (voir resolver.next_incomplete_section) ne s'applique au reste. Utile
    # pour les sections qui posent les questions dont dépendent des sections
    # conditionnelles plus loin dans la liste (ex. "activités", "milieu") :
    # les faire passer tôt maximise les branches débloquées pour la suite,
    # sans quoi le tirage aléatoire pourrait les repousser arbitrairement
    # tard et retarder d'autant la découverte des sections qu'elles activent.
    ancrage_debut: int = 0


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
    "Citoyenneté",
    "Éthique au travail",
    "Sans-abrisme",
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

# Réutilisée par diagnostic_besoins_futurs ET learning_expedition_europe (les
# besoins associés à un futur axe de développement sont la même taxonomie
# que les besoins d'accompagnement généraux — pas de raison d'avoir deux
# listes différentes pour la même notion).
OPTIONS_SOUTIEN_ACCOMPAGNEMENT = [
    "Plan financier et pérennisation", "Gouvernance / gestion de collectif", "Médiation de conflits",
    "Repenser l'organisationnel et les processus de décision", "Communication",
    "Activation de communauté d'usagers", "Ancrage territorial / partenariats",
    "Événementiel (conception ou production d'événements)", "Aide juridique", "Gestion de projet",
    "Structure d'accueil de bénévoles", "Développement entrepreneurial / rapport à l'argent des usagers",
    "Lancement de services de proximité", "Usages d'outils numériques",
    "Gestion financière, administrative et comptabilité", "Montée en compétence de l'équipe",
    "Ressources pratiques et inspirations (modèles, fieldtrips...)",
    "Mise en réseau avec d'autres tiers-lieux", "Aide sur systèmes énergétiques/hydriques",
    "Centre logistique ou compostage", "Rénovation / obstacles architecturaux",
    "Innovation low-tech, éco-construction ou économie circulaire",
    "Activités agricoles ou alimentaires", "Comment implémenter des services publics",
    "Aucun besoin identifié", "Autre",
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
        Field("frequence_activites_principales", "À quelle fréquence les activités principales du lieu ont-elles lieu ?",
              FieldType.SINGLE_CHOICE,
              options=["Quotidienne", "Plusieurs fois par semaine", "Hebdomadaire", "Mensuelle",
                       "Ponctuelle / événementielle", "Variable selon l'activité"]),
        Field("activite_phare", "Si vous deviez décrire l'activité la plus emblématique ou porteuse du lieu, "
                                 "laquelle et pourquoi ?", FieldType.TEXTAREA),
        Field("evolution_activites_3ans", "Comment l'offre d'activités a-t-elle évolué ces trois dernières années ?",
              FieldType.MULTI_CHOICE,
              options=["De nouvelles activités se sont ajoutées", "Certaines activités ont été abandonnées",
                       "L'offre s'est recentrée / spécialisée", "Peu de changement",
                       "Le lieu n'existait pas il y a 3 ans"]),
        Field("activites_saisonnalite", "L'activité du lieu varie-t-elle fortement selon les saisons ?", FieldType.BOOLEAN),
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

section_culture_detail = Section(
    id="culture_detail",
    title="Approfondissement — culture et arts",
    condition=Condition("activites_principales", "contains", "Activités culturelles ou artistiques"),
    fields=[
        Field("domaines_artistiques", "Quels domaines artistiques le lieu accueille-t-il ?", FieldType.MULTI_CHOICE,
              options=["Arts plastiques", "Spectacles vivants", "Musique", "Écriture / littérature",
                       "Architecture et patrimoine", "Autre"]),
        Field("types_activites_artistiques", "Quels types d'activités artistiques le lieu propose-t-il ?",
              FieldType.MULTI_CHOICE,
              options=["Diffusion (spectacles, expositions)", "Pratiques amateurs", "Médiation culturelle",
                       "Création artistique", "Accueil d'artistes en résidence",
                       "Administration / production de projets culturels", "Éducation artistique et culturelle",
                       "Formation professionnelle artistique", "Autre"]),
        Field("nombre_evenements_culturels_an", "Combien d'événements culturels/artistiques ouverts au public le "
                                                  "lieu organise-t-il par an, environ ?", FieldType.NUMBER),
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
        Field("repartition_structures_hebergees", "Parmi les structures hébergées ou domiciliées, quels types "
                                                    "sont représentés ?", FieldType.MULTI_CHOICE,
              options=["Entrepreneurs / indépendants individuels", "Associations", "PME / TPE", "Coopératives",
                       "SARL ou équivalent", "Artistes", "Autre"],
              condition=Condition("services_proposes", "contains", "Domiciliation d'entreprises")),
        Field("activite_incubation_pepiniere", "Le lieu a-t-il une activité d'incubateur, de pépinière ou "
                                                 "d'accélérateur d'entreprises ?", FieldType.BOOLEAN),
        Field("part_teletravail_coworking", "Quelle part des usagers du coworking sont des salarié·es en "
                                             "télétravail (plutôt qu'indépendants) ?", FieldType.SINGLE_CHOICE,
              options=BANDE_INTENSITE,
              condition=Condition("services_proposes", "contains", "Espaces de télétravail")),
        Field("types_production", "Le lieu dispose-t-il d'outils ou d'espaces dédiés à l'un de ces types de "
                                   "production ?", FieldType.MULTI_CHOICE,
              options=["Production / transformation alimentaire", "Production agricole",
                       "Production de produits du quotidien non alimentaires", "Fabrication 3D / numérique",
                       "Travail du bois", "Travail du métal", "Production graphique (gravure, sérigraphie...)",
                       "Production textile", "Céramique / terre", "Travail du cuir", "Production médicale",
                       "Autre métier d'art", "Aucune", "Autre"]),
        Field("dispose_materiautheque_ressourcerie", "Le lieu dispose-t-il d'une matériauthèque ou d'une "
                                                       "ressourcerie ?", FieldType.BOOLEAN),
        Field("modalites_acces", "Comment les usagers accèdent-ils principalement aux services du lieu ?",
              FieldType.MULTI_CHOICE,
              options=["Gratuit / libre accès", "Adhésion", "Abonnement", "Paiement à l'usage",
                       "Sur réservation uniquement", "Sur critères / dossier", "Autre"]),
        Field("capacite_accueil_simultanee", "Combien de personnes le lieu peut-il accueillir simultanément "
                                              "(ordre de grandeur) ?", FieldType.NUMBER),
        Field("amplitude_horaire", "Quelle est l'amplitude horaire d'ouverture habituelle du lieu ?",
              FieldType.SINGLE_CHOICE,
              options=["Moins de 20h/semaine", "20 à 40h/semaine", "40 à 60h/semaine",
                       "Plus de 60h/semaine", "Ouvert en continu (7j/7)"]),
    ],
)

section_formations = Section(
    id="formations",
    title="Formations et apprentissages",
    fields=[
        Field("propose_formations", "Le lieu propose-t-il des formations, ateliers ou temps d'apprentissage "
                                     "entre pairs ?", FieldType.BOOLEAN),
        Field("themes_formations", "Sur quels thèmes portent ces formations ?", FieldType.MULTI_CHOICE,
              condition=Condition("propose_formations", "eq", True),
              options=["Numérique / informatique / programmation", "Entrepreneuriat", "Fabrication numérique",
                       "Intelligence collective / gouvernance partagée", "Écologie", "Artisanat / métiers d'art",
                       "Bien-être / coaching", "Culture / arts", "Communication / marketing",
                       "Administratif / gestion / finance", "Agriculture / biodiversité / apiculture",
                       "Réemploi", "Langues", "Autre"]),
        Field("origine_formations", "Comment ces formations sont-elles produites ?", FieldType.MULTI_CHOICE,
              condition=Condition("propose_formations", "eq", True),
              options=["Produites par le lieu lui-même", "Produites par d'autres structures",
                       "Produites par les membres/usagers", "Co-produites avec un organisme de formation"]),
        Field("nombre_personnes_formees_an", "Combien de personnes ont bénéficié d'une formation dans le lieu, "
                                              "environ par an ?", FieldType.NUMBER,
              condition=Condition("propose_formations", "eq", True)),
        Field("reconnu_education_permanente", "Le lieu est-il reconnu au titre de l'éducation permanente ou d'un "
                                               "dispositif équivalent ?", FieldType.BOOLEAN),
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
        Field("accessibilite_dimensions", "Au-delà de l'accessibilité physique (PMR), sur quelles autres dimensions "
                                           "le lieu veille-t-il à rester accessible ?", FieldType.MULTI_CHOICE,
              options=["Accessibilité financière (tarifs adaptés, gratuité...)",
                       "Accessibilité cognitive (signalétique claire, accompagnement...)",
                       "Aucune démarche particulière", "Autre"]),
        Field("sentiment_inclusion_confiance", "Comment décririez-vous le sentiment d'inclusion, d'appartenance et de "
                                                "confiance entre les usagers du lieu ?", FieldType.TEXTAREA),
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
        Field("nombre_benevoles_reguliers", "Combien de bénévoles réguliers contribuent au fonctionnement du lieu ?",
              FieldType.NUMBER, roles=ROLES_INTERNES),
        Field("turnover_equipe", "Comment qualifieriez-vous le turnover au sein de l'équipe salariée ?",
              FieldType.SINGLE_CHOICE,
              options=["Très faible, équipe stable", "Modéré", "Élevé", "Pas d'équipe salariée"],
              roles=ROLES_INTERNES),
        Field("defis_recrutement_rh", "Rencontrez-vous des difficultés de recrutement ou de fidélisation de "
                                       "l'équipe ?", FieldType.TEXTAREA, roles=ROLES_INTERNES),
    ],
)

section_gouvernance = Section(
    id="gouvernance",
    title="Gouvernance",
    fields=[
        # Déplacé depuis section_acteurs_origine : demandé juste après
        # "d'où vient le projet / quelles valeurs", il créait une rupture de
        # thème perçue comme incohérente par les répondants ("on parlait de
        # genèse et de valeurs, pourquoi une question juridique ?"). Il
        # gate déjà plusieurs champs plus bas dans CETTE section (coopérative
        # ou non) — le placer ici règle la rupture ET rapproche le champ de
        # ses propres dépendants, dans la même section plutôt qu'entre deux
        # sections différentes.
        Field("statut_juridique", "Statut juridique de la structure porteuse", FieldType.SINGLE_CHOICE,
              options=STATUT_JURIDIQUE, roles=ROLES_INTERNES),
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
        Field("frequence_instances_gouvernance", "À quelle fréquence les instances de gouvernance "
                                                  "(CA, AG, comité...) se réunissent-elles ?", FieldType.SINGLE_CHOICE,
              options=["Hebdomadaire", "Mensuelle", "Trimestrielle", "Annuelle uniquement",
                       "Pas d'instance formelle", "Je ne sais pas"], roles=ROLES_INTERNES),
        Field("outils_gouvernance_formalises", "Quels outils de gouvernance sont formalisés ?", FieldType.MULTI_CHOICE,
              options=["Statuts", "Règlement intérieur", "Charte de valeurs", "Organigramme", "Aucun", "Autre"],
              roles=ROLES_INTERNES),
        Field("mode_prise_decision", "Comment les décisions importantes sont-elles généralement prises ?",
              FieldType.SINGLE_CHOICE,
              options=["Par consensus", "Par vote majoritaire", "Par la direction / le porteur de projet seul",
                       "Sociocratie / gouvernance partagée", "Autre"], roles=ROLES_INTERNES),
        Field("difficulte_gouvernance", "Rencontrez-vous des difficultés particulières liées à la gouvernance ou "
                                         "à la prise de décision ?", FieldType.TEXTAREA, roles=ROLES_INTERNES),
        Field("nombre_adherents_cooperateurs", "Combien d'adhérents (association) ou de coopérateurs (coopérative) "
                                                "compte le lieu ?", FieldType.NUMBER, roles=ROLES_INTERNES,
              condition=Condition("statut_juridique", "in",
                                   ["Association / organisation à but non lucratif", "Association loi 1901", "ASBL",
                                    "SCIC", "SCOP", "Coopérative", "Coopérative (SC / SCRL)"])),
        Field("gouvernance_multiniveau", "Le lieu s'inscrit-il dans un modèle de gouvernance multi-niveau "
                                          "(commune, région, réseau européen...) ?", FieldType.BOOLEAN,
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
                       "Restauration / débit de boissons", "Dons / mécénat", "Vente de produits", "Prêt bancaire",
                       "Billetterie", "Location de machines ou d'outils", "Crowdfunding", "Offre d'hébergement",
                       "Conseil / accompagnement / ingénierie de projets", "Autre"]),
        Field("subventionneurs_publics", "Si des subventions publiques sont perçues, de quels niveaux proviennent-elles ?",
              FieldType.MULTI_CHOICE, options=SUBVENTIONNEURS_PUBLICS, roles=ROLES_INTERNES,
              condition=Condition("sources_financement_fonctionnement", "contains", "Subvention(s) publique(s)")),
        Field("dependance_financeur_unique", "Un financeur représente-t-il une part dominante (>50%) des ressources ?",
              FieldType.BOOLEAN, roles=ROLES_INTERNES),
        Field("difficulte_financiere_actuelle", "Le lieu traverse-t-il actuellement une difficulté financière ?",
              FieldType.BOOLEAN, roles=ROLES_INTERNES),
        Field("chiffre_affaires_annuel", "Quel est le chiffre d'affaires annuel approximatif du lieu (€) ?",
              FieldType.NUMBER, roles=ROLES_INTERNES),
        Field("resultat_annuel", "Quel est le résultat annuel approximatif (bénéfice ou perte, en €) ?",
              FieldType.NUMBER, roles=ROLES_INTERNES,
              help_text="Un nombre négatif pour une perte."),
        Field("pourcentage_subside_rentrees", "Quelle part (%) des rentrées du lieu provient de subsides ?",
              FieldType.NUMBER, roles=ROLES_INTERNES,
              help_text="Aide à situer si le modèle atteint l'équilibre sans subside ou non."),
        Field("sources_financement_investissement", "Quelles ont été les principales sources de financement de "
                                                      "l'investissement de départ (locaux, gros équipements) ?",
              FieldType.MULTI_CHOICE, roles=ROLES_INTERNES,
              options=["Fonds propres", "Subventions publiques", "Prêt bancaire", "Mécénat / fondations",
                       "Investissement en capital par les fondateurs ou proches", "Crowdfunding",
                       "Investissement en capital par des entreprises", "Autre"]),
        # Le corpus ne comportait aucune donnée financière chiffrée exploitable
        # pour une décision d'investissement (bilan, prévisionnel, ROI) au-delà
        # de chiffre_affaires_annuel/resultat_annuel — ces champs comblent ce
        # manque explicitement plutôt que de compter sur une mention spontanée.
        Field("a_des_investisseurs_capital", "Le lieu compte-t-il des investisseurs ayant apporté du capital "
                                              "(hors subventions, dons ou prêt bancaire) ?",
              FieldType.BOOLEAN, roles=ROLES_INTERNES),
        Field("montant_investi_capital", "Quel est le montant total de capital apporté par ces investisseurs (€) ?",
              FieldType.NUMBER, roles=ROLES_INTERNES,
              condition=Condition("a_des_investisseurs_capital", "eq", True)),
        Field("type_retour_investisseurs", "Quel type de retour est prévu ou attendu pour ces investisseurs ?",
              FieldType.SINGLE_CHOICE, roles=ROLES_INTERNES,
              options=["Retour financier chiffré (dividendes, plus-value, intérêts)",
                       "Remboursement du capital sans intérêt",
                       "Retour social/environnemental uniquement (pas de retour financier)",
                       "Non défini / pas encore clarifié", "Autre"],
              condition=Condition("a_des_investisseurs_capital", "eq", True)),
        Field("roi_annuel_pourcentage", "Si un retour financier chiffré est prévu, quel est le taux de "
                                         "rendement annuel approximatif (%) ?",
              FieldType.NUMBER, roles=ROLES_INTERNES,
              help_text="Sert de base à une véritable analyse de rentabilité pour un investisseur potentiel — "
                        "sans ce chiffre, seule une décision qualitative est possible.",
              condition=Condition("type_retour_investisseurs", "eq",
                                   "Retour financier chiffré (dividendes, plus-value, intérêts)")),
        Field("previsionnel_financier_formalise", "Le lieu dispose-t-il d'un prévisionnel financier formalisé "
                                                    "(business plan, budget prévisionnel pluriannuel) ?",
              FieldType.BOOLEAN, roles=ROLES_INTERNES),
        Field("horizon_previsionnel", "Sur quel horizon porte ce prévisionnel ?",
              FieldType.SINGLE_CHOICE, roles=ROLES_INTERNES,
              options=["1 an", "3 ans", "5 ans ou plus", "Autre"],
              condition=Condition("previsionnel_financier_formalise", "eq", True)),
        Field("postes_depenses_significatifs", "Quels sont les postes de dépenses de fonctionnement les plus "
                                                "significatifs ?", FieldType.MULTI_CHOICE, roles=ROLES_INTERNES,
              options=["Charges de fonctionnement (loyer, électricité, eau, internet, assurance...)",
                       "Rémunérations du personnel", "Investissement matériel (mobilier, équipement...)",
                       "Communication", "Travaux (peinture, menuiserie, sol...)", "Autre"]),
        Field("modeles_economiques_emergents", "Le lieu a-t-il mis en place l'un de ces modèles économiques "
                                                "émergents ?", FieldType.MULTI_CHOICE, roles=ROLES_INTERNES,
              options=["Coopérative (SCIC ou équivalent)", "Modèle contributif", "Monnaie locale",
                       "Aucun de ceux-ci", "Autre"]),
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
    # localisation_identite (milieu) et activites (activites_principales)
    # déclenchent à elles deux la quasi-totalité des sections conditionnelles
    # du module (alimentaire, culture, milieu rural/urbain...) — les garder
    # en tête garantit que ces branches sont débloquées tôt, quel que soit
    # l'ordre tiré ensuite pour le reste. acteurs_origine (genèse du lieu)
    # les accompagne comme ouverture naturelle de l'entretien.
    ancrage_debut=3,
    sections=[
        section_localisation_identite,
        section_acteurs_origine,
        section_activites,
        section_activites_alimentaires,
        section_culture_detail,
        section_services_detailles,
        section_formations,
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
        Field("isolation_ressentie", "Comment jugez-vous l'isolation du/des bâtiment(s) occupé(s) (toit, murs, sol) ?",
              FieldType.SINGLE_CHOICE, options=["Bien isolé", "Moyennement isolé", "Mal isolé", "Je ne sais pas"]),
        Field("actions_efficacite_energetique", "Quelles actions ont été mises en place pour améliorer l'efficacité "
                                                 "énergétique des bâtiments (réhabilitation, isolation, énergies "
                                                 "renouvelables...) ?", FieldType.TEXTAREA),
        Field("mise_normes_realisee", "Des mises aux normes (incendie, AFSCA...) ont-elles été réalisées récemment ? "
                                       "Lesquelles ?", FieldType.TEXTAREA),
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
        Field("effets_revitalisation_quartier", "Le lieu a-t-il contribué à revitaliser un quartier ou un village "
                                                  "(friche réhabilitée, bâtiment ou gare désaffectée...) ou à attirer "
                                                  "de nouveaux profils (freelances, artistes, néo-ruraux...) ?",
              FieldType.TEXTAREA),
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
        Field("stade_developpement", "Parmi ces étapes, lesquelles considérez-vous comme déjà franchies par le lieu ?",
              FieldType.MULTI_CHOICE,
              options=["Vision et raison d'être établies", "Foncier acquis ou occupé", "Budget consolidé",
                       "Communauté d'usagers mobilisée", "Partenariats noués", "Activités lancées",
                       "Quelques années d'expériences", "Expansion planifiée",
                       "Tiers-lieu abouti, solide et renforcé"]),
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
              FieldType.MULTI_CHOICE, options=OPTIONS_SOUTIEN_ACCOMPAGNEMENT),
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
        # Deuxième palier, hiérarchisé sous les 4 questions ci-dessus (le
        # dossier minimal) : approfondir n'est proposé qu'à qui le souhaite,
        # plutôt que d'allonger le dossier de base pour tout le monde.
        Field("candidat_approfondir_dossier",
              "Souhaitez-vous dès à présent détailler davantage votre candidature (quelques questions "
              "supplémentaires) ? Vous pourrez aussi le faire plus tard.", FieldType.BOOLEAN,
              condition=Condition("interet_learning_expedition", "eq", "Oui, je souhaite déposer un dossier")),
        Field("candidat_cooperations_actuelles",
              "Décrivez brièvement vos coopérations territoriales actuelles : avec qui, sur quoi ?",
              FieldType.TEXTAREA,
              help_text="Complète ce qui est déjà connu via les partenariats déclarés (section "
                        "Partenariats territoriaux) — inutile de tout relister, l'idée est de mettre en "
                        "avant ce qui est le plus pertinent pour une learning expedition.",
              condition=Condition("candidat_approfondir_dossier", "eq", True)),
        Field("candidat_perennite",
              "En quoi votre lieu est-il aujourd'hui pérenne, ou vise-t-il à le devenir ? Qu'est-ce qui "
              "vous rend confiant·e (ou non) sur la durabilité du projet ?", FieldType.TEXTAREA,
              help_text="Peut faire écho à ce qui a déjà été dit sur les difficultés financières ou la "
                        "dépendance à un financeur unique (section Modèle économique).",
              condition=Condition("candidat_approfondir_dossier", "eq", True)),
        Field("candidat_angle_deploiement",
              "Quel est le prochain axe de développement que vous envisagez pour le lieu ?", FieldType.TEXTAREA,
              help_text="En lien avec la vision à 5 ans si elle a déjà été exprimée (module Diagnostic).",
              condition=Condition("candidat_approfondir_dossier", "eq", True)),
        Field("candidat_besoins_deploiement",
              "Quels types de besoins sont associés à ce développement ?", FieldType.MULTI_CHOICE,
              options=OPTIONS_SOUTIEN_ACCOMPAGNEMENT,
              condition=Condition("candidat_approfondir_dossier", "eq", True)),
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


def champ_public(champ_id: str) -> bool:
    """Un champ n'est exposable publiquement (API, synthèse publique) que s'il
    existe dans le questionnaire, n'est pas confidentiel par défaut et est
    ouvert à tous les rôles — un champ inconnu (ancien schéma) est exclu par
    prudence."""
    champ = get_field(champ_id)
    if champ is None or champ.confidential_default:
        return False
    return champ.roles is None or set(TOUS_ROLES) <= set(champ.roles)


_LABELS_BY_FIELD_ID = {f.id: f.label for _, _, f in all_fields()}


def field_label(champ_id: str) -> str:
    """Libellé lisible d'un champ (les champs libres "libre::<texte>" portent
    leur libellé dans leur identifiant). Ici plutôt que dans annuaire.py, qui
    dépend de Streamlit : l'API (src/api) doit pouvoir l'utiliser sans."""
    if champ_id.startswith("libre::"):
        return champ_id[len("libre::"):].strip() or champ_id
    return _LABELS_BY_FIELD_ID.get(champ_id, champ_id)
