"""Shared knowledge-loading service for the CLI and the live dashboard.

Resolves which workspaces to inspect (an explicit one or the active
subscriptions) and loads the knowledge graph + artifacts from `Storage`. Both
`kaos knowledge/dashboard` (CLI) and the FastAPI app build on this, so the
projection logic lives in one place.
"""

from __future__ import annotations

from collections.abc import Sequence

from kaos.bootstrap.factory import build_storage, build_subscription_store
from kaos.contracts.artifact import Artifact
from kaos.contracts.storage import Storage
from kaos.contracts.subscription import SubscriptionStore
from kaos.core.config import Settings
from kaos.core.knowledge import KnowledgeGraph, build_graph
from kaos.domain.subscription import Subscription


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


def normalize_workspace(workspace: str) -> str:
    """Accept a bare Discord id and turn it into a canonical workspace."""
    return workspace if ":" in workspace else Subscription.workspace_for(workspace)


async def resolve_workspaces(
    workspace: str | None,
    settings: Settings,
    *,
    subscription_store: SubscriptionStore | None = None,
) -> list[str]:
    """Return the workspaces to inspect: the given one, or all subscriptions.

    ``subscription_store`` can be injected to reuse a shared store (the live
    app owns its lifecycle); otherwise a store is built and closed here.
    """
    if workspace:
        return [normalize_workspace(workspace)]
    store = subscription_store or build_subscription_store(settings)
    try:
        subs = await store.list(active_only=True)
    finally:
        if subscription_store is None:
            await _close(store)
    return [s.workspace for s in subs]


async def load_knowledge(
    settings: Settings,
    *,
    workspace: str | None = None,
    include_events: bool = False,
    storage: Storage | None = None,
    subscription_store: SubscriptionStore | None = None,
) -> tuple[list[str], KnowledgeGraph, list[tuple[str, list[Artifact]]]]:
    """Load the workspaces, the knowledge graph and per-workspace artifacts.

    ``storage`` and ``subscription_store`` can be injected to reuse shared
    instances (the caller then owns their lifecycle); otherwise they are built
    from ``settings`` and closed here.
    """
    workspaces = await resolve_workspaces(
        workspace, settings, subscription_store=subscription_store
    )
    store = storage or build_storage(settings)
    try:
        graph = await build_graph(store, workspaces, include_events=include_events)
        sections: list[tuple[str, list[Artifact]]] = [
            (ws, list(await store.list_artifacts(ws))) for ws in workspaces
        ]
    finally:
        if storage is None:
            await _close(store)
    return workspaces, graph, sections


def artifacts_to_dicts(artifacts: Sequence[Artifact]) -> list[dict[str, object]]:
    """Serialize artifacts for the JSON API (ids and datetimes as strings)."""
    return [
        {
            "id": str(a.id),
            "kind": a.kind,
            "workspace": a.workspace,
            "produced_by": a.produced_by,
            "content": a.content,
            "metadata": a.metadata,
            "timestamp": a.timestamp.isoformat(),
        }
        for a in artifacts
    ]

