"""Tests for the Resume Agent."""

from __future__ import annotations

import asyncio

from kaos.contracts import Artifact, Context, Event, EventBus
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.agents.resume_agent import ARTIFACT_KIND, CONVERSATION_COMPLETED
from kaos.runtime import InMemoryStorage, KaosRuntime
from kaos.sdk import EchoLLMProvider


def _message(author: str, text: str) -> Event:
    return Event(
        type="message.created",
        source="discord",
        workspace="w1",
        payload={"author": author, "text": text},
    )


def _completed() -> Event:
    return Event(type=CONVERSATION_COMPLETED, source="discord", workspace="w1")


def test_accepts_only_when_conversation_completed() -> None:
    agent = ResumeAgent(EchoLLMProvider())
    only_messages = Context(workspace="w1", events=(_message("ana", "hola"),))
    with_trigger = Context(workspace="w1", events=(_message("ana", "hola"), _completed()))
    assert agent.accepts(only_messages) is False
    assert agent.accepts(with_trigger) is True


def test_run_produces_traceable_summary() -> None:
    canned = "# Resumen Ejecutivo\n## Estado\n- ok"
    llm = EchoLLMProvider(response=canned)
    agent = ResumeAgent(llm)
    e1 = _message("ana", "avanzamos con el módulo Odoo")
    e2 = _message("juan", "usaremos PostgreSQL")
    context = Context(workspace="w1", events=(e1, e2, _completed()))

    artifacts = asyncio.run(agent.run(context))

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.kind == ARTIFACT_KIND
    assert artifact.produced_by == "resume-agent"
    assert artifact.content["summary"] == canned
    assert artifact.content["format"] == "markdown"
    assert artifact.content["message_count"] == 2
    # Traceability: the summary references both source messages.
    assert artifact.source_events == (e1.id, e2.id)


def test_run_builds_transcript_prompt() -> None:
    llm = EchoLLMProvider()  # echoes the last (user) message = the transcript
    agent = ResumeAgent(llm)
    context = Context(
        workspace="w1",
        events=(_message("ana", "hola"), _message("juan", "listo"), _completed()),
    )

    artifacts = asyncio.run(agent.run(context))

    assert artifacts[0].content["summary"] == "ana: hola\njuan: listo"
    # The system prompt was sent first.
    assert llm.calls[0][0].role == "system"


def test_extra_instructions_augment_system_prompt() -> None:
    from kaos.plugins.agents.resume_agent import SYSTEM_PROMPT

    llm = EchoLLMProvider()
    extra = "enfocate en montos y bloqueantes"
    agent = ResumeAgent(llm, extra_instructions=extra)
    context = Context(workspace="w1", events=(_message("ana", "hola"), _completed()))

    asyncio.run(agent.run(context))

    system = llm.calls[0][0]
    assert system.role == "system"
    # The base prompt is preserved and the user instructions are appended.
    assert SYSTEM_PROMPT in system.content
    assert extra in system.content


def test_no_extra_instructions_keeps_base_prompt_unchanged() -> None:
    from kaos.plugins.agents.resume_agent import SYSTEM_PROMPT

    llm = EchoLLMProvider()
    agent = ResumeAgent(llm)
    context = Context(workspace="w1", events=(_message("ana", "hola"), _completed()))

    asyncio.run(agent.run(context))

    assert llm.calls[0][0].content == SYSTEM_PROMPT


def test_transcript_prefixes_timestamp_when_present() -> None:
    llm = EchoLLMProvider()  # echoes the transcript back as the "summary"
    agent = ResumeAgent(llm)
    dated = Event(
        type="message.created",
        source="discord",
        workspace="w1",
        payload={"author": "ana", "text": "hola", "timestamp": "2026-07-08T14:30:00+00:00"},
    )
    context = Context(workspace="w1", events=(dated, _message("juan", "listo"), _completed()))

    artifacts = asyncio.run(agent.run(context))

    # Dated line carries its ISO timestamp; the undated line stays minimal.
    assert artifacts[0].content["summary"] == (
        "[2026-07-08T14:30:00+00:00] ana: hola\njuan: listo"
    )


def test_secrets_are_redacted_before_llm_and_artifact() -> None:
    secret = "sk-abcdefghijklmnopqrstuvwxyz012345"
    llm = EchoLLMProvider()  # echoes the transcript back as the "summary"
    agent = ResumeAgent(llm)
    context = Context(
        workspace="w1",
        events=(_message("ana", f"la api_key es {secret}"), _completed()),
    )

    artifacts = asyncio.run(agent.run(context))

    # Never sent to the provider...
    transcript = llm.calls[0][1].content
    assert secret not in transcript
    assert "[REDACTED]" in transcript
    # ...and never stored in the published artifact.
    assert secret not in artifacts[0].content["summary"]



class _CollectingPublisher:
    name = "collecting-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)


class _ConversationConnector:
    name = "conversation-connector"

    async def start(self, bus: EventBus) -> None:
        await bus.publish(_message("ana", "necesitamos un Resume Agent"))
        await bus.publish(_completed())

    async def stop(self) -> None:
        ...


def test_resume_agent_end_to_end_in_runtime() -> None:
    storage = InMemoryStorage()
    runtime = KaosRuntime(storage=storage)
    publisher = _CollectingPublisher()

    runtime.register_connector(_ConversationConnector())
    runtime.register_agent(ResumeAgent(EchoLLMProvider(response="# Resumen Ejecutivo")))
    runtime.register_publisher(publisher)

    asyncio.run(runtime.start())

    assert len(publisher.published) == 1
    artifact = publisher.published[0]
    assert artifact.kind == ARTIFACT_KIND
    assert artifact.content["summary"] == "# Resumen Ejecutivo"

    stored = asyncio.run(storage.list_artifacts("w1"))
    assert len(stored) == 1

