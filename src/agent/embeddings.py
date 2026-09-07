"""Wrapper Voyage AI pour les embeddings du RAG. Modèle multilingue (adapté
au français) recommandé par Anthropic pour l'usage avec Claude.

Retry avec backoff sur les erreurs de rate limit : le palier gratuit Voyage
sans moyen de paiement enregistré est plafonné à 3 requêtes/minute, ce qui se
déclenche facilement en usage interactif (chaque question RAG peut appeler
`search_knowledge_base`). Ajouter un moyen de paiement sur
https://dashboard.voyageai.com/ lève cette limite (les tokens gratuits
restent acquis) — ce retry absorbe les pics en attendant.
"""

from __future__ import annotations

import os

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from voyageai.error import RateLimitError

MODEL = "voyage-multilingual-2"
BATCH_SIZE = 128

_retry_on_rate_limit = retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=5, min=5, max=60),
    stop=stop_after_attempt(6),
    reraise=True,
)


class VoyageEmbedder:
    def __init__(self, api_key: str | None = None):
        import voyageai

        self.client = voyageai.Client(api_key=api_key or os.environ.get("VOYAGE_API_KEY"))

    @_retry_on_rate_limit
    def embed_documents(self, texts: list) -> list:
        embeddings: list = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            result = self.client.embed(batch, model=MODEL, input_type="document")
            embeddings.extend(result.embeddings)
        return embeddings

    @_retry_on_rate_limit
    def embed_query(self, text: str) -> list:
        result = self.client.embed([text], model=MODEL, input_type="query")
        return result.embeddings[0]
