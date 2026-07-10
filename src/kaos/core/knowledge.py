"""Knowledge graph: a queryable projection over the knowledge already stored.

KAOS persists two immutable things: *events* (what happened) and *artifacts*
(what is known, e.g. a conversation summary or a project status). Every artifact
traces back to the events that produced it (`source_events`). The Knowledge
Graph turns that existing, traceable structure into nodes and edges so the
accumulated knowledge can be inspected and rendered — no new datastore, just a
read-model over the `Storage` contract (Knowledge before Reports).

The model is pure data (no external deps): it can be built from any `Storage`
and exported to a plain dict (JSON) or Mermaid for a dashboard.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from kaos.contracts.storage import Storage

# Node kinds.
WORKSPACE = "workspace"
ARTIFACT = "artifact"
EVENT = "event"

# Edge kinds.
CONTAINS = "contains"          # workspace -> artifact
DERIVED_FROM = "derived_from"  # artifact  -> event


@dataclass(frozen=True)
class KnowledgeNode:
    """A node in the knowledge graph (a workspace, artifact or event)."""

    id: str
    kind: str
    label: str
    meta: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeEdge:
    """A directed relation between two nodes."""

    source: str
    target: str
    kind: str


@dataclass
class KnowledgeGraph:
    """A set of nodes and edges projected from stored knowledge."""

    nodes: list[KnowledgeNode] = field(default_factory=list)
    edges: list[KnowledgeEdge] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set, repr=False)

    def add_node(self, node: KnowledgeNode) -> None:
        """Append a node, ignoring duplicates by id (shared across workspaces)."""
        if node.id in self._seen:
            return
        self._seen.add(node.id)
        self.nodes.append(node)

    def add_edge(self, edge: KnowledgeEdge) -> None:
        self.edges.append(edge)

    def to_dict(self) -> dict[str, list[dict[str, object]]]:
        """Return a JSON-serializable representation of the graph."""
        return {
            "nodes": [
                {"id": n.id, "kind": n.kind, "label": n.label, "meta": n.meta}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "kind": e.kind}
                for e in self.edges
            ],
        }

    def to_mermaid(self) -> str:
        """Render the graph as a Mermaid ``graph TD`` diagram.

        Node ids (UUIDs, ``discord:123``) are aliased to safe ``nN`` handles so
        the diagram stays valid regardless of the original id characters.
        """
        alias = {node.id: f"n{i}" for i, node in enumerate(self.nodes)}
        shape = {WORKSPACE: ("[[", "]]"), ARTIFACT: ("[", "]"), EVENT: ("(", ")")}
        lines = ["graph TD"]
        for node in self.nodes:
            open_b, close_b = shape.get(node.kind, ("[", "]"))
            lines.append(f'    {alias[node.id]}{open_b}"{_escape(node.label)}"{close_b}')
        for edge in self.edges:
            src, tgt = alias.get(edge.source), alias.get(edge.target)
            if src is None or tgt is None:
                continue
            lines.append(f"    {src} -->|{edge.kind}| {tgt}")
        return "\n".join(lines)


def _escape(text: str) -> str:
    """Make a label safe inside a Mermaid quoted node.

    Mermaid can choke on characters like ``()[]{}|<>`` even inside quotes, so we
    replace them (and collapse whitespace) to keep the diagram parseable.
    """
    cleaned = text
    for ch in '"()[]{}|<>`#;':
        cleaned = cleaned.replace(ch, " ")
    return " ".join(cleaned.split())


def _artifact_label(kind: str, meta: dict[str, object], content: dict[str, object]) -> str:
    """Human-readable label for an artifact node."""
    thread = meta.get("thread_name")
    if thread:
        return str(thread)
    if kind == "project.status":
        return "📊 Estado del Proyecto"
    return kind


async def build_graph(
    storage: Storage,
    workspaces: Iterable[str],
    *,
    include_events: bool = False,
    event_label_length: int = 60,
) -> KnowledgeGraph:
    """Build a knowledge graph from the artifacts (and optionally events) stored.

    Each workspace becomes a node containing its artifacts; each artifact links
    to the events it was derived from when ``include_events`` is set. Events are
    excluded by default because a real conversation can have hundreds of them —
    the artifact-level graph is the useful overview.
    """
    graph = KnowledgeGraph()
    for workspace in workspaces:
        graph.add_node(KnowledgeNode(id=workspace, kind=WORKSPACE, label=workspace))

        events_by_id: dict[str, object] = {}
        if include_events:
            events_by_id = {str(e.id): e for e in await storage.list_events(workspace)}

        for artifact in await storage.list_artifacts(workspace):
            aid = str(artifact.id)
            graph.add_node(
                KnowledgeNode(
                    id=aid,
                    kind=ARTIFACT,
                    label=_artifact_label(artifact.kind, artifact.metadata, artifact.content),
                    meta={
                        "artifact_kind": artifact.kind,
                        "produced_by": artifact.produced_by,
                        "model": artifact.metadata.get("model"),
                        "thread_name": artifact.metadata.get("thread_name"),
                        "message_count": artifact.content.get("message_count"),
                        "timestamp": artifact.timestamp.isoformat(),
                    },
                )
            )
            graph.add_edge(KnowledgeEdge(source=workspace, target=aid, kind=CONTAINS))

            if include_events:
                _add_event_nodes(
                    graph, aid, artifact.source_events, events_by_id, event_label_length
                )
    return graph


def _add_event_nodes(
    graph: KnowledgeGraph,
    artifact_id: str,
    source_events: Sequence[object],
    events_by_id: dict[str, object],
    label_length: int,
) -> None:
    for ev_id in source_events:
        key = str(ev_id)
        event = events_by_id.get(key)
        if event is not None:
            payload = getattr(event, "payload", {})
            author = payload.get("author", "unknown")
            text = str(payload.get("text", ""))[:label_length]
            label = f"{author}: {text}"
        else:
            label = key
        graph.add_node(KnowledgeNode(id=key, kind=EVENT, label=label))
        graph.add_edge(KnowledgeEdge(source=artifact_id, target=key, kind=DERIVED_FROM))

