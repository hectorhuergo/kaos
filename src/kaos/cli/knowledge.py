"""`kaos knowledge` and `kaos dashboard`: inspect the accumulated knowledge.

Builds a knowledge graph (`kaos.core.knowledge`) from the stored artifacts and
renders it as a list, Mermaid, JSON, or a self-contained HTML dashboard. The
workspaces come from ``--workspace`` or, if omitted, from the active
subscriptions — so ``kaos knowledge`` shows everything KAOS manages.
"""

from __future__ import annotations

import json
from pathlib import Path

from kaos.bootstrap.factory import build_storage, build_subscription_store
from kaos.core.config import Settings
from kaos.core.knowledge import build_graph
from kaos.domain.subscription import Subscription
from kaos.plugins.dashboard import render_dashboard


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


def _normalize(workspace: str) -> str:
    """Accept a bare Discord id and turn it into a canonical workspace."""
    return workspace if ":" in workspace else Subscription.workspace_for(workspace)


async def _resolve_workspaces(
    workspace: str | None, settings: Settings
) -> list[str]:
    """Return the workspaces to inspect: the given one, or all subscriptions."""
    if workspace:
        return [_normalize(workspace)]
    store = build_subscription_store(settings)
    try:
        subs = await store.list(active_only=True)
    finally:
        await _close(store)
    return [s.workspace for s in subs]


async def run_knowledge(
    *,
    workspace: str | None = None,
    fmt: str = "text",
    include_events: bool = False,
    settings: Settings | None = None,
) -> int:
    """Print the knowledge graph as text, Mermaid or JSON."""
    settings = settings if settings is not None else Settings.from_env()
    workspaces = await _resolve_workspaces(workspace, settings)
    if not workspaces:
        print("(sin workspaces — usa --workspace o crea una suscripción)")
        return 0

    storage = build_storage(settings)
    try:
        graph = await build_graph(storage, workspaces, include_events=include_events)
    finally:
        await _close(storage)

    if fmt == "json":
        print(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2))
    elif fmt == "mermaid":
        print(graph.to_mermaid())
    else:
        _print_text(graph)
    return 0


def _print_text(graph) -> int:  # type: ignore[no-untyped-def]
    from kaos.core.knowledge import ARTIFACT, WORKSPACE

    workspaces = [n for n in graph.nodes if n.kind == WORKSPACE]
    artifacts = [n for n in graph.nodes if n.kind == ARTIFACT]
    print(f"KAOS knowledge — {len(workspaces)} workspace(s), {len(artifacts)} artifact(s)\n")
    for ws in workspaces:
        print(f"# {ws.label}")
        for node in artifacts:
            # An artifact belongs to this workspace if there is a contains edge.
            if any(e.source == ws.id and e.target == node.id for e in graph.edges):
                model = node.meta.get("model") or "-"
                count = node.meta.get("message_count")
                count_s = f"{count} msgs" if count is not None else "-"
                print(f"  · {node.label:28} [{node.meta.get('artifact_kind')}]  {model}  {count_s}")
        print()
    return 0


async def run_dashboard(
    *,
    workspace: str | None = None,
    out: str = "kaos-dashboard.html",
    include_events: bool = False,
    settings: Settings | None = None,
) -> int:
    """Write a self-contained HTML dashboard of the knowledge."""
    settings = settings if settings is not None else Settings.from_env()
    workspaces = await _resolve_workspaces(workspace, settings)
    if not workspaces:
        print("(sin workspaces — usa --workspace o crea una suscripción)")
        return 0

    storage = build_storage(settings)
    try:
        graph = await build_graph(storage, workspaces, include_events=include_events)
        sections = [(ws, list(await storage.list_artifacts(ws))) for ws in workspaces]
    finally:
        await _close(storage)

    html_doc = render_dashboard(sections, graph)
    path = Path(out)
    path.write_text(html_doc, encoding="utf-8")
    total = sum(len(a) for _, a in sections)
    print(f"Dashboard escrito en {path} ({total} artifact(s), {len(workspaces)} workspace(s)).")
    return 0

