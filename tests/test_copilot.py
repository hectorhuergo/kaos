"""Tests for the GitHub Copilot provider and its OAuth device flow.

HTTP is faked with ``httpx.MockTransport`` so the token exchange, session-token
caching and the device flow are exercised without touching the network.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from kaos.contracts.llm import Message
from kaos.plugins.providers.copilot import (
    ACCESS_TOKEN_URL,
    DEVICE_CODE_URL,
    CopilotLLMProvider,
    DeviceCodeError,
    device_login,
    poll_for_access_token,
)


async def _noop_sleep(_seconds: float) -> None:
    return None


def test_completion_exchanges_and_caches_session_token() -> None:
    calls = {"token": 0, "chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/copilot_internal/v2/token":
            calls["token"] += 1
            assert request.headers["Authorization"] == "token gho_test"
            return httpx.Response(
                200, json={"token": "tid=sess", "expires_at": time.time() + 1800}
            )
        if request.url.path == "/chat/completions":
            calls["chat"] += 1
            # The ephemeral session token — not the OAuth token — is the Bearer.
            assert request.headers["Authorization"] == "Bearer tid=sess"
            assert request.headers["Copilot-Integration-Id"] == "vscode-chat"
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "hola"}}]}
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = CopilotLLMProvider(oauth_token="gho_test", client=client)

    async def scenario() -> None:
        first = await provider.complete([Message(role="user", content="hi")])
        second = await provider.complete([Message(role="user", content="again")])
        assert first == "hola"
        assert second == "hola"
        await client.aclose()

    asyncio.run(scenario())
    assert calls["chat"] == 2
    # The session token is minted once and reused while still valid.
    assert calls["token"] == 1


def test_refresh_raises_on_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = CopilotLLMProvider(oauth_token="gho_bad", client=client)

    async def scenario() -> None:
        raised = False
        try:
            await provider.complete([Message(role="user", content="hi")])
        except ValueError:
            raised = True
        await client.aclose()
        assert raised

    asyncio.run(scenario())


def test_poll_waits_for_pending_then_returns_token() -> None:
    states = iter([
        {"error": "authorization_pending"},
        {"error": "slow_down"},
        {"access_token": "gho_new"},
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == ACCESS_TOKEN_URL
        return httpx.Response(200, json=next(states))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def scenario() -> str:
        token = await poll_for_access_token(
            "dev-code", interval=0.0, client=client, sleep=_noop_sleep
        )
        await client.aclose()
        return token

    assert asyncio.run(scenario()) == "gho_new"


def test_poll_raises_on_access_denied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": "access_denied"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def scenario() -> None:
        raised = False
        try:
            await poll_for_access_token("dev-code", client=client, sleep=_noop_sleep)
        except DeviceCodeError:
            raised = True
        await client.aclose()
        assert raised

    asyncio.run(scenario())


def test_device_login_runs_the_full_flow() -> None:
    prompts: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DEVICE_CODE_URL:
            return httpx.Response(
                200,
                json={
                    "device_code": "dev-code",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 0,
                },
            )
        if str(request.url) == ACCESS_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "gho_final"})
        raise AssertionError(f"unexpected url {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def scenario() -> str:
        token = await device_login(
            on_prompt=lambda code, uri: prompts.append((code, uri)),
            client=client,
            sleep=_noop_sleep,
        )
        await client.aclose()
        return token

    assert asyncio.run(scenario()) == "gho_final"
    assert prompts == [("ABCD-1234", "https://github.com/login/device")]
