"""Boucle agent Claude pour l'entretien de collecte.

Usage CLI (pour tester avant de brancher Streamlit) :
    python -m src.agent.collecte_agent --lieu "Le Hangar" --pays France --role fondateur
"""

from __future__ import annotations

import argparse
import json
import os

from anthropic import Anthropic
from dotenv import load_dotenv

from ..db.factory import get_admin_store
from ..questionnaire.schema import Role
from .caching import apply_single_cache_breakpoint, cached_system, to_plain_content
from .collecte_tools import TOOL_DEFINITIONS, CollecteToolHandler
from .usage import log_usage

SYSTEM_PROMPT = """Tu es l'agent d'entretien de la plateforme "Lieux hybrides et territoires".
Ton rôle est de recueillir, par une conversation naturelle en français, le portrait d'un
tiers-lieu — pas de faire remplir un formulaire.

Règles :
- Utilise le tool `get_current_section` pour savoir quelles questions poser, et
  seulement celles-ci. Ne les lis jamais telles quelles : reformule-les
  naturellement, adapte le ton à ce que le répondant vient de dire.
- UNE SEULE question à la fois, jamais plusieurs regroupées dans un même
  message — même si `get_current_section` en renvoie plusieurs d'un coup.
  Pose la première, attends la réponse, enchaîne sur la suivante.
- Quand tu commences une nouvelle section (nouveau thème : activités,
  gouvernance, foncier, modèle économique...), annonce brièvement le thème
  avant la première question de cette section (une phrase, pas un
  paragraphe) — ex. "Passons maintenant aux activités du lieu." Fais-le
  uniquement au changement de section, pas à chaque question.
- Un champ n'apparaissant pas dans `get_current_section` ne doit jamais être
  posé (il a été exclu car non pertinent pour ce rôle, ce pays, ou l'état
  actuel des réponses).
- Appelle `save_answer` dès qu'une réponse claire a été donnée pour un champ
  actif. Si la réponse est ambiguë, demande une clarification avant
  d'enregistrer.
- Si le répondant raconte quelque chose d'intéressant qui ne correspond à
  aucun champ précis (anecdote, ressenti, contexte), capture-le avec
  `save_free_text_note` sans interrompre le fil de la conversation.
- Quand une section est terminée, enchaîne naturellement sur la suivante
  (avec son annonce de thème) sans redemander la permission à chaque fois.
- Quand un module optionnel est proposé (Impact ou Diagnostic), demande
  explicitement au répondant s'il souhaite continuer ; utilise
  `skip_optional_module` s'il décline.
- Le répondant peut interrompre à tout moment ; ne redemande jamais une
  information déjà enregistrée précédemment.
- Si un résumé de ce qui est déjà connu sur ce lieu t'est fourni en début de
  conversation, commence par le restituer brièvement (2-3 phrases) pour que
  le répondant sache d'où l'entretien repart, avant d'enchaîner sur la
  section suivante — ne redemande jamais une information déjà présente dans
  ce résumé.
- Reste chaleureux et concret, comme un entretien mené par une personne qui
  s'intéresse sincèrement au projet — pas comme un robot qui lit un script.
"""


class CollecteAgent:
    def __init__(self, tool_handler: CollecteToolHandler, model: str = "claude-sonnet-5",
                 store=None, tiers_lieu_id: str | None = None):
        self.client = Anthropic()
        self.model = model
        self.tool_handler = tool_handler
        self.messages: list = []
        self.store = store
        self.tiers_lieu_id = tiers_lieu_id

    def send(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        return self._run_until_text()

    def _run_until_text(self) -> str:
        while True:
            apply_single_cache_breakpoint(self.messages)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2500,
                system=cached_system(SYSTEM_PROMPT),
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
            )
            if self.store is not None:
                log_usage(self.store, "entretien", self.model, response.usage, self.tiers_lieu_id)
            self.messages.append({"role": "assistant", "content": to_plain_content(response.content)})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text_blocks = [b.text for b in response.content if b.type == "text"]
                return "\n".join(text_blocks)

            tool_results = []
            for tu in tool_uses:
                result = self.tool_handler.execute(tu.name, tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
            self.messages.append({"role": "user", "content": tool_results})


def opening_message(store, tiers_lieu_id: str) -> str:
    """Message d'ouverture envoyé à l'agent pour démarrer la conversation.
    Si une donnée dérivée existe déjà pour ce lieu (reprise en tant que
    steward ou nouveau contributeur sur un lieu déjà avancé), on l'inclut
    pour que l'agent restitue un micro-résumé avant d'enchaîner sur les
    questions encore ouvertes plutôt que de repartir de zéro."""
    derive = store.get_lieu_derive(tiers_lieu_id)
    if derive and derive.donnees.get("resume"):
        return (
            "Je reprends l'entretien sur un lieu déjà partiellement documenté. "
            f"Voici ce qu'on sait déjà : {derive.donnees['resume']}\n\n"
            "Restitue ce résumé en 2-3 phrases pour le répondant afin qu'il sache d'où on "
            "repart, puis enchaîne sur les informations encore manquantes."
        )
    return "Bonjour, je suis prêt à commencer l'entretien."


def build_agent(lieu_nom: str, pays: str, role_str: str, owner_user_id: str = "cli-user") -> CollecteAgent:
    store = get_admin_store()
    tiers_lieu = store.get_or_create_tiers_lieu(owner_user_id, lieu_nom)
    if pays and not tiers_lieu.pays:
        store.update_tiers_lieu(tiers_lieu.id, pays=pays)
    role = Role(role_str)
    contributeur = store.get_or_create_contributeur(owner_user_id, tiers_lieu.id, role.value)
    session = store.get_or_start_session(tiers_lieu.id, contributeur.id)
    handler = CollecteToolHandler(store, tiers_lieu.id, contributeur.id, session, role)
    return CollecteAgent(handler, store=store, tiers_lieu_id=tiers_lieu.id)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--lieu", required=True)
    parser.add_argument("--pays", default="France")
    parser.add_argument("--role", default="fondateur",
                         choices=[r.value for r in Role])
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY n'est pas défini (voir .env.example).")
        return

    agent = build_agent(args.lieu, args.pays, args.role)
    print(f"Entretien démarré pour '{args.lieu}' ({args.pays}), rôle: {args.role}.")
    print("Tapez 'exit' pour quitter (la session reprendra où vous l'avez laissée).\n")

    opening = agent.send(opening_message(agent.store, agent.tiers_lieu_id))
    print(f"Agent: {opening}\n")

    while True:
        try:
            user_input = input("Vous: ")
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.strip().lower() in {"exit", "quit"}:
            break
        reply = agent.send(user_input)
        print(f"\nAgent: {reply}\n")


if __name__ == "__main__":
    main()
