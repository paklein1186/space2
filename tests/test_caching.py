"""Vérifie la logique de gestion du point de cache mobile (sans appel API) :
un seul breakpoint actif à la fois, toujours sur le dernier message."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.caching import apply_single_cache_breakpoint, to_plain_content


def check(label, condition):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label}")
    assert condition, label


def has_cache_control(msg) -> bool:
    content = msg["content"]
    if isinstance(content, list):
        return any(isinstance(b, dict) and "cache_control" in b for b in content)
    return False


def main():
    messages = [
        {"role": "user", "content": "Bonjour"},
    ]
    apply_single_cache_breakpoint(messages)
    check("Le premier message porte le cache_control", has_cache_control(messages[0]))

    messages.append({"role": "assistant", "content": [{"type": "text", "text": "Salut !"}]})
    messages.append({"role": "user", "content": "Deuxième message"})
    apply_single_cache_breakpoint(messages)
    check("Le cache_control a été retiré du premier message", not has_cache_control(messages[0]))
    check("Le cache_control a été retiré du deuxième message (assistant)", not has_cache_control(messages[1]))
    check("Le cache_control est maintenant sur le dernier message", has_cache_control(messages[2]))

    messages.append({"role": "assistant", "content": [
        {"type": "tool_use", "id": "t1", "name": "save_answer", "input": {"champ_id": "x", "valeur": "y"}}
    ]})
    messages.append({"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "t1", "content": "{}"}
    ]})
    apply_single_cache_breakpoint(messages)
    check("Un seul message porte le cache_control", sum(has_cache_control(m) for m in messages) == 1)
    check("C'est bien le tout dernier message (tool_result)", has_cache_control(messages[-1]))

    class FakeBlock:
        def model_dump(self, exclude_none=True):
            return {"type": "text", "text": "réponse convertie"}

    plain = to_plain_content([FakeBlock()])
    check("to_plain_content convertit un objet SDK en dict", plain == [{"type": "text", "text": "réponse convertie"}])

    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    main()
