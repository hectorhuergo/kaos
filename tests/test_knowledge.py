"""Tests for the knowledge graph and the static dashboard."""

from __future__ import annotations

import asyncio

from kaos.contracts.artifact import Artifact
from kaos.contracts.event import Event
from kaos.core.knowledge import (
    ARTIFACT,
    CONTAINS,
    DERIVED_FROM,
    EVENT,
    WORKSPACE,
    build_graph,
)
from kaos.plugins.dashboard import render_dashboard
from kaos.runtime import InMemoryStorage

WS = "discord:42"


def _seed() -> InMemoryStorage:
    storage = InMemoryStorage()

    async def scenario() -> None:
        ev = Event(
            type="message.created",
            source="discord",
            workspace=WS,
            payload={"author": "ana", "text": "avanzamos con Odoo"},
        )
        await storage.save_event(ev)
        await storage.save_artifact(
            Artifact(
                kind="conversation.summary",
                workspace=WS,
                produced_by="resume-agent",
                content={"summary": "# Resumen\n- ok", "message_count": 1},
                source_events=(ev.id,),
                metadata={"thread_name": "PMO", "model": "gpt-4o"},
            )
        )
        await storage.save_artifact(
            Artifact(
                kind="project.status",
                workspace=WS,
                produced_by="resume-agent",
                content={"summary": "# 📊 Estado", "message_count": 1, "thread_count": 1},
            )
        )

    asyncio.run(scenario())
    return storage


def test_build_graph_projects_workspace_and_artifacts() -> None:
    storage = _seed()
    graph = asyncio.run(build_graph(storage, [WS]))

    kinds = sorted({n.kind for n in graph.nodes})
    assert kinds == [ARTIFACT, WORKSPACE]
    # One workspace node + two artifact nodes.
    assert len([n for n in graph.nodes if n.kind == WORKSPACE]) == 1
    assert len([n for n in graph.nodes if n.kind == ARTIFACT]) == 2
    # Every artifact is contained by the workspace.
    contains = [e for e in graph.edges if e.kind == CONTAINS]
    assert len(contains) == 2
    assert all(e.source == WS for e in contains)
    # The summary node is labeled by its thread name.
    labels = {n.label for n in graph.nodes if n.kind == ARTIFACT}
    assert "PMO" in labels
    assert "📊 Estado del Proyecto" in labels


def test_build_graph_includes_events_when_requested() -> None:
    storage = _seed()
    graph = asyncio.run(build_graph(storage, [WS], include_events=True))

    events = [n for n in graph.nodes if n.kind == EVENT]
    assert len(events) == 1
    assert events[0].label.startswith("ana: avanzamos con Odoo")
    derived = [e for e in graph.edges if e.kind == DERIVED_FROM]
    assert len(derived) == 1


def test_to_dict_and_mermaid() -> None:
    storage = _seed()
    graph = asyncio.run(build_graph(storage, [WS]))

    data = graph.to_dict()
    assert set(data) == {"nodes", "edges"}
    assert len(data["nodes"]) == 3

    mermaid = graph.to_mermaid()
    assert mermaid.startswith("graph TD")
    assert "-->|contains|" in mermaid
    # Aliased ids keep the diagram valid (no raw 'discord:42' as a node handle).
    assert "n0[[" in mermaid


def test_render_dashboard_embeds_summaries_and_graph() -> None:
    storage = _seed()
    artifacts = asyncio.run(storage.list_artifacts(WS))
    graph = asyncio.run(build_graph(storage, [WS]))

    html_doc = render_dashboard([(WS, artifacts)], graph)

    assert "<!doctype html>" in html_doc
    assert "class=\"mermaid\"" in html_doc
    assert "PMO" in html_doc
    assert "gpt-4o" in html_doc
    assert "Estado" in html_doc
    # Mermaid must load as a classic UMD script (global), not as an ES module:
    # importing the UMD build as a module fails silently and shows raw text.
    assert "<script src=" in html_doc
    assert "type=\"module\"" not in html_doc


def test_empty_workspaces_produce_empty_graph() -> None:
    graph = asyncio.run(build_graph(InMemoryStorage(), []))
    assert graph.nodes == []
    assert graph.edges == []


def test_build_graph_dedupes_resummaries_by_thread() -> None:
    """Re-summarizing the same thread (e.g. another model) must not duplicate."""
    storage = InMemoryStorage()

    async def scenario() -> None:
        older = Artifact(
            kind="conversation.summary",
            workspace=WS,
            produced_by="resume-agent",
            content={"summary": "v1", "message_count": 1},
            metadata={"thread_name": "PMO", "model": "qwen2.5:3b"},
        )
        await storage.save_artifact(older)
        newer = Artifact(
            kind="conversation.summary",
            workspace=WS,
            produced_by="resume-agent",
            content={"summary": "v2", "message_count": 1},
            metadata={"thread_name": "PMO", "model": "llama3.2:3b"},
            timestamp=older.timestamp,
        )
        # Ensure the second one is strictly newer.
        newer = newer.model_copy(update={"timestamp": _later(older.timestamp)})
        await storage.save_artifact(newer)

    asyncio.run(scenario())

    deduped = asyncio.run(build_graph(storage, [WS]))
    artifacts = [n for n in deduped.nodes if n.kind == ARTIFACT]
    assert len(artifacts) == 1
    assert artifacts[0].meta["model"] == "llama3.2:3b"  # kept the latest

    full = asyncio.run(build_graph(storage, [WS], dedupe=False))
    assert len([n for n in full.nodes if n.kind == ARTIFACT]) == 2


def _later(ts: object) -> object:
    from datetime import timedelta

    return ts + timedelta(seconds=1)  # type: ignore[operator]


def test_group_artifacts_groups_by_subject_newest_first() -> None:
    from kaos.core.knowledge import group_artifacts

    a1 = Artifact(
        kind="conversation.summary",
        workspace=WS,
        produced_by="resume-agent",
        content={"summary": "old"},
        metadata={"thread_name": "T", "model": "m1"},
    )
    a2 = a1.model_copy(
        update={"content": {"summary": "new"}, "metadata": {"thread_name": "T", "model": "m2"},
                "timestamp": _later(a1.timestamp)}
    )
    other = Artifact(
        kind="conversation.summary",
        workspace=WS,
        produced_by="resume-agent",
        content={"summary": "x"},
        metadata={"thread_name": "U"},
    )

    groups = group_artifacts([a1, a2, other])
    assert len(groups) == 2  # two subjects: T and U
    thread_t = next(g for g in groups if g[0].metadata.get("thread_name") == "T")
    assert [a.metadata["model"] for a in thread_t] == ["m2", "m1"]  # newest first


