"""Tests for the OpenAI-compatible LLM provider (no network, MockTransport)."""

from __future__ import annotations

import asyncio
import json

import httpx

from kaos.contracts import Context, Event
from kaos.contracts.llm import Message
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.agents.resume_agent import CONVERSATION_COMPLETED
from kaos.plugins.providers import GITHUB_MODELS_BASE_URL, OpenAICompatibleLLMProvider


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_complete_sends_openai_payload_and_parses_response() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "hola!"}}]},
        )

    provider = OpenAICompatibleLLMProvider(
        model="gpt-4o-mini",
        api_key="secret",
        base_url="https://example.test/v1",
        client=_mock_client(handler),
    )

    async def scenario() -> str:
        result = await provider.complete(
            [Message(role="user", content="hola")], temperature=0.2
        )
        await provider.aclose()
        return result

    result = asyncio.run(scenario())

    assert result == "hola!"
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hola"}]
    assert captured["body"]["temperature"] == 0.2  # options passthrough


def test_provider_retries_on_rate_limit() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                headers={"retry-after": "0"},
                json={"error": {"message": "Rate limit"}},
            )
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = OpenAICompatibleLLMProvider(
        model="m", api_key="k", client=_mock_client(handler), max_retries=3
    )
    result = asyncio.run(provider.complete([Message(role="user", content="hi")]))
    assert result == "ok"
    assert calls["n"] == 2  # retried once after the 429


def test_github_models_factory_targets_github_endpoint() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    provider = OpenAICompatibleLLMProvider.github_models(
        token="ghtoken", client=_mock_client(handler)
    )
    assert provider.name == "github-models"

    result = asyncio.run(provider.complete([Message(role="user", content="hi")]))
    assert result == "ok"
    assert captured["url"] == f"{GITHUB_MODELS_BASE_URL}/chat/completions"


def test_provider_drives_resume_agent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "# Resumen Ejecutivo"}}]},
        )

    provider = OpenAICompatibleLLMProvider(
        model="m", api_key="k", client=_mock_client(handler)
    )
    agent = ResumeAgent(provider)
    context = Context(
        workspace="w1",
        events=(
            Event(type="message.created", source="d", workspace="w1",
                  payload={"author": "ana", "text": "hola"}),
            Event(type=CONVERSATION_COMPLETED, source="d", workspace="w1"),
        ),
    )

    artifacts = asyncio.run(agent.run(context))
    assert artifacts[0].content["summary"] == "# Resumen Ejecutivo"

