"""Live dashboard: a FastAPI app that serves the knowledge, always current.

Unlike the static HTML export, this reads `Storage` on each request, so the view
reflects the latest artifacts without regenerating a file. FastAPI is imported
lazily inside `create_app` so importing this module never requires the web
stack; `kaos serve` wires it to uvicorn.

Routes:
- ``GET /``                  → the HTML dashboard (same renderer as the export).
- ``GET /api/workspaces``    → the workspaces KAOS manages.
- ``GET /api/knowledge``     → the knowledge graph as JSON (nodes/edges).
- ``GET /api/artifacts``     → the stored artifacts (optionally by workspace).
"""

from __future__ import annotations

from typing import Any

from kaos.core.config import Settings
from kaos.plugins.dashboard import render_dashboard
from kaos.plugins.dashboard.service import artifacts_to_dicts, load_knowledge


def create_app(settings: Settings | None = None) -> Any:
    """Build the FastAPI dashboard app.

    ``settings`` defaults to the environment. The app is intentionally
    read-only: it exposes knowledge, never mutates it.
    """
    from fastapi import FastAPI, Query
    from fastapi.responses import HTMLResponse

    cfg = settings if settings is not None else Settings.from_env()
    app = FastAPI(title="KAOS Dashboard", version="1.0.0-beta.1")

    @app.get("/", response_class=HTMLResponse)
    async def index(
        workspace: str | None = Query(default=None),
        events: bool = Query(default=False),
    ) -> str:
        _ws, graph, sections = await load_knowledge(
            cfg, workspace=workspace, include_events=events
        )
        return render_dashboard(sections, graph)

    @app.get("/api/workspaces")
    async def api_workspaces() -> dict[str, list[str]]:
        workspaces, _graph, _sections = await load_knowledge(cfg)
        return {"workspaces": workspaces}

    @app.get("/api/knowledge")
    async def api_knowledge(
        workspace: str | None = Query(default=None),
        events: bool = Query(default=False),
    ) -> dict[str, Any]:
        _ws, graph, _sections = await load_knowledge(
            cfg, workspace=workspace, include_events=events
        )
        return graph.to_dict()

    @app.get("/api/artifacts")
    async def api_artifacts(
        workspace: str | None = Query(default=None),
    ) -> dict[str, Any]:
        _ws, _graph, sections = await load_knowledge(cfg, workspace=workspace)
        return {
            "artifacts": [
                {"workspace": ws, "items": artifacts_to_dicts(arts)}
                for ws, arts in sections
            ]
        }

    return app

