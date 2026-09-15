"""Résolution du questionnaire conditionnel.

Toute la logique de filtrage (conditions, localisation, rôle) vit ici, en
Python pur — l'agent Claude ne reçoit que des sections déjà résolues, pas le
schéma complet ni les règles de branchement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

from .schema import QUESTIONNAIRE, Field, Module, Role, Section

COUNTRY_NAME_TO_CODE = {"France": "FR", "Belgique": "BE"}


def country_code_for(pays_label: Optional[str]) -> Optional[str]:
    if not pays_label:
        return None
    return COUNTRY_NAME_TO_CODE.get(pays_label)


@dataclass
class ResolvedField:
    field: Field
    options: Optional[list]

    @property
    def id(self) -> str:
        return self.field.id


def section_is_active(section: Section, answers: dict) -> bool:
    if section.condition is None:
        return True
    return section.condition.evaluate(answers)


def field_is_active(f: Field, answers: dict, role: Optional[Role]) -> bool:
    """`role=None` ignore la restriction de rôle (traite le champ comme actif
    pour n'importe qui) — utilisé pour une vue agrégée tous-rôles-confondus,
    par exemple la complétion d'un lieu dont les réponses viennent de
    plusieurs contributeurs de rôles différents."""
    if role is not None and not f.allowed_for(role):
        return False
    if f.condition is None:
        return True
    return f.condition.evaluate(answers)


def resolve_section_fields(section: Section, answers: dict, role: Role, country_code: Optional[str]) -> list:
    """Renvoie la liste des ResolvedField actuellement actifs pour cette section."""
    resolved = []
    for f in section.fields:
        if not field_is_active(f, answers, role):
            continue
        resolved.append(ResolvedField(field=f, options=f.resolved_options(country_code)))
    return resolved


def section_is_complete(section: Section, answers: dict, role: Role, country_code: Optional[str]) -> bool:
    """Une section est complète quand tous ses champs actifs et requis ont une réponse
    (les champs non requis n'empêchent pas de passer à la suite)."""
    for rf in resolve_section_fields(section, answers, role, country_code):
        if rf.field.required and answers.get(rf.field.id) is None:
            return False
    return True


def _rang_pseudo_aleatoire(seed: str, section_id: str) -> str:
    """Rang stable et pseudo-aléatoire pour une section donnée un `seed`
    donné — même section + même seed renvoie toujours le même rang (ordre
    stable au sein d'une session), mais le classement diffère d'un seed
    (donc d'un entretien) à l'autre. Pas besoin de porter un générateur
    aléatoire avec état : un simple hash suffit et reste calculable à la
    volée, y compris après reprise d'une session interrompue."""
    return hashlib.md5(f"{seed}:{section_id}".encode()).hexdigest()


def next_incomplete_section(module: Module, answers: dict, role: Role, country_code: Optional[str],
                             completed_section_ids: set, seed: Optional[str] = None) -> Optional[Section]:
    """Renvoie la prochaine section à traiter parmi celles actives et non
    terminées. Sans `seed`, l'ordre déclaré dans le schéma fait foi (utilisé
    par les tests et tout appelant qui n'a pas de session à identifier).

    Avec un `seed` (typiquement l'id du contributeur), les sections situées
    au-delà de `module.ancrage_debut` sont proposées dans un ordre
    pseudo-aléatoire propre à ce seed plutôt que toujours le même — pour
    qu'un même parcours ne se déroule pas de façon identique à chaque
    entretien, tout en gardant l'entrée en matière (et les sections qui
    déclenchent des branches conditionnelles) dans un ordre prévisible. Les
    conditions d'activation restent seules responsables de ce qui PEUT être
    proposé ; ce tirage ne choisit qu'entre des sections déjà également
    valides à cet instant.

    Parmi ces candidates, une section conditionnelle (`section.condition`
    renseigné) vient toujours d'être débloquée par une réponse précise —
    elle reste prioritaire sur les sections génériques (sans condition,
    actives dès le départ) pour enchaîner dessus tant que c'est encore dans
    le fil de la conversation, plutôt que de sauter directement à une
    section sans rapport ; le tirage aléatoire ne s'applique qu'au sein de
    chacun des deux groupes."""
    candidats = [s for s in module.sections
                 if s.id not in completed_section_ids and section_is_active(s, answers)]
    if not candidats:
        return None
    if seed is None:
        return candidats[0]
    ancrage_ids = {s.id for s in module.sections[:module.ancrage_debut]}
    ancres = [s for s in candidats if s.id in ancrage_ids]
    if ancres:
        return ancres[0]
    conditionnelles = [s for s in candidats if s.condition is not None]
    groupe = conditionnelles or candidats
    return min(groupe, key=lambda s: _rang_pseudo_aleatoire(seed, s.id))


def module_is_complete(module: Module, answers: dict, role: Role, country_code: Optional[str],
                        completed_section_ids: set, seed: Optional[str] = None) -> bool:
    return next_incomplete_section(module, answers, role, country_code, completed_section_ids, seed) is None


def completion_stats(answers: dict, role: Optional[Role], country_code: Optional[str]) -> dict:
    """Taux de complétion du questionnaire pour cet état de réponses : parmi
    les champs actuellement ACTIFS (compte tenu du rôle, du pays, et des
    branches conditionnelles déjà révélées par les réponses données), quelle
    proportion a une réponse. Un champ dont la condition n'est pas encore
    remplie ne compte pas dans le total — il ne pénalise pas le répondant
    pour une branche qui ne le concerne pas (ou pas encore).

    Volontairement basé sur TOUS les champs actifs (pas seulement les
    champs requis) : la demande est une mesure de profondeur ("à quel degré
    de profondeur" un lieu a été complété), pas juste de savoir si le
    minimum obligatoire est rempli.

    `role=None` (vue admin) agrège tous rôles confondus : les réponses d'un
    lieu proviennent typiquement de plusieurs contributeurs de rôles
    différents (voir Store.get_answers, vue fusionnée), donc restreindre à
    UN rôle sous-compterait les champs réservés aux autres.
    """
    total = 0
    repondus = 0
    par_module = []
    for module in QUESTIONNAIRE:
        m_total = 0
        m_repondus = 0
        for section in module.sections:
            if not section_is_active(section, answers):
                continue
            for f in section.fields:
                if not field_is_active(f, answers, role):
                    continue
                m_total += 1
                if answers.get(f.id) is not None:
                    m_repondus += 1
        par_module.append({
            "module_id": module.id, "titre": module.title,
            "total": m_total, "repondus": m_repondus,
            "pourcentage": round(100 * m_repondus / m_total) if m_total else 0,
        })
        total += m_total
        repondus += m_repondus
    return {
        "total": total, "repondus": repondus,
        "pourcentage": round(100 * repondus / total) if total else 0,
        "par_module": par_module,
    }


def next_module(current_module_id: Optional[str]) -> Optional[Module]:
    ids = [m.id for m in QUESTIONNAIRE]
    if current_module_id is None:
        return QUESTIONNAIRE[0]
    try:
        idx = ids.index(current_module_id)
    except ValueError:
        return QUESTIONNAIRE[0]
    if idx + 1 < len(QUESTIONNAIRE):
        return QUESTIONNAIRE[idx + 1]
    return None
