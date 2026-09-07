"""Estimation de coût et journalisation des appels LLM (table `llm_calls`),
pour un suivi budgétaire réel au fil de la montée en charge — voir §6/§10 du
plan d'architecture (audit du 2026-09-07)."""

from __future__ import annotations

from typing import Optional

from ..db.store import Store

# Tarifs Anthropic (USD par million de tokens), à date de l'audit.
PRICING_PER_MILLION = {
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-opus-5": {"input": 5.00, "output": 25.00},
}


# Multiplicateurs sur le prix input de base pour les tokens de cache
# (voir la doc Anthropic sur le prompt caching : écriture ~1.25x, lecture ~0.1x).
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def estimate_cost(model: str, tokens_in: int, tokens_out: int,
                   cache_creation_tokens: int = 0, cache_read_tokens: int = 0) -> float:
    prices = PRICING_PER_MILLION.get(model)
    if not prices:
        return 0.0
    input_cost = (
        tokens_in * prices["input"]
        + cache_creation_tokens * prices["input"] * CACHE_WRITE_MULTIPLIER
        + cache_read_tokens * prices["input"] * CACHE_READ_MULTIPLIER
    ) / 1_000_000
    output_cost = (tokens_out / 1_000_000) * prices["output"]
    return input_cost + output_cost


def log_usage(store: Store, type_appel: str, model: str, usage, tiers_lieu_id: Optional[str] = None) -> None:
    """`usage` est l'objet `response.usage` du SDK Anthropic. `tokens_in` couvre
    uniquement les tokens neufs (non cachés) — cache_creation_input_tokens et
    cache_read_input_tokens sont comptés séparément avec leur propre tarif."""
    tokens_in = getattr(usage, "input_tokens", 0) or 0
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cout = estimate_cost(model, tokens_in, tokens_out, cache_creation, cache_read)
    # tokens_in enregistré inclut les tokens de cache pour que le total reste lisible
    # (nombre de tokens réellement traités), le coût lui tient compte du tarif réel de chacun.
    store.log_llm_call(type_appel, model, tokens_in + cache_creation + cache_read, tokens_out,
                        cout, tiers_lieu_id)
