"""Token-budget helpers for agent-level chunking (map-reduce).

Pure functions (no plugin/provider imports) so the Core stays agnostic. Agents
use these to split oversized input into pieces that fit a model's context window
and then synthesize a single coherent result — instead of pushing chunking into
the provider, where concatenating partial answers would corrupt a structured
output (e.g. an executive summary). See ADR-0024.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

# Rough heuristic used across LLMs: ~4 characters per token. Good enough to
# budget a request without pulling in a model-specific tokenizer (tiktoken).
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` (~4 chars/token, min 1)."""
    return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)


def group_by_token_budget[T](
    items: Sequence[T], size_of: Callable[[T], int], budget: int
) -> list[list[T]]:
    """Greedily group ``items`` so each group's estimated size stays ``<= budget``.

    Preserves order (important for a conversation). An item larger than the
    budget on its own is placed in its own group — it cannot be split here
    without breaking its meaning, so the caller decides how to handle it.
    """
    if budget <= 0:
        return [list(items)] if items else []
    groups: list[list[T]] = []
    current: list[T] = []
    current_size = 0
    for item in items:
        size = size_of(item)
        if current and current_size + size > budget:
            groups.append(current)
            current, current_size = [], 0
        current.append(item)
        current_size += size
    if current:
        groups.append(current)
    return groups

