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
# Marge sous la limite Voyage de 120 000 tokens par batch — atteinte en
# pratique bien avant BATCH_SIZE textes sur un document long découpé en
# chunks de ~1000 caractères (vécu : un guide PDF, 128 chunks ~= 123 000
# tokens, requête rejetée par Voyage).
MAX_TOKENS_PAR_LOT = 100_000

_retry_on_rate_limit = retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=5, min=5, max=60),
    stop=stop_after_attempt(6),
    reraise=True,
)


class VoyageEmbedder:
    def __init__(self, api_key: str | None = None):
        import voyageai

        # Timeout explicite : sans lui, une requête sans réponse peut bloquer
        # indéfiniment un enrichissement en masse au lieu d'échouer proprement.
        # .strip() : une clé collée avec un retour à la ligne final (vécu sur
        # Render) rend Voyage inutilisable — « Invalid leading whitespace,
        # reserved character(s), or return character(s) in header value ».
        cle = (api_key or os.environ.get("VOYAGE_API_KEY") or "").strip().strip("\"'") or None
        self.client = voyageai.Client(api_key=cle, timeout=60.0)

    @_retry_on_rate_limit
    def embed_documents(self, texts: list) -> list:
        embeddings: list = []
        lot: list = []
        tokens_lot = 0
        for texte in texts:
            tokens_texte = self.client.count_tokens([texte], model=MODEL)
            if lot and (len(lot) >= BATCH_SIZE or tokens_lot + tokens_texte > MAX_TOKENS_PAR_LOT):
                embeddings.extend(self.client.embed(lot, model=MODEL, input_type="document").embeddings)
                lot, tokens_lot = [], 0
            lot.append(texte)
            tokens_lot += tokens_texte
        if lot:
            embeddings.extend(self.client.embed(lot, model=MODEL, input_type="document").embeddings)
        return embeddings

    @_retry_on_rate_limit
    def embed_query(self, text: str) -> list:
        result = self.client.embed([text], model=MODEL, input_type="query")
        return result.embeddings[0]
