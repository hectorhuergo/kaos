"""KAOS LLM providers (AI Provider Agnostic implementations of LLMProvider)."""

from __future__ import annotations

from kaos.plugins.providers.openai_compatible import (
    GITHUB_MODELS_BASE_URL,
    OPENAI_BASE_URL,
    OpenAICompatibleLLMProvider,
)

__all__ = [
    "GITHUB_MODELS_BASE_URL",
    "OPENAI_BASE_URL",
    "OpenAICompatibleLLMProvider",
]

