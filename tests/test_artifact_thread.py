"""Round 5 — artifact threads, transcript embedding, and friendly labels.

The chat history must be able to show the *full originating thread* behind any
artifact (not just its summary), paginated backwards for infinite scroll, plus
render a friendly title and last-activity date in the knowledge list.
"""

from __future__ import annotations

import asyncio

from kaos.contracts.artifact import Artifact
from kaos.contracts.event import Event
from kaos.plugins.dashboard.chat import (
    artifact_friendly_title,
    artifact_last_activity,
    artifact_thread,
)
from kaos.runtime import InMemoryStorage

WS = "github:acme/widget"


def _summary_artifact(count: int = 100) -> Artifact:
    messages = [
        {
            "author": f"user{i % 3}",
            "text": f"mensaje {i}",
            "timestamp": f"2026-07-12T00:{i // 60:02d}:{i % 60:02d}+00:00",
        }
        for i in range(count)
    ]
    return Artifact(
        kind="conversation.summary",
        workspace=WS,
        produced_by="Resume Agent",
        content={
            "summary": "Un resumen.",
            "format": "markdown",
            "message_count": count,
            "messages": messages,
            "title": "Hilo de prueba",
        },
        metadata={"title": "Hilo de prueba"},
    )


def test_artifact_thread_paginates_backwards() -> None:
    storage = InMemoryStorage()
    artifact = _summary_artifact(100)

    async def scenario() -> tuple[dict[str, object], dict[str, object]]:
        await storage.save_artifact(artifact)
        first = await artifact_thread(storage, WS, str(artifact.id), offset=0, limit=40)
        second = await artifact_thread(
            storage, WS, str(artifact.id), offset=int(first["next_offset"]), limit=40
        )
        return first, second

    first, second = asyncio.run(scenario())

    # Newest window comes first (ascending inside the window).
    assert len(first["messages"]) == 40
    assert first["messages"][-1]["text"] == "mensaje 99"
    assert first["messages"][0]["text"] == "mensaje 60"
    assert first["has_more"] is True
    assert first["next_offset"] == 40
    assert first["summary"] == "Un resumen."

    # Older window continues backwards; summary only on the first page.
    assert second["messages"][-1]["text"] == "mensaje 59"
    assert second["messages"][0]["text"] == "mensaje 20"
    assert second["has_more"] is True
    assert second["summary"] is None


def test_artifact_thread_last_page_stops() -> None:
    storage = InMemoryStorage()
    artifact = _summary_artifact(30)

    async def scenario() -> dict[str, object]:
        await storage.save_artifact(artifact)
        return await artifact_thread(storage, WS, str(artifact.id), offset=0, limit=40)

    page = asyncio.run(scenario())
    assert len(page["messages"]) == 30
    assert page["has_more"] is False
    assert page["messages"][0]["text"] == "mensaje 0"


def test_artifact_thread_falls_back_to_source_events() -> None:
    """Artifacts predating transcript embedding recover from stored events."""
    storage = InMemoryStorage()

    async def scenario() -> dict[str, object]:
        events = []
        for i in range(3):
            ev = Event(
                type="message.created",
                source="discord",
                workspace=WS,
                payload={
                    "author": f"u{i}",
                    "text": f"evento {i}",
                    "timestamp": f"2026-07-12T00:00:0{i}+00:00",
                    "channel_id": "42",
                },
            )
            await storage.save_event(ev)
            events.append(ev)
        artifact = Artifact(
            kind="conversation.summary",
            workspace=WS,
            produced_by="Resume Agent",
            content={"summary": "s", "format": "markdown"},
            source_events=tuple(e.id for e in events),
            metadata={"channel_id": "42"},
        )
        await storage.save_artifact(artifact)
        return await artifact_thread(storage, WS, str(artifact.id))

    page = asyncio.run(scenario())
    assert [m["text"] for m in page["messages"]] == ["evento 0", "evento 1", "evento 2"]


def test_artifact_thread_missing_artifact_is_empty() -> None:
    storage = InMemoryStorage()
    page = asyncio.run(artifact_thread(storage, WS, "does-not-exist"))
    assert page["messages"] == []
    assert page["has_more"] is False


def test_friendly_title_prefers_title_then_thread_then_kind() -> None:
    with_title = _summary_artifact(2)
    assert artifact_friendly_title(with_title) == "Hilo de prueba"

    plain = Artifact(
        kind="conversation.summary",
        workspace=WS,
        produced_by="Resume Agent",
        content={"summary": "s"},
    )
    assert artifact_friendly_title(plain) == "Resumen de conversación"

    status = Artifact(
        kind="project.status",
        workspace=WS,
        produced_by="Resume Agent",
        content={"summary": "s"},
    )
    assert artifact_friendly_title(status) == "📊 Estado del Proyecto"


def test_last_activity_uses_latest_message_timestamp() -> None:
    artifact = _summary_artifact(5)
    assert artifact_last_activity(artifact) == "2026-07-12T00:00:04+00:00"

    plain = Artifact(
        kind="conversation.summary",
        workspace=WS,
        produced_by="Resume Agent",
        content={"summary": "s"},
    )
    # Falls back to the artifact's own timestamp (ISO string).
    assert artifact_last_activity(plain) == plain.timestamp.isoformat(timespec="seconds")
