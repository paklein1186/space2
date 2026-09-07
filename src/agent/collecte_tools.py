"""Tools Claude pour l'agent de collecte : démarrage/reprise de session,
lecture de la section courante (déjà résolue), sauvegarde des réponses et
des notes libres. Toute la logique conditionnelle est déléguée à
`questionnaire.resolver` — l'agent ne voit jamais le schéma brut.

La progression (module courant, section courante, sections déjà terminées)
est chargée depuis la session persistée à l'initialisation, ce qui permet une
reprise exacte après interruption — voir `db.store.SessionEntretien`.
"""

from __future__ import annotations

from typing import Optional

from ..db.store import SessionEntretien, Store
from ..questionnaire.resolver import (
    country_code_for,
    next_incomplete_section,
    next_module,
    resolve_section_fields,
    section_is_complete,
)
from ..questionnaire.schema import QUESTIONNAIRE, Role, get_module, get_section

TOOL_DEFINITIONS = [
    {
        "name": "get_current_section",
        "description": (
            "Renvoie la section actuellement à traiter dans l'entretien (titre, "
            "introduction, et la liste des questions actives pour ce répondant "
            "précis — déjà filtrées selon son rôle, le pays du lieu, et les "
            "réponses déjà données). Appeler ce tool au début de la conversation "
            "et après chaque changement de section."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_answer",
        "description": (
            "Enregistre la réponse d'un champ du schéma pour ce répondant. "
            "N'appeler que pour un champ effectivement retourné par "
            "get_current_section. Après l'appel, vérifier si la section est "
            "complète (le résultat l'indique) avant de continuer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "champ_id": {"type": "string", "description": "id exact du champ, tel que renvoyé par get_current_section"},
                "valeur": {"description": "valeur donnée par le répondant (texte, nombre, booléen, ou liste pour un choix multiple)"},
                "confidentiel": {"type": "boolean", "description": "true si le répondant souhaite que cette donnée reste confidentielle (par défaut la valeur par défaut du champ s'applique)"},
            },
            "required": ["champ_id", "valeur"],
        },
    },
    {
        "name": "save_free_text_note",
        "description": (
            "Capture un témoignage, une anecdote ou un ressenti qui sort du "
            "cadre des champs structurés du schéma — à utiliser librement dès "
            "que le répondant partage quelque chose d'intéressant qui ne rentre "
            "dans aucun champ précis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texte": {"type": "string"},
                "section_id": {"type": "string", "description": "section en cours, si pertinent"},
            },
            "required": ["texte"],
        },
    },
    {
        "name": "skip_optional_module",
        "description": (
            "À appeler si le répondant décline explicitement de continuer avec "
            "le module optionnel proposé (Impact ou Diagnostic). Passe à la "
            "suite ou termine l'entretien s'il n'y a plus de module."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"module_id": {"type": "string", "enum": ["impact", "diagnostic"]}},
            "required": ["module_id"],
        },
    },
]


class CollecteToolHandler:
    """Lie les tools ci-dessus à une session concrète (lieu + contributeur + rôle).

    La progression est initialisée depuis `session` (chargée par
    `store.get_or_start_session`), pas recalculée par déduction — c'est ce qui
    garantit une reprise exacte, y compris pour une section dont tous les
    champs seraient optionnels (qui serait sinon considérée "complète" à tort
    dès qu'on la regarde)."""

    def __init__(self, store: Store, tiers_lieu_id: str, contributeur_id: str, session: SessionEntretien, role: Role):
        self.store = store
        self.tiers_lieu_id = tiers_lieu_id
        self.contributeur_id = contributeur_id
        self.session_id = session.id
        self.role = role
        self._module_id: Optional[str] = session.module_courant
        self._section_id: Optional[str] = session.section_courante
        self._completed_section_ids: set = set(session.completed_sections or [])
        if self._module_id is None:
            self._enter_module(QUESTIONNAIRE[0].id, persist=False)

    def _current_answers(self) -> dict:
        return self.store.get_answers(self.tiers_lieu_id, self.contributeur_id)

    def _country_code(self) -> Optional[str]:
        answers = self._current_answers()
        return country_code_for(answers.get("pays"))

    def _persist_progress(self, statut: str = "en_cours") -> None:
        self.store.update_session_progress(
            self.session_id, self._module_id, self._section_id,
            sorted(self._completed_section_ids), statut=statut,
        )

    def _enter_module(self, module_id: str, persist: bool = True) -> None:
        """Positionne la session sur la première section active et non terminée
        de ce module (ou aucune section si le module est déjà entièrement fait)."""
        self._module_id = module_id
        answers = self._current_answers()
        section = next_incomplete_section(
            get_module(module_id), answers, self.role, self._country_code(), self._completed_section_ids
        )
        self._section_id = section.id if section else None
        if persist:
            self._persist_progress()

    def get_current_section(self, _input: dict) -> dict:
        if self._section_id is None:
            return self._advance_module(self._module_id)
        module = get_module(self._module_id)
        section = get_section(self._module_id, self._section_id)
        answers = self._current_answers()
        resolved = resolve_section_fields(section, answers, self.role, self._country_code())
        return {
            "module_id": self._module_id,
            "module_title": module.title,
            "module_optional": module.optional,
            "section_id": section.id,
            "section_title": section.title,
            "intro": section.intro,
            "fields": [
                {
                    "id": rf.id,
                    "label": rf.field.label,
                    "type": rf.field.type.value,
                    "options": rf.options,
                    "required": rf.field.required,
                    "help_text": rf.field.help_text,
                    "max_choices": rf.field.max_choices,
                }
                for rf in resolved
            ],
        }

    def save_answer(self, tool_input: dict) -> dict:
        champ_id = tool_input["champ_id"]
        valeur = tool_input["valeur"]
        confidentiel = bool(tool_input.get("confidentiel", False))
        self.store.save_answer(self.tiers_lieu_id, self.contributeur_id, champ_id, valeur, confidentiel)

        section = get_section(self._module_id, self._section_id)
        answers = self._current_answers()
        complete = section_is_complete(section, answers, self.role, self._country_code())
        result = {"saved": True, "champ_id": champ_id, "section_complete": complete}
        if complete:
            self._completed_section_ids.add(self._section_id)
            next_section = next_incomplete_section(
                get_module(self._module_id), answers, self.role, self._country_code(), self._completed_section_ids
            )
            if next_section:
                self._section_id = next_section.id
                self._persist_progress()
                result["next_section"] = self.get_current_section({})
            else:
                result.update(self._advance_module(self._module_id))
        else:
            self._persist_progress()
        return result

    def _advance_module(self, current_module_id: str) -> dict:
        nxt = next_module(current_module_id)
        if nxt is None:
            self._module_id = current_module_id
            self._section_id = None
            self._persist_progress(statut="terminee")
            return {"module_complete": True, "questionnaire_termine": True}
        self._enter_module(nxt.id)
        return {
            "module_complete": True,
            "next_module_proposed": {"id": nxt.id, "title": nxt.title, "optional": nxt.optional},
        }

    def save_free_text_note(self, tool_input: dict) -> dict:
        self.store.save_free_text_note(
            self.tiers_lieu_id, self.contributeur_id, tool_input.get("section_id"), tool_input["texte"]
        )
        return {"saved": True}

    def skip_optional_module(self, tool_input: dict) -> dict:
        module_id = tool_input["module_id"]
        return self._advance_module(module_id)

    def execute(self, tool_name: str, tool_input: dict) -> dict:
        handler = getattr(self, tool_name, None)
        if handler is None:
            return {"error": f"tool inconnu: {tool_name}"}
        return handler(tool_input)
