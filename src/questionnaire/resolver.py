"""Résolution du questionnaire conditionnel.

Toute la logique de filtrage (conditions, localisation, rôle) vit ici, en
Python pur — l'agent Claude ne reçoit que des sections déjà résolues, pas le
schéma complet ni les règles de branchement.
"""

from __future__ import annotations

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


def next_incomplete_section(module: Module, answers: dict, role: Role, country_code: Optional[str],
                             completed_section_ids: set) -> Optional[Section]:
    for section in module.sections:
        if section.id in completed_section_ids:
            continue
        if not section_is_active(section, answers):
            continue
        return section
    return None


def module_is_complete(module: Module, answers: dict, role: Role, country_code: Optional[str],
                        completed_section_ids: set) -> bool:
    return next_incomplete_section(module, answers, role, country_code, completed_section_ids) is None


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
