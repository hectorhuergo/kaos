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


def test_copilot_ready_with_oauth_token() -> None:
    from kaos.core.providers import secret_field

    assert is_ready("copilot", Settings()) is False
    assert is_ready("copilot", Settings(copilot_oauth_token="gho_x")) is True
    # No cross-provider fallback: a GitHub Models token does not enable Copilot.
    assert is_ready("copilot", Settings(github_token="ghp_x")) is False
    assert secret_field("copilot") == "copilot_oauth_token"
    assert secret_sources("copilot", Settings(copilot_oauth_token="gho_x")) == (
        "KAOS_COPILOT_TOKEN",
    )


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


def test_list_models_parses_openai_shape() -> None:
    import asyncio

    import httpx

    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200, json={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(model="x", api_key="sk", client=client)

    async def scenario() -> list[str]:
        try:
            return await provider.list_models()
        finally:
            await client.aclose()

    assert asyncio.run(scenario()) == ["gpt-4o", "gpt-4o-mini"]


def test_list_models_helper_returns_empty_on_failure() -> None:
    import asyncio

    from kaos.bootstrap.factory import list_models

    # No credential + no DB: build_llm raises for openai -> best-effort [].
    assert asyncio.run(list_models(Settings(), "openai")) == []
    # echo has no catalog.
    assert asyncio.run(list_models(Settings(), "echo")) == []


def test_list_models_extracts_model_names_from_urls() -> None:
    """GitHub Models returns azureml resource URIs; use the model ``name``.

    The Azure inference host (``https://models.inference.ai.azure.com/models``)
    returns a top-level list where ``id`` is an
    ``azureml://…/models/<name>/versions/<n>`` URI — its last path segment is the
    *version number*, not the model. The parser must use ``name`` instead, keep
    plain ids untouched, and drop non-chat (embedding) entries.
    """
    import asyncio

    import httpx

    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json=[
                {
                    "id": "azureml://registries/azure-openai/models/gpt-4o/versions/2",
                    "name": "gpt-4o",
                    "task": "chat-completion",
                },
                {
                    "id": "azureml://registries/azureml-meta/models/"
                    "Meta-Llama-3.1-8B-Instruct/versions/4",
                    "name": "Meta-Llama-3.1-8B-Instruct",
                    "task": "chat-completion",
                },
                {
                    "id": "azureml://registries/azureml-cohere/models/"
                    "Cohere-embed-v3-english/versions/3",
                    "name": "Cohere-embed-v3-english",
                    "task": "embeddings",  # non-chat -> filtered out
                },
                {"id": "gpt-4o-mini"},  # plain OpenAI-style id, unchanged
            ],
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(model="x", api_key="sk", client=client)

    async def scenario() -> list[str]:
        try:
            return await provider.list_models()
        finally:
            await client.aclose()

    # Sorted, deduped, chat-only, using ``name`` for azureml URIs.
    assert asyncio.run(scenario()) == [
        "Meta-Llama-3.1-8B-Instruct",
        "gpt-4o",
        "gpt-4o-mini",
    ]


def test_complete_raises_llm_error_with_provider_message() -> None:
    """A 4xx from the endpoint surfaces the provider's own reason, not a bare code.

    GitHub Models' legacy host *lists* models (e.g. Meta-Llama) that its inference
    endpoint then rejects with ``400 unknown_model``. The provider must raise an
    ``LLMError`` carrying that message and the status so the UI can show it.
    """
    import asyncio

    import httpx

    from kaos.contracts.llm import LLMError, Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "unknown_model",
                    "message": "Unknown model: meta-llama-3.1-8b-instruct",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        model="Meta-Llama-3.1-8B-Instruct", api_key="sk", client=client, name="github-models"
    )

    async def scenario() -> LLMError:
        try:
            try:
                await provider.complete([Message(role="user", content="hola")])
            except LLMError as exc:
                return exc
            raise AssertionError("expected LLMError")
        finally:
            await client.aclose()

    err = asyncio.run(scenario())
    assert err.status_code == 400
    assert err.provider == "github-models"
    assert err.model == "Meta-Llama-3.1-8B-Instruct"
    assert "Unknown model: meta-llama-3.1-8b-instruct" in str(err)


def test_complete_wraps_transport_errors_as_llm_error() -> None:
    """A transport failure (no network) becomes an ``LLMError``, not a raw httpx one."""
    import asyncio

    import httpx

    from kaos.contracts.llm import LLMError, Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        model="gpt-4o-mini", api_key="sk", client=client, name="github-models"
    )

    async def scenario() -> LLMError:
        try:
            try:
                await provider.complete([Message(role="user", content="hola")])
            except LLMError as exc:
                return exc
            raise AssertionError("expected LLMError")
        finally:
            await client.aclose()

    err = asyncio.run(scenario())
    assert err.status_code is None
    assert "No se pudo contactar a github-models" in str(err)

