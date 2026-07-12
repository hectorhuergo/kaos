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
        # Keep *all* artifacts here (the graph is deduped to one node per subject,
        # but the view groups the versions of a node into a navigable card, so it
        # needs the full history — e.g. the same thread summarized by two models).
        sections: list[tuple[str, list[Artifact]]] = [
            (ws, list(await store.list_artifacts(ws))) for ws in workspaces
        ]
    finally:
        if storage is None:
            await _close(store)
    return workspaces, graph, sections


async def load_projects(
    settings: Settings,
    workspaces: Sequence[str],
    *,
    subscription_store: SubscriptionStore | None = None,
) -> dict[str, str | None]:
    """Map each workspace in view to its subscription's ``project`` (if any).

    Feeds the explicit cross-workspace relations (ADR-0019): workspaces sharing a
    project are linked in the graph. Only workspaces present in ``workspaces`` are
    returned. ``subscription_store`` can be injected to reuse a shared store.
    """
    store = subscription_store or build_subscription_store(settings)
    try:
        subs = await store.list(active_only=True)
    finally:
        if subscription_store is None:
            await _close(store)
    wanted = set(workspaces)
    return {s.workspace: s.project for s in subs if s.workspace in wanted}


async def load_relations(
    settings: Settings,
    workspaces: Sequence[str],
    *,
    subscription_store: SubscriptionStore | None = None,
) -> dict[str, list[str]]:
    """Map each in-view workspace to the workspaces it is explicitly related to.

    Feeds the ad-hoc ``related_to`` edges an operator sets per subscription. Both
    endpoints are restricted to the workspaces in view. ``subscription_store`` can
    be injected to reuse a shared store.
    """
    store = subscription_store or build_subscription_store(settings)
    try:
        subs = await store.list(active_only=True)
    finally:
        if subscription_store is None:
            await _close(store)
    wanted = set(workspaces)
    return {
        s.workspace: [w for w in s.related_to if w in wanted]
        for s in subs
        if s.workspace in wanted and s.related_to
    }


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

