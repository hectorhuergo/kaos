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

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from kaos.contracts.artifact import Artifact
from kaos.contracts.storage import Storage

# Node kinds.
WORKSPACE = "workspace"
ARTIFACT = "artifact"
EVENT = "event"

# Edge kinds.
CONTAINS = "contains"          # workspace -> artifact
DERIVED_FROM = "derived_from"  # artifact  -> event
RELATED_TO = "related_to"      # workspace <-> workspace (shared project name)


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

    def relabel(self, labels: Mapping[str, str]) -> None:
        """Replace node labels by id with friendly names (in place).

        The projection is built with canonical ids as labels (``discord:123``)
        because the Core stays agnostic of any provider's naming. A view that can
        resolve friendly names (e.g. the dashboard, via the Discord REST API)
        applies them here so the rendered graph shows the channel/forum name
        instead of the raw workspace id — without leaking that lookup into Core.
        """
        if not labels:
            return
        self.nodes = [
            replace(node, label=labels[node.id]) if node.id in labels else node
            for node in self.nodes
        ]

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
    dedupe: bool = True,
) -> KnowledgeGraph:
    """Build a knowledge graph from the artifacts (and optionally events) stored.

    Each workspace becomes a node containing its artifacts; each artifact links
    to the events it was derived from when ``include_events`` is set. Events are
    excluded by default because a real conversation can have hundreds of them —
    the artifact-level graph is the useful overview.

    When ``dedupe`` is set (the default), only the most recent artifact per
    logical subject (its thread, or its kind) is kept. Re-summarizing the same
    conversation — e.g. after switching the LLM model — produces a *new*
    artifact with a different id; keeping only the latest avoids showing the same
    knowledge duplicated once per model/run (Knowledge before Reports: the last
    summary supersedes the previous ones).
    """
    graph = KnowledgeGraph()
    for workspace in workspaces:
        graph.add_node(KnowledgeNode(id=workspace, kind=WORKSPACE, label=workspace))

        events_by_id: dict[str, object] = {}
        if include_events:
            events_by_id = {str(e.id): e for e in await storage.list_events(workspace)}

        artifacts = list(await storage.list_artifacts(workspace))
        if dedupe:
            artifacts = latest_artifacts(artifacts)

        for artifact in artifacts:
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


def latest_artifacts(artifacts: Sequence[Artifact]) -> list[Artifact]:
    """Keep only the most recent artifact per logical subject.

    The subject key is the artifact's thread (``metadata.thread_name``) when it
    has one, otherwise its ``kind``. This collapses the duplicates produced by
    re-summarizing the same conversation with different models/runs, keeping the
    newest by ``timestamp``. Order is preserved (first appearance of each key).

    Shared by the graph projection (:func:`build_graph`) and the artifact
    sections rendered under it, so both views agree.
    """
    latest: dict[tuple[str, str], Artifact] = {}
    order: list[tuple[str, str]] = []
    for artifact in artifacts:
        thread = artifact.metadata.get("thread_name")
        key = (artifact.kind, str(thread) if thread else "")
        current = latest.get(key)
        if current is None:
            latest[key] = artifact
            order.append(key)
        elif artifact.timestamp >= current.timestamp:
            latest[key] = artifact
    return [latest[key] for key in order]


def _subject_key(artifact: Artifact) -> tuple[str, str]:
    """The logical-subject key: its thread when present, otherwise its kind."""
    thread = artifact.metadata.get("thread_name")
    return (artifact.kind, str(thread) if thread else "")


def group_artifacts(artifacts: Sequence[Artifact]) -> list[list[Artifact]]:
    """Group artifacts by logical subject, newest first within each group.

    Complements :func:`latest_artifacts`: instead of dropping the older versions
    of a subject, it keeps them together so the view can show every version of a
    node (e.g. the same thread summarized by two models) as a navigable card. The
    group order follows the first appearance of each subject; within a group the
    artifacts are sorted by ``timestamp`` descending (latest first).
    """
    groups: dict[tuple[str, str], list[Artifact]] = {}
    order: list[tuple[str, str]] = []
    for artifact in artifacts:
        key = _subject_key(artifact)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(artifact)
    return [
        sorted(groups[key], key=lambda a: a.timestamp, reverse=True) for key in order
    ]


def _project_tokens(label: str) -> list[str]:
    """Tokens of a workspace's project name (its most specific path segment).

    GitHub labels read as ``owner/repo``; only the repo carries the project name,
    so we keep the last ``/`` segment. The name is lower-cased and split on any
    non-alphanumeric run, so ``proyecto-x-grid`` → ``["proyecto", "x", "grid"]``.
    """
    name = label.rsplit("/", 1)[-1]
    return [tok for tok in re.split(r"[^0-9a-z]+", name.lower()) if tok]


def _shared_leading(a: Sequence[str], b: Sequence[str]) -> int:
    """How many leading tokens two token lists share."""
    count = 0
    for left, right in zip(a, b, strict=False):
        if left != right:
            break
        count += 1
    return count


def relate_workspaces(
    labels: Mapping[str, str],
    *,
    projects: Mapping[str, str | None] | None = None,
    relations: Mapping[str, Iterable[str]] | None = None,
    min_shared_tokens: int = 2,
) -> list[KnowledgeEdge]:
    """Link workspaces that belong to the same project or are explicitly related.

    Three complementary signals produce a ``related_to`` edge:

    1. **Explicit grouping** (authoritative): when ``projects`` maps workspaces to
       a project name, every pair sharing the same (case-insensitive) project is
       linked. This is how a workspace whose name shares nothing with the others
       — e.g. the ``kaos`` repo, the *brain* of ``proyecto-x`` — still joins the
       project (ADR-0019).
    2. **Explicit relations** (ad-hoc): ``relations`` maps a workspace to the
       other workspaces it is explicitly related to, linking pairs an operator
       connected by hand even when they share neither name nor project.
    3. **Name heuristic**: two workspaces whose names (the most specific path
       segment, tokenized) share at least ``min_shared_tokens`` leading tokens are
       linked — e.g. the forum ``proyecto-x`` and the repo ``proyecto-x-grid``.

    All are deterministic (no LLM, no network) and turn the otherwise-isolated
    per-workspace islands into a connected view. Edges are undirected: a single
    edge per pair is emitted with the workspace ids in a stable (sorted) order,
    deduplicated across all signals, and restricted to workspaces present in
    ``labels`` (the ones in view). Callers pass already-resolved labels, keeping
    the Core agnostic of how names are looked up.
    """
    known = set(labels)
    pairs: set[tuple[str, str]] = set()

    # 1) Explicit project grouping.
    if projects:
        by_project: dict[str, list[str]] = {}
        for workspace, project in projects.items():
            name = (project or "").strip().lower()
            if name and workspace in known:
                by_project.setdefault(name, []).append(workspace)
        for members in by_project.values():
            for i, ws_a in enumerate(members):
                for ws_b in members[i + 1 :]:
                    pairs.add(_ordered_pair(ws_a, ws_b))

    # 2) Explicit ad-hoc relations between subscriptions.
    if relations:
        for workspace, others in relations.items():
            if workspace not in known:
                continue
            for other in others:
                if other in known and other != workspace:
                    pairs.add(_ordered_pair(workspace, other))

    # 3) Name-prefix heuristic.
    tokens = {ws: _project_tokens(label) for ws, label in labels.items()}
    workspaces = list(labels)
    for i, ws_a in enumerate(workspaces):
        for ws_b in workspaces[i + 1 :]:
            if _shared_leading(tokens[ws_a], tokens[ws_b]) >= min_shared_tokens:
                pairs.add(_ordered_pair(ws_a, ws_b))

    return [
        KnowledgeEdge(source=source, target=target, kind=RELATED_TO)
        for source, target in sorted(pairs)
    ]


def _ordered_pair(a: str, b: str) -> tuple[str, str]:
    """Return the two ids in a stable (sorted) order for dedup/undirected edges."""
    return (a, b) if a <= b else (b, a)


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

