"""Tests for the LLM provider catalog and `kaos providers`."""

from __future__ import annotations

from kaos.core.config import LLM_PROVIDERS, Settings
from kaos.core.providers import CATALOG, is_ready, provider_status, secret_sources


def test_catalog_covers_every_configured_provider() -> None:
    assert {p.id for p in CATALOG} == set(LLM_PROVIDERS)


def test_echo_is_always_ready() -> None:
    assert is_ready("echo", Settings()) is True


def test_github_requires_its_own_token() -> None:
    assert is_ready("github", Settings()) is False
    assert is_ready("github", Settings(github_token="ghp_x")) is True
    # No cross-provider fallback: the generic OpenAI key does not enable GitHub.
    assert is_ready("github", Settings(llm_api_key="k")) is False


def test_anthropic_ready_with_key() -> None:
    assert is_ready("anthropic", Settings()) is False
    assert is_ready("anthropic", Settings(anthropic_api_key="sk-ant")) is True
    # No cross-provider fallback to the generic OpenAI key.
    assert is_ready("anthropic", Settings(llm_api_key="k")) is False


def test_secret_sources_report_only_the_providers_own_env() -> None:
    # Without its own secret set there is no source (no generic fallback).
    assert secret_sources("anthropic", Settings(llm_api_key="k")) == ()
    assert secret_sources("github", Settings(llm_api_key="k")) == ()
    assert secret_sources("anthropic", Settings(anthropic_api_key="sk-ant")) == (
        "KAOS_ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY",
    )
    assert secret_sources("github", Settings(github_token="ghp_x")) == (
        "KAOS_GITHUB_TOKEN",
        "GITHUB_TOKEN",
    )
    assert secret_sources("openai", Settings(llm_api_key="sk")) == ("KAOS_LLM_API_KEY",)


def test_openai_ready_with_llm_key() -> None:
    assert is_ready("openai", Settings()) is False
    assert is_ready("openai", Settings(llm_api_key="sk")) is True


def test_ollama_is_always_ready_and_needs_no_secret() -> None:
    from kaos.core.providers import secret_field

    assert is_ready("ollama", Settings()) is True
    assert secret_field("ollama") is None


def test_provider_status_marks_active_and_readiness() -> None:
    settings = Settings(llm_provider="github", github_token="ghp_x")
    status = {info.id: (ready, active) for info, ready, active in provider_status(settings)}
    assert status["github"] == (True, True)
    assert status["openai"][1] is False  # not active
    assert status["echo"][0] is True  # always ready

