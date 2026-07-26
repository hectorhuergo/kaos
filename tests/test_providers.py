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


def test_complete_injects_num_ctx_when_configured() -> None:
    """With ``num_ctx`` set, Ollama is called on its native ``/api/chat`` API.

    The OpenAI-compatible endpoint ignores ``num_ctx``; the native API applies it
    via ``options.num_ctx``. This is how KAOS raises Ollama's small default
    context and avoids ``exceeds available context size`` on long conversations —
    no prompt chunking, no degraded summaries.
    """
    import asyncio
    import json

    import httpx

    from kaos.contracts.llm import Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider.ollama(
        model="gemma3:4b", client=client, num_ctx=8192
    )

    async def scenario() -> str:
        try:
            return await provider.complete([Message(role="user", content="hola")])
        finally:
            await client.aclose()

    assert asyncio.run(scenario()) == "ok"
    assert seen["path"] == "/api/chat"  # native endpoint, not /v1/chat/completions
    assert seen["body"]["options"]["num_ctx"] == 8192


def test_complete_omits_num_ctx_by_default() -> None:
    """Hosted providers never receive ``num_ctx`` (would be an unknown param)."""
    import asyncio

    import httpx

    from kaos.contracts.llm import Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(model="gpt-4o-mini", api_key="sk", client=client)

    async def scenario() -> str:
        try:
            return await provider.complete([Message(role="user", content="hola")])
        finally:
            await client.aclose()

    assert asyncio.run(scenario()) == "ok"
    assert "num_ctx" not in seen


def test_complete_consolidates_consecutive_same_role_messages() -> None:
    """Consecutive same-role messages are folded into one before sending.

    Strict chat templates (e.g. CodeGemma) ``raise_exception`` when roles don't
    alternate. KAOS' chunking/tool-use paths emit several ``user`` messages in a
    row, which triggered Ollama 500s. Folding runs of the same role keeps the
    sequence alternating while preserving all content.
    """
    import asyncio
    import json

    import httpx

    from kaos.contracts.llm import Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(model="gpt-4o-mini", api_key="sk", client=client)

    async def scenario() -> str:
        try:
            return await provider.complete(
                [
                    Message(role="system", content="sys"),
                    Message(role="user", content="chunk 1"),
                    Message(role="user", content="chunk 2"),
                    Message(role="user", content="chunk 3"),
                    Message(role="assistant", content="a1"),
                    Message(role="assistant", content="a2"),
                ]
            )
        finally:
            await client.aclose()

    assert asyncio.run(scenario()) == "ok"
    messages = seen["body"]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant"]
    assert messages[1]["content"] == "chunk 1\n\nchunk 2\n\nchunk 3"
    assert messages[2]["content"] == "a1\n\na2"


def test_complete_consolidates_roles_on_ollama_native() -> None:
    """Role consolidation also applies on Ollama's native ``/api/chat`` path."""
    import asyncio
    import json

    import httpx

    from kaos.contracts.llm import Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "ok"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider.ollama(
        model="codegemma", client=client, num_ctx=4096
    )

    async def scenario() -> str:
        try:
            return await provider.complete(
                [
                    Message(role="user", content="chunk 1"),
                    Message(role="user", content="chunk 2"),
                ]
            )
        finally:
            await client.aclose()

    assert asyncio.run(scenario()) == "ok"
    messages = seen["body"]["messages"]
    assert [m["role"] for m in messages] == ["user"]
    assert messages[0]["content"] == "chunk 1\n\nchunk 2"


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


def test_complete_reports_timeout_clearly() -> None:
    """A read timeout surfaces an explicit, non-empty reason (not a bare colon)."""
    import asyncio

    import httpx

    from kaos.contracts.llm import LLMError, Message
    from kaos.plugins.providers import OpenAICompatibleLLMProvider

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleLLMProvider(
        model="gemma", api_key="x", client=client, name="ollama"
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
    assert "timeout" in str(err).lower()
    assert "KAOS_LLM_TIMEOUT" in str(err)


