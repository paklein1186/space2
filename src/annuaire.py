"""Vue agrégée en lecture seule : pour chaque tiers-lieu, une fiche de
synthèse qui compile les contributions de tous les répondants (tous rôles
confondus), avec la provenance de chaque élément qualitatif, plus les
coordonnées pour une carte. Ne collecte rien — lit uniquement ce que
l'agent de collecte a déjà enregistré.
"""

from __future__ import annotations

from .db.store import Store
from .questionnaire.schema import all_fields

_LABELS_BY_FIELD_ID = {f.id: f.label for _, _, f in all_fields()}


def field_label(champ_id: str) -> str:
    return _LABELS_BY_FIELD_ID.get(champ_id, champ_id)


def build_fiche_lieu(store: Store, tiers_lieu) -> dict:
    """Compile une fiche de synthèse multi-répondants pour un lieu donné."""
    par_contributeur = store.get_all_answers_by_contributeur(tiers_lieu.id)
    notes = store.get_free_text_notes(tiers_lieu.id)

    # Regroupe par champ pour repérer les convergences/divergences entre rôles.
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
