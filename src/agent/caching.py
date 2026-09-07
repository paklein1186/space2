"""Prompt caching pour les conversations Claude multi-tours (entretien, RAG).

L'historique de conversation est append-only (on n'édite jamais un message
passé) — c'est le cas d'usage idéal pour le cache de préfixe d'Anthropic :
on ne marque qu'UN seul point de cache mobile, toujours sur le dernier
message, et on retire le marquage du point précédent à chaque tour (Anthropic
limite à 4 breakpoints par requête ; un seul, mobile, suffit ici puisque le
préfixe ne fait que s'allonger).
"""

from __future__ import annotations

CACHE_CONTROL = {"type": "ephemeral"}


def to_plain_content(content) -> list:
    """Convertit le contenu d'une réponse Claude (liste d'objets SDK typés :
    TextBlock, ToolUseBlock...) en liste de dicts simples, pour pouvoir y
    ajouter/retirer librement un marqueur cache_control par la suite."""
    plain = []
    for block in content:
        if isinstance(block, dict):
            plain.append(dict(block))
        else:
            plain.append(block.model_dump(exclude_none=True))
    return plain


def apply_single_cache_breakpoint(messages: list) -> None:
    """Modifie `messages` en place : retire cache_control de tout message
    autre que le dernier, puis le pose sur le dernier bloc de contenu du
    dernier message."""
    for msg in messages[:-1]:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)

    if not messages:
        return
    last = messages[-1]
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content, "cache_control": CACHE_CONTROL}]
    elif isinstance(content, list) and content:
        last_block = content[-1]
        if isinstance(last_block, dict):
            content[-1] = {**last_block, "cache_control": CACHE_CONTROL}


def cached_system(system_text: str) -> list:
    return [{"type": "text", "text": system_text, "cache_control": CACHE_CONTROL}]
