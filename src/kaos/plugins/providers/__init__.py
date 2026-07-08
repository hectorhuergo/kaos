"""KAOS LLM providers (AI Provider Agnostic implementations of LLMProvider)."""

from __future__ import annotations

from kaos.plugins.providers.openai_compatible import (
    ANTHROPIC_BASE_URL,
    DEFAULT_ANTHROPIC_MODEL,
    GITHUB_MODELS_BASE_URL,
    OPENAI_BASE_URL,
    OpenAICompatibleLLMProvider,
)

__all__ = [
    "ANTHROPIC_BASE_URL",
    "DEFAULT_ANTHROPIC_MODEL",
    "GITHUB_MODELS_BASE_URL",
    "OPENAI_BASE_URL",
    "OpenAICompatibleLLMProvider",
]

