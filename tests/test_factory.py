"""Tests for the composition root (bootstrap.factory)."""

from __future__ import annotations

import asyncio
import io

from kaos.bootstrap.factory import build_llm, build_runtime
from kaos.core.config import Settings
from kaos.plugins.providers import (
    ANTHROPIC_BASE_URL,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OLLAMA_MODEL,
    GITHUB_MODELS_BASE_URL,
    OLLAMA_BASE_URL,
    OpenAICompatibleLLMProvider,
)
from kaos.plugins.publishers import ConsolePublisher
from kaos.runtime import InMemoryStorage
from kaos.sdk import EchoLLMProvider


def test_build_llm_echo_by_default() -> None:
    assert isinstance(build_llm(Settings.from_env({})), EchoLLMProvider)


def test_build_llm_github() -> None:
    settings = Settings.from_env({"KAOS_LLM_PROVIDER": "github", "KAOS_GITHUB_TOKEN": "t"})
    llm = build_llm(settings)
    assert isinstance(llm, OpenAICompatibleLLMProvider)
    assert llm.name == "github-models"
    assert llm._base_url == GITHUB_MODELS_BASE_URL  # type: ignore[attr-defined]


def test_build_llm_anthropic_defaults_to_haiku() -> None:
    settings = Settings.from_env(
        {"KAOS_LLM_PROVIDER": "anthropic", "KAOS_ANTHROPIC_API_KEY": "k"}
    )
    llm = build_llm(settings)
    assert isinstance(llm, OpenAICompatibleLLMProvider)
    assert llm.name == "anthropic"
    assert llm._base_url == ANTHROPIC_BASE_URL  # type: ignore[attr-defined]
    # No claude model set -> defaults to Haiku.
    assert llm._model == DEFAULT_ANTHROPIC_MODEL  # type: ignore[attr-defined]


def test_build_llm_anthropic_honours_claude_model() -> None:
    settings = Settings.from_env(
        {
            "KAOS_LLM_PROVIDER": "anthropic",
            "KAOS_ANTHROPIC_API_KEY": "k",
            "KAOS_LLM_MODEL": "claude-3-5-sonnet-latest",
        }
    )
    llm = build_llm(settings)
    assert llm._model == "claude-3-5-sonnet-latest"  # type: ignore[attr-defined]


def test_build_llm_openai_uses_base_url() -> None:
    settings = Settings.from_env(
        {"KAOS_LLM_PROVIDER": "openai", "KAOS_LLM_API_KEY": "k", "KAOS_LLM_BASE_URL": "https://x/v1"}
    )
    llm = build_llm(settings)
    assert isinstance(llm, OpenAICompatibleLLMProvider)
    assert llm._base_url == "https://x/v1"  # type: ignore[attr-defined]


def test_build_llm_ollama_defaults_no_secret() -> None:
    # Local provider: no credential needed; app-wide default model is replaced
    # by Ollama's default tag and the local endpoint is used.
    settings = Settings.from_env({"KAOS_LLM_PROVIDER": "ollama"})
    llm = build_llm(settings)
    assert isinstance(llm, OpenAICompatibleLLMProvider)
    assert llm.name == "ollama"
    assert llm._base_url == OLLAMA_BASE_URL  # type: ignore[attr-defined]
    assert llm._model == DEFAULT_OLLAMA_MODEL  # type: ignore[attr-defined]


def test_build_llm_ollama_honours_model_and_base_url() -> None:
    settings = Settings.from_env(
        {
            "KAOS_LLM_PROVIDER": "ollama",
            "KAOS_LLM_MODEL": "qwen2.5:7b",
            "KAOS_LLM_BASE_URL": "http://ollama:11434/v1",
        }
    )
    llm = build_llm(settings)
    assert llm._model == "qwen2.5:7b"  # type: ignore[attr-defined]
    assert llm._base_url == "http://ollama:11434/v1"  # type: ignore[attr-defined]


def test_build_runtime_offline_demo_runs(monkeypatch) -> None:
    # No Discord token -> offline demo with console publisher.
    runtime = build_runtime(Settings.from_env({}))
    # Redirect the console publisher's stream by replacing the publisher.
    buffer = io.StringIO()
    runtime._publishers = [ConsolePublisher(stream=buffer)]  # type: ignore[attr-defined]
    asyncio.run(runtime.start())
    assert "conversation.summary" in buffer.getvalue()


def test_build_runtime_discord_wiring() -> None:
    settings = Settings.from_env(
        {"KAOS_DISCORD_TOKEN": "dtoken", "KAOS_DISCORD_GUILD_ID": "42"}
    )
    runtime = build_runtime(settings)
    connector = runtime._connectors[0]  # type: ignore[attr-defined]
    publisher = runtime._publishers[0]  # type: ignore[attr-defined]
    assert connector.name == "discord-connector"
    assert publisher.name == "discord-publisher"


def test_build_publisher_webhook_when_configured() -> None:
    from kaos.bootstrap.factory import build_publisher

    settings = Settings.from_env(
        {
            "KAOS_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/abc",
            "KAOS_DISCORD_RESUME_THREAD_ID": "1415760589195575356",
        }
    )
    publisher = build_publisher(settings)
    assert publisher.name == "discord-webhook-publisher"


def test_build_storage_defaults_to_memory() -> None:
    from kaos.bootstrap.factory import build_storage

    assert isinstance(build_storage(Settings.from_env({})), InMemoryStorage)


def test_build_storage_postgres_when_configured() -> None:
    from kaos.bootstrap.factory import build_storage
    from kaos.plugins.storage import PostgresStorage

    settings = Settings.from_env({"KAOS_DATABASE_URL": "postgresql://u:p@localhost/db"})
    # Constructed lazily; no connection is opened here.
    assert isinstance(build_storage(settings), PostgresStorage)


