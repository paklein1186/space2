"""Vérifie les fonctions pures de coût et de hash (sans appel API)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.enrichissement import compute_source_hash
from src.agent.usage import estimate_cost


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def main():
    h1 = compute_source_hash({"c1": {"champ_a": "valeur"}}, [{"texte": "note 1"}])
    h2 = compute_source_hash({"c1": {"champ_a": "valeur"}}, [{"texte": "note 1"}])
    h3 = compute_source_hash({"c1": {"champ_a": "autre valeur"}}, [{"texte": "note 1"}])
    check("Même contenu -> même hash", h1 == h2)
    check("Contenu différent -> hash différent", h1 != h3)

    cost_plain = estimate_cost("claude-sonnet-5", tokens_in=1_000_000, tokens_out=0)
    check("Coût input Sonnet 5 = 2$/1M tokens", abs(cost_plain - 2.0) < 1e-9)

    cost_cache_read = estimate_cost("claude-sonnet-5", tokens_in=0, tokens_out=0, cache_read_tokens=1_000_000)
    check("Coût cache_read = 10% du prix input (0.20$/1M)", abs(cost_cache_read - 0.20) < 1e-9)

    cost_cache_write = estimate_cost("claude-sonnet-5", tokens_in=0, tokens_out=0, cache_creation_tokens=1_000_000)
    check("Coût cache_write = 125% du prix input (2.50$/1M)", abs(cost_cache_write - 2.50) < 1e-9)

    cost_haiku = estimate_cost("claude-haiku-4-5", tokens_in=1_000_000, tokens_out=1_000_000)
    check("Coût Haiku 4.5 = 1$ + 5$ = 6$ pour 1M in + 1M out", abs(cost_haiku - 6.0) < 1e-9)

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
