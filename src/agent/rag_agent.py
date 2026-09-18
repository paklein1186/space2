"""Boucle agent Claude pour l'assistant RAG (analyse du corpus + des données
collectées). Voir collecte_agent.py pour l'agent qui mène les entretiens —
les deux partagent le même store et donc les mêmes données collectées.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
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

`reponses_tiers_lieux` est un format LONG : une ligne par (lieu, champ, valeur), pas une
colonne par question. Ses colonnes ("champ", "champ_id", "valeur"...) listées par
`list_datasets` sont donc TOUJOURS les mêmes génériques, quelle que soit la question
concernée — ce n'est PAS la liste des questions posées, et son absence de la description du
dataset ne veut RIEN dire sur l'existence de données. Avant de conclure qu'une donnée
précise (un effectif, une date, un statut...) n'existe pas : filtre réellement ce dataset sur
la colonne "champ" avec `contains` et un mot-clé du sujet (ex. {"column": "champ", "op":
"contains", "value": "temps plein"} pour une question sur les ETP) — seul un filtre qui ne
renvoie AUCUNE ligne permet de dire que la donnée n'a pas été collectée. Ne te fie jamais à
la description générale d'un dataset pour ça, et ne confonds jamais `reponses_tiers_lieux`
(réponses brutes, tous champs du questionnaire) avec `lieux_enrichis` (résumé dérivé, une
poignée de catégories seulement) — l'absence d'un sujet dans les colonnes du second ne dit
rien sur sa présence dans le premier.

Cite systématiquement tes sources (nom du lieu, nom de fichier, ou "données collectées via
l'entretien") sous ta réponse. Si l'information demandée n'est vraiment pas trouvable après
avoir réellement interrogé les tools (pas juste consulté leur description), dis-le
clairement plutôt que de deviner.
"""


class RagAgent:
    def __init__(self, tool_handler: RagToolHandler, model: str = "claude-sonnet-5", store=None):
        # Timeout explicite : voir la même note dans collecte_agent.py /
        # enrichissement.py — sans lui, une requête sans réponse peut bloquer
        # l'interface indéfiniment plutôt que d'échouer proprement.
        self.client = Anthropic(timeout=60.0)
        self.model = model
        self.tool_handler = tool_handler
        self.messages: list = []
        self.store = store or getattr(tool_handler, "store", None)

    def send(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        return self._run_until_text()

    def send_stream(self, user_text: str):
        """Variante génératrice de send() — voir la même note dans
        collecte_agent.py. Le tour qui appelle search_knowledge_base/
        list_datasets/query_structured_data (le cas courant en début de
        réponse) ne cède aucun texte tant que ces tools n'ont pas répondu ;
        le texte final commence ensuite à s'afficher au fil de l'eau."""
        self.messages.append({"role": "user", "content": user_text})
        while True:
            apply_single_cache_breakpoint(self.messages)
            with self.client.messages.stream(
                model=self.model,
                max_tokens=8000,
                system=cached_system(SYSTEM_PROMPT),
                tools=TOOL_DEFINITIONS,
                messages=self.messages,
            ) as stream:
                yield from stream.text_stream
                final_message = stream.get_final_message()

            if self.store is not None:
                log_usage(self.store, "rag_query", self.model, final_message.usage)
            self.messages.append({"role": "assistant", "content": to_plain_content(final_message.content)})

            tool_uses = [b for b in final_message.content if b.type == "tool_use"]
            if not tool_uses:
                if final_message.stop_reason == "max_tokens":
                    yield ("\n\n*(Réponse interrompue — trop longue pour être générée en une fois. "
                           "Redemandez « continue » pour la suite, ou reformulez une question plus ciblée.)*")
                return

            self.messages.append({"role": "user", "content": self._executer_tool_uses(tool_uses)})

    def _executer_tool_uses(self, tool_uses: list) -> list:
        """Exécute tous les tool_use d'un même tour — en parallèle plutôt
        qu'en séquence quand Claude en demande plusieurs à la fois (ex.
        search_knowledge_base sur deux doc_type, ou list_datasets +
        query_structured_data ensemble) : ce sont tous des appels réseau
        indépendants et en lecture seule (Chroma/Voyage/Supabase), sans état
        partagé — les paralléliser réduit directement la latence perçue, qui
        s'additionnait sinon appel après appel (constaté en production :
        20-30s sur une question déclenchant plusieurs tools). Partagée entre
        send() et send_stream() : même logique, un seul endroit à maintenir."""
        def _executer(tu):
            # Une exception non rattrapée ici laisserait ce message assistant
            # (avec ses tool_use) sans tool_result correspondant — non
            # seulement ça fait planter la page en cours, mais la
            # conversation stockée dans self.messages reste corrompue : le
            # PROCHAIN message de l'utilisateur renvoie alors une erreur 400
            # de l'API ("tool_use ids were found without tool_result
            # blocks"). Convertir toute exception en résultat d'erreur normal
            # évite les deux.
            try:
                return self.tool_handler.execute(tu.name, tu.input)
            except Exception as exc:
                return {"error": f"{type(exc).__name__}: {exc}"}

        if len(tool_uses) == 1:
            resultats = [_executer(tool_uses[0])]
        else:
            with ThreadPoolExecutor(max_workers=len(tool_uses)) as executor:
                resultats = list(executor.map(_executer, tool_uses))

        return [
            {
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
            }
            for tu, result in zip(tool_uses, resultats)
        ]

    def _run_until_text(self) -> str:
        while True:
            apply_single_cache_breakpoint(self.messages)
            response = self.client.messages.create(
                model=self.model,
                # 2500 coupait net des réponses légitimement longues (liste
                # de contacts/lieux, synthèse détaillée) en plein milieu
                # d'une phrase — constaté en production, sans aucun signal
                # que la réponse était incomplète.
                max_tokens=8000,
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
                texte = "\n".join(text_blocks)
                if response.stop_reason == "max_tokens":
                    texte += ("\n\n*(Réponse interrompue — trop longue pour être générée en une fois. "
                              "Redemandez « continue » pour la suite, ou reformulez une question plus ciblée.)*")
                return texte

            self.messages.append({"role": "user", "content": self._executer_tool_uses(tool_uses)})
