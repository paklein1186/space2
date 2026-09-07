"""Import de questionnaires déjà remplis (docx/pdf), reçus hors de l'agent
conversationnel (ex. anciens questionnaires de capitalisation), vers le même
schéma que l'entretien : 1 appel LLM par document mappe le texte libre sur
les champs du module Socle, puis les réponses sont enregistrées comme si un
contributeur les avait données lui-même (donnée brute, jamais reformulée).

Usage :
    python -m src.ingest.import_questionnaire fichier1.docx fichier2.pdf ...
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from anthropic import Anthropic
from dotenv import load_dotenv

from src.agent.usage import log_usage
from src.db.factory import get_admin_store
from src.ingest.loaders import extract_text
from src.questionnaire.schema import QUESTIONNAIRE, Role, get_module

MODEL = "claude-sonnet-5"


def field_reference(country_code: str = "BE") -> list:
    """Description des champs du module Socle (id, label, type, options),
    sans filtrage par rôle — utilisée uniquement pour guider le mapping."""
    module = get_module("socle")
    fields = []
    for section in module.sections:
        for f in section.fields:
            fields.append({
                "id": f.id,
                "label": f.label,
                "type": f.type.value,
                "options": f.resolved_options(country_code),
            })
    return fields


EXTRACTION_PROMPT_TEMPLATE = """Voici la liste des champs disponibles pour décrire un tiers-lieu (id, libellé, type, options) :
{fields_json}

Voici le texte intégral d'un questionnaire déjà rempli par un tiers-lieu :
---
{document_text}
---

Extrais les réponses présentes dans ce texte et mappe-les sur les champs ci-dessus.
Règles strictes :
- Ne réponds QUE pour les champs dont l'information est clairement présente dans le texte.
  N'invente jamais une valeur absente.
- Pour un champ de type single_choice/multi_choice, choisis parmi les "options" fournies
  celle(s) qui correspond(ent) le mieux au texte, ou "Autre" si rien ne convient. Pour
  multi_choice, renvoie une liste même s'il n'y a qu'un élément.
- Pour un champ number, renvoie uniquement la valeur numérique (pas d'unité).
- Pour un champ boolean, renvoie true/false uniquement si le texte est explicite.
- Capture tout élément qualitatif intéressant qui ne correspond à aucun champ précis
  (contexte, anecdote, difficulté rencontrée...) dans "notes_libres".

Réponds UNIQUEMENT avec un objet JSON de cette forme, sans texte autour :
{{"nom_lieu": "...", "reponses": {{"champ_id": valeur, ...}}, "notes_libres": ["...", ...]}}
"""


def extract_answers(document_text: str, country_code: str = "BE") -> dict:
    client = Anthropic()
    fields = field_reference(country_code)
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        fields_json=json.dumps(fields, ensure_ascii=False), document_text=document_text[:40000]
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "disabled"},
        messages=[{"role": "user", "content": prompt}],
    )
    store = get_admin_store()
    log_usage(store, "import_questionnaire", MODEL, response.usage)

    text = "".join(b.text for b in response.content if b.type == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def import_file(path: Path, owner_user_id: str = "import-drive", pays: str = "Belgique",
                 role: str = "fondateur", confidentiel: bool = False) -> str:
    print(f"[import] {path.name}")
    document_text = extract_text(path)
    if not document_text.strip():
        print("  (texte vide, ignoré)")
        return ""

    result = extract_answers(document_text, country_code="BE" if pays == "Belgique" else "FR")
    nom_lieu = result.get("nom_lieu") or path.stem
    reponses = result.get("reponses", {})
    notes = result.get("notes_libres", [])

    store = get_admin_store()
    tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, nom_lieu)
    store.update_tiers_lieu(tiers_lieu.id, pays=pays)
    contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, role)

    valid_field_ids = {f["id"] for f in field_reference()}
    saved = 0
    for champ_id, valeur in reponses.items():
        if champ_id not in valid_field_ids:
            print(f"  champ inconnu ignoré: {champ_id}")
            continue
        store.save_answer(tiers_lieu.id, contributeur.id, champ_id, valeur, confidentiel)
        saved += 1
    for note in notes:
        store.save_free_text_note(tiers_lieu.id, contributeur.id, None, note)

    print(f"  -> lieu '{nom_lieu}' : {saved} champs enregistrés, {len(notes)} notes libres")
    return tiers_lieu.id


def main():
    load_dotenv()
    if len(sys.argv) < 2:
        print("Usage: python -m src.ingest.import_questionnaire <fichier1> [fichier2 ...]")
        return
    for arg in sys.argv[1:]:
        import_file(Path(arg))


if __name__ == "__main__":
    main()
