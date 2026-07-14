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
    RELATED_TO,
    WORKSPACE,
    build_graph,
    relate_workspaces,
)
from kaos.plugins.dashboard import render_dashboard
from kaos.plugins.dashboard.metrics import summarize_workspace
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
    assert "assets" in html_doc.lower()
    assert "Estado" in html_doc
    # Mermaid must load as a classic UMD script (global), not as an ES module:
    # importing the UMD build as a module fails silently and shows raw text.
    assert "<script src=" in html_doc
    assert "type=\"module\"" not in html_doc


def test_workspace_metrics_capture_assets_agents_and_models() -> None:
    storage = _seed()
    artifacts = asyncio.run(storage.list_artifacts(WS))
    metrics = summarize_workspace(artifacts)
    assert metrics["asset_count"] == 2
    assert metrics["artifact_count"] == 2
    assert metrics["agents"] == ["resume-agent"]
    assert metrics["models"] == ["gpt-4o"]


def test_empty_workspaces_produce_empty_graph() -> None:
    graph = asyncio.run(build_graph(InMemoryStorage(), []))
    assert graph.nodes == []
    assert graph.edges == []


def test_relabel_applies_friendly_names_to_workspace_nodes() -> None:
    """The dashboard shows the channel/forum name, not the raw workspace id."""
    storage = _seed()
    graph = asyncio.run(build_graph(storage, [WS]))

    ws_node = next(n for n in graph.nodes if n.kind == WORKSPACE)
    assert ws_node.label == WS  # raw id before relabeling

    graph.relabel({WS: "📋 PMO"})

    ws_node = next(n for n in graph.nodes if n.kind == WORKSPACE)
    assert ws_node.id == WS  # id stays canonical
    assert ws_node.label == "📋 PMO"  # label is the friendly name
    # Artifact labels (no mapping given) are untouched.
    assert {n.label for n in graph.nodes if n.kind == ARTIFACT} == {
        "PMO",
        "📊 Estado del Proyecto",
    }
    # A raw id must no longer surface in the JSON the graph endpoint returns.
    labels = {n["label"] for n in graph.to_dict()["nodes"]}
    assert WS not in labels


def test_relate_workspaces_links_same_project_islands() -> None:
    """Forum + repo of the same project connect; an unrelated repo stays apart."""
    labels = {
        "discord:1": "proyecto-x",           # forum
        "github:acme/proyecto-x-grid": "acme/proyecto-x-grid",  # related repo
        "github:acme/kaos": "acme/kaos",     # unrelated repo
    }

    edges = relate_workspaces(labels)

    assert all(e.kind == RELATED_TO for e in edges)
    pairs = {tuple(sorted((e.source, e.target))) for e in edges}
    # proyecto-x forum ↔ proyecto-x-grid repo are linked.
    assert ("discord:1", "github:acme/proyecto-x-grid") in pairs
    # kaos is not linked to anything.
    assert not any("github:acme/kaos" in pair for pair in pairs)
    assert len(edges) == 1


def test_relate_workspaces_needs_two_shared_leading_tokens() -> None:
    """A single shared (possibly generic) leading token is not enough."""
    labels = {
        "github:acme/proyecto-a": "acme/proyecto-a",
        "github:acme/proyecto-b": "acme/proyecto-b",
    }
    # Share only ["proyecto"] as leading tokens (the next differ) → not related.
    assert relate_workspaces(labels) == []
    # Lowering the threshold relates them.
    assert len(relate_workspaces(labels, min_shared_tokens=1)) == 1


def test_relate_workspaces_explicit_relations_link_arbitrary_pairs() -> None:
    """Ad-hoc ``relations`` connect two workspaces with no name/project overlap."""
    labels = {
        "discord:1": "soporte",
        "github:acme/kaos": "acme/kaos",
        "github:acme/lonely": "acme/lonely",
    }
    relations = {"discord:1": ["github:acme/kaos"]}  # operator-set relation
    edges = relate_workspaces(labels, relations=relations)
    pairs = {tuple(sorted((e.source, e.target))) for e in edges}
    assert ("discord:1", "github:acme/kaos") in pairs
    assert not any("github:acme/lonely" in pair for pair in pairs)


def test_relate_workspaces_relations_ignore_unknown_and_self() -> None:
    """Relations to workspaces not in view (or to self) are dropped."""
    labels = {"discord:1": "a", "github:acme/kaos": "acme/kaos"}
    relations = {
        "discord:1": ["discord:1", "github:missing"],  # self + not in view
        "github:acme/kaos": ["discord:1"],  # valid
    }
    edges = relate_workspaces(labels, relations=relations)
    pairs = {tuple(sorted((e.source, e.target))) for e in edges}
    assert pairs == {("discord:1", "github:acme/kaos")}


def test_relate_workspaces_explicit_project_groups_unrelated_names() -> None:
    """An explicit project connects workspaces even when names don't match.

    ``kaos`` shares no name prefix with ``proyecto-x``, but as the project's
    'brain' it is grouped under the same project and thus related.
    """
    labels = {
        "discord:1": "proyecto-x",
        "github:acme/kaos": "acme/kaos",
        "github:acme/other": "acme/other",
    }
    projects = {
        "discord:1": "proyecto-x",
        "github:acme/kaos": "proyecto-x",
        "github:acme/other": None,  # not part of the project
    }
    edges = relate_workspaces(labels, projects=projects)
    pairs = {tuple(sorted((e.source, e.target))) for e in edges}
    assert ("discord:1", "github:acme/kaos") in pairs  # brain joins the project
    assert not any("github:acme/other" in pair for pair in pairs)


def test_relate_workspaces_dedupes_name_and_project_signals() -> None:
    """A pair related by both name prefix and project yields a single edge."""
    labels = {
        "discord:1": "proyecto-x",
        "github:acme/proyecto-x-grid": "acme/proyecto-x-grid",
    }
    projects = {
        "discord:1": "proyecto-x",
        "github:acme/proyecto-x-grid": "proyecto-x",
    }
    edges = relate_workspaces(labels, projects=projects)
    assert len(edges) == 1  # not duplicated across the two signals


def test_relate_workspaces_emits_one_stable_edge_per_pair() -> None:
    """Two repos of the same project yield a single, order-stable edge."""
    labels = {
        "github:acme/proyecto-x-api": "acme/proyecto-x-api",
        "github:acme/proyecto-x-grid": "acme/proyecto-x-grid",
    }
    edges = relate_workspaces(labels)
    assert len(edges) == 1
    edge = edges[0]
    assert (edge.source, edge.target) == (
        "github:acme/proyecto-x-api",
        "github:acme/proyecto-x-grid",
    )  # sorted order


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


