"""Vue agrégée en lecture seule : pour chaque tiers-lieu, une fiche de
synthèse qui compile les contributions de tous les répondants (tous rôles
confondus), avec la provenance de chaque élément qualitatif, plus les
coordonnées pour une carte. Ne collecte rien — lit uniquement ce que
l'agent de collecte / le pipeline d'enrichissement ont déjà produit.
"""

from __future__ import annotations

import hashlib

from .db.store import Store
from .questionnaire.schema import all_fields

# Palette de secours pour la vignette d'un lieu sans photo — couleur stable
# par lieu (dérivée du nom), pas aléatoire à chaque rechargement.
_PALETTE = ["#E07A5F", "#3D5A80", "#81B29A", "#F2CC8F", "#6D597A", "#B56576", "#457B9D"]
_EMOJI_PAR_MOT_CLE = [
    (("aliment", "nourric", "maraîch", "agricole", "ferme"), "🌾"),
    (("fabric", "numérique", "fablab", "makerspace", "atelier"), "🛠️"),
    (("cultur", "art", "spectacle", "musique"), "🎨"),
    (("coworking", "bureau", "travail"), "💼"),
    (("insertion", "formation", "emploi"), "🎓"),
    (("social", "solidaire", "cohésion"), "🤝"),
    (("écolog", "circulaire", "recycl", "durab"), "♻️"),
]


def default_visual(nom_lieu: str, donnees: dict | None = None) -> tuple[str, str]:
    """Vignette par défaut (emoji + couleur) quand aucune photo n'est
    renseignée — stable par lieu, dérivée de son nom et de ses mots-clés."""
    couleur = _PALETTE[int(hashlib.sha256(nom_lieu.encode("utf-8")).hexdigest(), 16) % len(_PALETTE)]
    texte_reference = ""
    if donnees:
        texte_reference = (str(donnees.get("activites", "")) + " " +
                            " ".join(donnees.get("mots_cles") or [])).lower()
    for mots, emoji in _EMOJI_PAR_MOT_CLE:
        if any(m in texte_reference for m in mots):
            return emoji, couleur
    return "🏘️", couleur

_LABELS_BY_FIELD_ID = {f.id: f.label for _, _, f in all_fields()}

# Ordre et libellés d'affichage des sections homogénéisées de l'Annuaire —
# doit correspondre à agent.enrichissement.CHAMPS_LONGUEUR_CIBLE + resume.
SECTIONS_SYNTHESE = [
    ("resume", "Résumé"),
    ("activites", "Activités"),
    ("publics", "Publics"),
    ("territoire", "Territoire"),
    ("gouvernance", "Gouvernance"),
    ("ressources", "Ressources"),
    ("besoins", "Besoins"),
    ("modele_economique", "Modèle économique"),
    ("partenaires", "Partenaires"),
    ("competences", "Compétences"),
    ("projets", "Projets"),
    ("enjeux", "Enjeux"),
]


def field_label(champ_id: str) -> str:
    return _LABELS_BY_FIELD_ID.get(champ_id, champ_id)


def build_fiche_lieu(store: Store, tiers_lieu) -> dict:
    """Compile une fiche de synthèse multi-répondants pour un lieu donné."""
    par_contributeur = store.get_all_answers_by_contributeur(tiers_lieu.id)
    notes = store.get_free_text_notes(tiers_lieu.id)

    par_champ: dict = {}
    for contributeur_id, reponses in par_contributeur.items():
        for champ_id, valeur in reponses.items():
            par_champ.setdefault(champ_id, []).append({
                "contributeur_id": contributeur_id,
                "valeur": valeur,
            })

    return {
        "tiers_lieu": tiers_lieu,
        "nombre_contributeurs": len(par_contributeur),
        "par_champ": {
            field_label(champ_id): entries for champ_id, entries in par_champ.items()
        },
        "temoignages": [
            {"section": n.get("section_id"), "texte": n["texte"]} for n in notes
        ],
    }


def source_items_for_section(store: Store, tiers_lieu_id: str, section_key: str,
                              lieu_derive) -> list:
    """Résout les identifiants de provenance d'une section de synthèse
    (lieu_derive.sources[section_key], ex. ["milieu", "note_2"]) vers leur
    contenu brut affichable dans le popup de sources."""
    if not lieu_derive or not lieu_derive.sources:
        return []
    ids = lieu_derive.sources.get(section_key, [])
    if not ids:
        return []

    notes = store.get_free_text_notes(tiers_lieu_id)
    par_contributeur = store.get_all_answers_by_contributeur(tiers_lieu_id)

    items = []
    for source_id in ids:
        if source_id.startswith("note_"):
            try:
                idx = int(source_id.split("_", 1)[1])
            except ValueError:
                continue
            if 0 <= idx < len(notes):
                items.append({"type": "note", "label": "Note libre", "valeur": notes[idx]["texte"]})
        else:
            for contributeur_id, reponses in par_contributeur.items():
                if source_id in reponses:
                    items.append({
                        "type": "reponse",
                        "label": field_label(source_id),
                        "valeur": reponses[source_id],
                        "contributeur_id": contributeur_id,
                    })
    return items


def build_annuaire(store: Store) -> list:
    """Fiches de synthèse pour tous les lieux recensés (toutes personnes confondues)."""
    lieux = store.list_tiers_lieux()
    return [build_fiche_lieu(store, lieu) for lieu in lieux]


def lieux_avec_coordonnees(store: Store) -> list:
    return [
        {"nom": l.nom, "lat": l.latitude, "lon": l.longitude}
        for l in store.list_tiers_lieux()
        if l.latitude is not None and l.longitude is not None
    ]
