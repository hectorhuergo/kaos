"""Round 4 — chat over knowledge, contributions reuse, and dev-agent tool-use.

Covers three behaviours added so the chat can operate on any stored artifact
(A), so human chat contributions enrich future Resume runs (B), and so a
tool-using agent (Dev Agent) runs its tool loop from the chat instead of a
single completion (C).
"""

from __future__ import annotations

import asyncio

from kaos.contracts.context import Context
from kaos.contracts.event import Event
from kaos.core.config import Settings
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.dashboard.chat import (
    CONTRIBUTION_EVENT,
    contribution_ids,
    load_contributions,
    send_message,
)
from kaos.runtime import InMemoryStorage, KaosRuntime
from kaos.sdk import EchoLLMProvider

WS = "github:acme/widget"


# ---- B: contributions from stored chat messages ----


def test_load_contributions_maps_user_messages() -> None:
    storage = InMemoryStorage()

    async def scenario() -> list[Event]:
        await storage.save_event(
            Event(
                type="chat.message.user",
                source="chat",
                workspace=WS,
                payload={"user_id": "ana", "message": "El cambio X ya fue publicado."},
            )
        )
        # An assistant message and an empty user message must be ignored.
        await storage.save_event(
            Event(
                type="chat.message.assistant",
                source="chat",
                workspace=WS,
                payload={"response": "ok"},
            )
        )
        await storage.save_event(
            Event(
                type="chat.message.user",
                source="chat",
                workspace=WS,
                payload={"user_id": "ana", "message": "   "},
            )
        )
        return await load_contributions(storage, WS)

    contributions = asyncio.run(scenario())
    assert len(contributions) == 1
    c = contributions[0]
    assert c.type == CONTRIBUTION_EVENT
    assert c.payload["author"] == "aporte:ana"
    assert c.payload["text"] == "El cambio X ya fue publicado."
    # The stable originating id is carried for cache fingerprints.
    assert c.payload["contribution_id"]
    assert contribution_ids(contributions) == [c.payload["contribution_id"]]


def test_contribution_ids_are_stable_across_reload() -> None:
    storage = InMemoryStorage()

    async def scenario() -> tuple[list[str], list[str]]:
        await storage.save_event(
            Event(
                type="chat.message.user",
                source="chat",
                workspace=WS,
                payload={"user_id": "ana", "message": "aporte"},
            )
        )
        first = contribution_ids(await load_contributions(storage, WS))
        second = contribution_ids(await load_contributions(storage, WS))
        return first, second

    first, second = asyncio.run(scenario())
    # Ids must be stable (the chat event id), not the synthetic event's uuid,
    # so the cache fingerprint does not churn on every run.
    assert first == second


def test_resume_agent_weighs_a_contribution() -> None:
    """A synthetic contribution event is rendered by the Resume Agent as-is."""
    agent = ResumeAgent(EchoLLMProvider())
    contribution = Event(
        type=CONTRIBUTION_EVENT,
        source="chat",
        workspace=WS,
        payload={
            "author": "aporte:ana",
            "text": "Confirmo que el deploy se hizo.",
            "timestamp": "2026-01-01T00:00:00",
        },
    )
    context = Context(workspace=WS, events=(contribution,))
    artifacts = asyncio.run(agent.run(context))
    assert artifacts
    summary = artifacts[0].content["summary"]
    assert "Confirmo que el deploy se hizo." in summary


def test_prime_workspace_seeds_history_for_contributions() -> None:
    storage = InMemoryStorage()
    runtime = KaosRuntime(storage=storage)
    contribution = Event(
        type=CONTRIBUTION_EVENT,
        source="chat",
        workspace=WS,
        payload={"author": "aporte:ana", "text": "hola", "timestamp": "t"},
    )
    runtime.prime_workspace(WS, [contribution])
    # The primed events are available for the next context built for WS.
    history = runtime._history.get(WS)  # noqa: SLF001 - white-box on purpose
    assert history is not None and contribution in history


# ---- A: chat grounded on an existing artifact ----


def test_send_message_about_artifact_links_and_inherits_project() -> None:
    storage = InMemoryStorage()

    async def scenario() -> dict[str, object]:
        from kaos.contracts.artifact import Artifact

        art = Artifact(
            kind="conversation.summary",
            workspace=WS,
            produced_by="resume-agent",
            content={"summary": "Estado: pendiente publicar."},
            metadata={"project": "widget"},
        )
        await storage.save_artifact(art)
        result = await send_message(
            storage,
            Settings(),
            workspace=WS,
            user_id="ana",
            agent_id="resume-agent",
            message="Ya publiqué el cambio.",
            about_artifact=str(art.id),
        )
        return result, str(art.id)  # type: ignore[return-value]

    result, art_id = asyncio.run(scenario())  # type: ignore[misc]
    assert result["about_artifact"] == art_id
    # The project was inherited from the referenced artifact.
    assert result["session"]["project"] == "widget"  # type: ignore[index]
    # The produced turn artifact records the link back to the source knowledge.
    turn = result["artifacts"][0]  # type: ignore[index]
    assert turn.metadata["about_artifact"] == art_id


def test_send_message_unknown_about_artifact_is_ignored() -> None:
    storage = InMemoryStorage()

    async def scenario() -> dict[str, object]:
        return await send_message(
            storage,
            Settings(),
            workspace=WS,
            user_id="ana",
            agent_id="resume-agent",
            message="hola",
            about_artifact="00000000-0000-0000-0000-000000000000",
        )

    result = asyncio.run(scenario())
    assert result["about_artifact"] is None
    assert result["response"]


# ---- C: dev-agent runs its tool loop from the chat ----


def test_send_message_dev_agent_produces_dev_session() -> None:
    storage = InMemoryStorage()

    async def scenario() -> dict[str, object]:
        return await send_message(
            storage,
            Settings(),
            workspace=WS,
            user_id="ana",
            agent_id="dev-agent",
            message="Listá el directorio actual.",
        )

    result = asyncio.run(scenario())
    # The dev-agent branch runs the tool loop and persists a traceable
    # dev.session (with tool steps) instead of a plain chat.turn.
    turn = result["artifacts"][0]  # type: ignore[index]
    assert turn.kind == "dev.session"
    assert "steps" in turn.content
