"""Boucle agent Claude pour l'assistant RAG (analyse du corpus + des données
collectées). Voir collecte_agent.py pour l'agent qui mène les entretiens —
les deux partagent le même store et donc les mêmes données collectées.
"""

from __future__ import annotations

import json
from typing import Optional

from anthropic import Anthropic

from .caching import apply_single_cache_breakpoint, cached_system, to_plain_content
from .rag_tools import TOOL_DEFINITIONS, RagToolHandler
from .usage import log_usage

SYSTEM_PROMPT = """Tu es l'assistant d'analyse de la plateforme "Lieux hybrides et territoires".
Tu réponds en français à des questions sur les tiers-lieux recensés, en t'appuyant sur :
- `search_knowledge_base` pour trois types de contenu vectorisé, à choisir selon la question :
  le profil sémantique de chaque lieu (doc_type "profil_lieu", pour "quels lieux travaillent
  sur...", "lieux avec une approche comparable à...") ; les interviews et rapports déposés
  (doc_type "interview"/"rapport", pour retrouver un passage précis) ; les résumés de
  datasets/géodonnées déposés (doc_type "dataset_summary"/"geodata").
- `list_datasets` et `query_structured_data` pour toute question chiffrée ou statistique
  précise (ne jamais inventer un chiffre : passe toujours par ces tools).

Cite systématiquement tes sources (nom du lieu, nom de fichier, ou "données collectées via
l'entretien") sous ta réponse. Si l'information demandée n'est pas trouvable via les tools,
dis-le clairement plutôt que de deviner.
"""


class RagAgent:
    def __init__(self, tool_handler: RagToolHandler, model: str = "claude-sonnet-5", store=None):
        self.client = Anthropic()
        self.model = model
        self.tool_handler = tool_handler
        self.messages: list = []
        self.store = store or getattr(tool_handler, "store", None)

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
                log_usage(self.store, "rag_query", self.model, response.usage)
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
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            self.messages.append({"role": "user", "content": tool_results})
