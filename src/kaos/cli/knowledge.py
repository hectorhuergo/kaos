"""`kaos knowledge`, `kaos dashboard` and `kaos serve`: inspect the knowledge.

Builds a knowledge graph (`kaos.core.knowledge`) from the stored artifacts and
renders it as a list, Mermaid, JSON, a self-contained HTML file, or a live
FastAPI dashboard. Workspaces come from ``--workspace`` or, if omitted, from the
active subscriptions — so ``kaos knowledge`` shows everything KAOS manages.
"""

from __future__ import annotations

import json
from pathlib import Path

from kaos.core.config import Settings
from kaos.core.knowledge import ARTIFACT, WORKSPACE, KnowledgeGraph, relate_workspaces
from kaos.plugins.dashboard import render_dashboard
from kaos.plugins.dashboard.directory import resolve_labels
from kaos.plugins.dashboard.service import load_knowledge, load_projects, load_relations


async def run_knowledge(
    *,
    workspace: str | None = None,
    fmt: str = "text",
    include_events: bool = False,
    settings: Settings | None = None,
) -> int:
    """Print the knowledge graph as text, Mermaid or JSON."""
    settings = settings if settings is not None else Settings.from_env()
    workspaces, graph, _sections = await load_knowledge(
        settings, workspace=workspace, include_events=include_events
    )
    if not workspaces:
        print("(sin workspaces — usa --workspace o crea una suscripción)")
        return 0

    # Friendly names on the nodes + relate workspaces of the same project
    # (by name prefix and by explicit ``project`` grouping).
    labels = await resolve_labels(workspaces, settings)
    graph.relabel(labels)
    projects = await load_projects(settings, workspaces)
    relations = await load_relations(settings, workspaces)
    graph.edges.extend(relate_workspaces(labels, projects=projects, relations=relations))

    if fmt == "json":
        print(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2))
    elif fmt == "mermaid":
        print(graph.to_mermaid())
    else:
        _print_text(graph)
    return 0


def _print_text(graph: KnowledgeGraph) -> None:
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


async def run_dashboard(
    *,
    workspace: str | None = None,
    out: str = "kaos-dashboard.html",
    include_events: bool = False,
    settings: Settings | None = None,
) -> int:
    """Write a self-contained HTML dashboard of the knowledge."""
    settings = settings if settings is not None else Settings.from_env()
    workspaces, graph, sections = await load_knowledge(
        settings, workspace=workspace, include_events=include_events
    )
    if not workspaces:
        print("(sin workspaces — usa --workspace o crea una suscripción)")
        return 0

    # Friendly names on the nodes/sections + relate workspaces of the same project.
    labels = await resolve_labels(workspaces, settings)
    graph.relabel(labels)
    projects = await load_projects(settings, workspaces)
    relations = await load_relations(settings, workspaces)
    graph.edges.extend(relate_workspaces(labels, projects=projects, relations=relations))

    path = Path(out)
    path.write_text(
        render_dashboard(sections, graph, workspace_labels=labels), encoding="utf-8"
    )
    total = sum(len(a) for _, a in sections)
    print(f"Dashboard escrito en {path} ({total} artifact(s), {len(workspaces)} workspace(s)).")
    return 0


def run_serve(*, host: str = "127.0.0.1", port: int = 8000) -> int:
    """Serve the live FastAPI dashboard with uvicorn."""
    try:
        import uvicorn
    except ModuleNotFoundError:
        print("error: falta 'uvicorn'. Instálalo con: pip install -e .[dashboard]")
        return 1

    from kaos.plugins.dashboard.app import create_app

    print(f"KAOS dashboard vivo en http://{host}:{port}  (Ctrl-C para detener)")
    print(f"KAOS consola en      http://{host}:{port}/console")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
    return 0



