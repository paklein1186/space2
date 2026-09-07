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


def field_is_active(f: Field, answers: dict, role: Role) -> bool:
    if not f.allowed_for(role):
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
