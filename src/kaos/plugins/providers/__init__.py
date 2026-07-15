"""KAOS LLM providers (AI Provider Agnostic implementations of LLMProvider)."""

from __future__ import annotations

from kaos.plugins.providers.copilot import (
    COPILOT_BASE_URL,
    DEFAULT_COPILOT_MODEL,
    CopilotLLMProvider,
    device_login,
)
from kaos.plugins.providers.openai_compatible import (
    ANTHROPIC_BASE_URL,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OLLAMA_MODEL,
    GITHUB_MODELS_BASE_URL,
    OLLAMA_BASE_URL,
    OPENAI_BASE_URL,
    OpenAICompatibleLLMProvider,
)

__all__ = [
    "ANTHROPIC_BASE_URL",
    "COPILOT_BASE_URL",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_COPILOT_MODEL",
    "DEFAULT_OLLAMA_MODEL",
    "GITHUB_MODELS_BASE_URL",
    "OLLAMA_BASE_URL",
    "OPENAI_BASE_URL",
    "CopilotLLMProvider",
    "OpenAICompatibleLLMProvider",
    "device_login",
]

