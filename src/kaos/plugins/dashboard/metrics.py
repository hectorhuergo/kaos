"""Pure helpers for dashboard KPIs derived from artifacts."""

from __future__ import annotations

from collections.abc import Sequence

from kaos.contracts.artifact import Artifact
from kaos.core.agents import agent_catalog
from kaos.core.knowledge import group_artifacts

# Friendly names for the producers seen on artifacts. Chat turns are produced by
# the synthetic ``chat-agent`` (not part of the plugin agent catalog).
_AGENT_LABELS: dict[str, str] = {a.id: a.label for a in agent_catalog()}
_AGENT_LABELS.setdefault("chat-agent", "Chat")


def _agent_label(agent_id: str) -> str:
    return _AGENT_LABELS.get(agent_id, agent_id)


def summarize_workspace(artifacts: Sequence[Artifact]) -> dict[str, object]:
    """Return generic KPIs for one workspace's artifacts."""
    items = list(artifacts)
    groups = group_artifacts(items)
    last_execution = max((a.timestamp for a in items), default=None)
    agents = sorted(
        {
            str(a.metadata.get("agent_id") or a.produced_by)
            for a in items
            if a.metadata.get("agent_id") or a.produced_by
        }
    )
    models = sorted(
        {str(a.metadata.get("model")) for a in items if a.metadata.get("model")}
    )
    projects = sorted(
        {str(a.metadata.get("project")) for a in items if a.metadata.get("project")}
    )
    kinds = sorted({a.kind for a in items})
    session_ids = sorted(
        {
            str(a.metadata.get("session_id") or a.content.get("session_id"))
            for a in items
            if a.metadata.get("session_id") or a.content.get("session_id")
        }
    )
    message_count = 0
    for a in items:
        count = a.content.get("message_count")
        if isinstance(count, int):
            message_count += count
    return {
        "artifact_count": len(items),
        "asset_count": len(groups),
        "last_execution": last_execution.isoformat(timespec="seconds") if last_execution else None,
        "agents": agents,
        "agent_labels": sorted({_agent_label(a) for a in agents}),
        "models": models,
        "projects": projects,
        "kinds": kinds,
        "session_count": len(session_ids),
        "message_count": message_count,
        "session_ids": session_ids,
    }


def summarize_many(
    workspaces: Sequence[tuple[str, Sequence[Artifact]]]
) -> dict[str, dict[str, object]]:
    """Summarize a batch of workspace/artifact pairs."""
    return {workspace: summarize_workspace(artifacts) for workspace, artifacts in workspaces}

