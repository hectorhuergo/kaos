"""Chat session persistence and response helpers for the dashboard."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from kaos.bootstrap.factory import build_llm, load_settings
from kaos.contracts.artifact import Artifact
from kaos.contracts.context import Context
from kaos.contracts.event import Event, utcnow
from kaos.contracts.llm import Message
from kaos.contracts.storage import Storage
from kaos.core.agents import agent_catalog
from kaos.core.config import Settings
from kaos.core.redaction import redact_secrets
from kaos.plugins.agents import DevAgent
from kaos.plugins.tools import default_dev_tools
from kaos.sdk import EchoLLMProvider

SESSION_CREATED = "chat.session.created"
USER_MESSAGE = "chat.message.user"
ASSISTANT_MESSAGE = "chat.message.assistant"
TURN_ARTIFACT = "chat.turn"
CONTRIBUTION_EVENT = "message.contribution"

# Agents that work by running a tool-use loop instead of a single completion.
TOOL_USING_AGENTS = frozenset({"dev-agent"})


@dataclass(frozen=True)
class ChatSessionSummary:
    session_id: str
    workspace: str
    user_id: str
    agent_id: str
    project: str | None
    kind: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int
    model: str | None
    last_message: str


def _agent_prompt(agent_id: str) -> str:
    agent = next((a for a in agent_catalog() if a.id == agent_id), None)
    if agent is None:
        return "Sos el asistente de chat de KAOS. Respondé en Markdown, con foco y claridad."
    if agent.id == "resume-agent":
        return (
            "Sos el Resume Agent de KAOS. Respondé como un asistente ejecutivo, "
            "con resúmenes claros y sin inventar información."
        )
    if agent.id == "dev-agent":
        return (
            "Sos el Dev Agent de KAOS. Respondé como un compañero técnico útil, "
            "con foco en diagnóstico, cambios y próximos pasos."
        )
    return f"Sos {agent.label} de KAOS. {agent.description}"


def _session_id_from(event: Event | Artifact) -> str | None:
    raw = (
        event.payload.get("session_id")
        if isinstance(event, Event)
        else event.metadata.get("session_id")
    )
    if raw is None and isinstance(event, Artifact):
        raw = event.content.get("session_id")
    return str(raw) if raw else None


def _session_meta(event: Event | Artifact) -> dict[str, object]:
    payload = event.payload if isinstance(event, Event) else event.metadata
    content = event.content if isinstance(event, Artifact) else {}
    data: dict[str, object] = {}
    for key in ("user_id", "agent_id", "project", "kind", "title", "model", "session_id"):
        value = payload.get(key) if key in payload else content.get(key)
        if value not in (None, ""):
            data[key] = value
    return data


def _history(events: Sequence[Event]) -> str:
    lines: list[str] = []
    for event in sorted(events, key=lambda e: e.timestamp):
        if event.type == SESSION_CREATED:
            continue
        role = "usuario" if event.type == USER_MESSAGE else "asistente"
        text = str(event.payload.get("message") or event.payload.get("response") or "")
        stamp = event.timestamp.isoformat(timespec="seconds")
        lines.append(f"[{stamp}] {role}: {text}")
    return "\n".join(lines)


def _session_title(kind: str, project: str | None, user_id: str) -> str:
    if project:
        return f"{kind} · {project} · {user_id}"
    return f"{kind} · {user_id}"


async def _run_tool_agent(
    llm: object,
    agent_id: str,
    *,
    workspace: str,
    message: str,
    prior: str,
    reference_block: str,
) -> tuple[str, Artifact | None]:
    """Run a tool-using agent's loop; return ``(answer, session_artifact)``.

    The chat message (plus any prior thread and reference material) becomes the
    task, so an agent like the Dev Agent actually uses its tools instead of a
    single completion. The produced artifact (e.g. ``dev.session``) carries the
    traceable tool steps.
    """
    parts: list[str] = []
    if reference_block:
        parts.append(reference_block)
    if prior:
        parts.append("Conversación previa:\n" + prior)
    parts.append(f"Pedido actual del usuario: {message}")
    task = "\n\n".join(parts)

    if agent_id == "dev-agent":
        agent = DevAgent(llm, default_dev_tools(Path.cwd()))  # type: ignore[arg-type]
    else:  # pragma: no cover - guarded by TOOL_USING_AGENTS
        return ("(sin respuesta)", None)

    produced = await agent.run(Context(workspace=workspace, params={"task": task}))
    if not produced:
        return ("(sin respuesta)", None)
    art = produced[0]
    answer = redact_secrets(str(art.content.get("answer") or "")).strip()
    return (answer or "(sin respuesta)", art)


async def send_message(
    storage: Storage,
    settings: Settings,
    *,
    workspace: str,
    user_id: str,
    agent_id: str,
    message: str,
    project: str | None = None,
    kind: str = "conversation",
    session_id: str | None = None,
    title: str | None = None,
    about_artifact: str | None = None,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict[str, object]:
    """Persist a chat turn and generate an assistant response.

    ``llm_provider``/``llm_model`` are an optional per-message override that wins
    over the global default (transient — not stored on the session).
    """
    if not workspace.strip():
        raise ValueError("workspace is required")
    if not user_id.strip():
        raise ValueError("user_id is required")
    if not agent_id.strip():
        raise ValueError("agent_id is required")
    if not message.strip():
        raise ValueError("message is required")

    resolved = await load_settings(settings, provider=llm_provider, model=llm_model)
    llm = EchoLLMProvider() if resolved.llm_provider == "echo" else build_llm(resolved)
    session_id = session_id or uuid4().hex
    created_at = utcnow()

    events = list(await storage.list_events(workspace))
    artifacts = list(await storage.list_artifacts(workspace))

    # Optional: anchor this turn to an existing artifact so the agent answers
    # grounded on it and the contribution is traceable back to that knowledge.
    reference_block = ""
    about_id: str | None = None
    if about_artifact:
        about = next((a for a in artifacts if str(a.id) == about_artifact), None)
        if about is not None:
            about_id = str(about.id)
            ref = str(about.content.get("summary") or "")
            if not ref:
                ref = json.dumps(about.content, ensure_ascii=False)[:2000]
            reference_block = f"Material de referencia (artifact {about.kind}):\n{ref}"
            if not project:
                project = str(about.metadata.get("project") or "") or None

    session_events = [e for e in events if _session_id_from(e) == session_id]
    session_artifacts = [a for a in artifacts if _session_id_from(a) == session_id]
    first_turn = not session_events and not session_artifacts
    created_event: Event | None = None

    if first_turn:
        created_event = Event(
            type=SESSION_CREATED,
            source="chat",
            workspace=workspace,
            payload={
                "session_id": session_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "project": project,
                "kind": kind,
                "title": title or _session_title(kind, project, user_id),
            },
        )
        await storage.save_event(created_event)

    user_event = Event(
        type=USER_MESSAGE,
        source="chat",
        workspace=workspace,
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "project": project,
            "kind": kind,
            "title": title or _session_title(kind, project, user_id),
            "message": message.strip(),
        },
    )
    await storage.save_event(user_event)

    current_events = list(session_events)
    if created_event is not None:
        current_events.insert(0, created_event)
    current_events.append(user_event)

    dev_session: Artifact | None = None
    if agent_id in TOOL_USING_AGENTS:
        assistant_text, dev_session = await _run_tool_agent(
            llm,
            agent_id,
            workspace=workspace,
            message=message.strip(),
            prior=_history(session_events),
            reference_block=reference_block,
        )
    else:
        system_prompt = _agent_prompt(agent_id)
        transcript = _history(current_events) or f"usuario: {message.strip()}"
        if reference_block:
            transcript = f"{reference_block}\n\n{transcript}"
        assistant_raw = await llm.complete(
            [
                Message(role="system", content=system_prompt),
                Message(role="user", content=transcript),
            ]
        )
        assistant_text = redact_secrets(assistant_raw).strip() or "(sin respuesta)"

    assistant_event = Event(
        type=ASSISTANT_MESSAGE,
        source="chat",
        workspace=workspace,
        payload={
            "session_id": session_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "project": project,
            "kind": kind,
            "title": title or _session_title(kind, project, user_id),
            "model": resolved.llm_model,
            "response": assistant_text,
            "about_artifact": about_id,
        },
    )
    await storage.save_event(assistant_event)

    turn_meta = {
        "session_id": session_id,
        "user_id": user_id,
        "agent_id": agent_id,
        "project": project or "",
        "kind": kind,
        "title": title or _session_title(kind, project, user_id),
        "model": resolved.llm_model,
        "about_artifact": about_id or "",
    }
    if dev_session is not None:
        # Persist the traceable dev.session as this turn's artifact (tool steps
        # included) instead of a plain chat.turn.
        artifact = Artifact(
            kind=dev_session.kind,
            workspace=workspace,
            produced_by=dev_session.produced_by,
            content={**dict(dev_session.content), "session_id": session_id},
            source_events=tuple(e.id for e in current_events + [assistant_event]),
            metadata={**dict(dev_session.metadata), **turn_meta},
        )
    else:
        artifact = Artifact(
            kind=TURN_ARTIFACT,
            workspace=workspace,
            produced_by="chat-agent",
            content={
                "summary": assistant_text,
                "format": "markdown",
                "session_id": session_id,
                "user_message": message.strip(),
                "assistant_message": assistant_text,
                "message_count": len([e for e in current_events if e.type == USER_MESSAGE]),
            },
            source_events=tuple(e.id for e in current_events + [assistant_event]),
            metadata=turn_meta,
        )
    await storage.save_artifact(artifact)

    return {
        "session": {
            "session_id": session_id,
            "workspace": workspace,
            "user_id": user_id,
            "agent_id": agent_id,
            "project": project,
            "kind": kind,
            "title": title or _session_title(kind, project, user_id),
            "message_count": len([e for e in current_events if e.type == USER_MESSAGE]),
            "model": resolved.llm_model,
            "created_at": created_at.isoformat(timespec="seconds"),
            "updated_at": assistant_event.timestamp.isoformat(timespec="seconds"),
        },
        "response": assistant_text,
        "artifacts": [artifact],
        "about_artifact": about_id,
    }


async def list_sessions(storage: Storage, workspace: str) -> list[dict[str, object]]:
    """Return chat sessions derived from stored events and artifacts."""
    events = list(await storage.list_events(workspace))
    artifacts = list(await storage.list_artifacts(workspace))
    by_session: dict[str, dict[str, object]] = defaultdict(dict)

    combined: list[Event | Artifact] = [*events, *artifacts]
    for item in combined:
        session_id = _session_id_from(item)
        if not session_id:
            continue
        entry = by_session[session_id]
        meta = _session_meta(item)
        entry.setdefault("session_id", session_id)
        entry.setdefault("workspace", workspace)
        for key in ("user_id", "agent_id", "project", "kind", "title", "model"):
            value = meta.get(key)
            if value not in (None, ""):
                entry[key] = value
        stamp = item.timestamp.isoformat(timespec="seconds")
        entry["created_at"] = min(str(entry.get("created_at") or stamp), stamp)
        entry["updated_at"] = max(str(entry.get("updated_at") or stamp), stamp)

    for session_id, entry in by_session.items():
        session_events = [e for e in events if _session_id_from(e) == session_id]
        session_artifacts = [a for a in artifacts if _session_id_from(a) == session_id]
        entry["message_count"] = len([e for e in session_events if e.type == USER_MESSAGE])
        entry["turn_count"] = len(
            [e for e in session_events if e.type in {USER_MESSAGE, ASSISTANT_MESSAGE}]
        )
        entry["last_message"] = next(
            (
                str(e.payload.get("response") or e.payload.get("message") or "")
                for e in sorted(session_events, key=lambda e: e.timestamp, reverse=True)
                if e.type in {USER_MESSAGE, ASSISTANT_MESSAGE}
            ),
            "",
        )
        entry["artifacts"] = len(session_artifacts)
    sessions = sorted(by_session.values(), key=lambda s: str(s.get("updated_at", "")), reverse=True)
    return sessions


async def session_thread(
    storage: Storage, workspace: str, session_id: str
) -> list[dict[str, object]]:
    """Return the ordered user/assistant messages of one chat session."""
    events = [
        e
        for e in await storage.list_events(workspace)
        if _session_id_from(e) == session_id
    ]
    messages: list[dict[str, object]] = []
    for event in sorted(events, key=lambda e: e.timestamp):
        stamp = event.timestamp.isoformat(timespec="seconds")
        if event.type == USER_MESSAGE:
            messages.append(
                {
                    "role": "user",
                    "text": str(event.payload.get("message") or ""),
                    "timestamp": stamp,
                }
            )
        elif event.type == ASSISTANT_MESSAGE:
            messages.append(
                {
                    "role": "assistant",
                    "text": str(event.payload.get("response") or ""),
                    "timestamp": stamp,
                    "model": event.payload.get("model"),
                }
            )
    return messages


def artifact_friendly_title(artifact: Artifact) -> str:
    """A human-friendly label for an artifact in the knowledge list.

    Prefers an explicit title, then the originating thread name, then the last
    message's title, falling back to a readable form of the kind.
    """
    meta = artifact.metadata
    content = artifact.content
    messages = content.get("messages")
    last_title = ""
    if isinstance(messages, list) and messages:
        last = messages[-1]
        if isinstance(last, dict):
            last_title = str(last.get("title") or last.get("author") or "")
    candidate = (
        str(meta.get("title") or "")
        or str(meta.get("thread_name") or "")
        or str(content.get("title") or "")
        or last_title
    )
    if candidate:
        return candidate
    if artifact.kind == "project.status":
        return "📊 Estado del Proyecto"
    if artifact.kind == "conversation.summary":
        return "Resumen de conversación"
    return artifact.kind


def artifact_last_activity(artifact: Artifact) -> str:
    """ISO timestamp of the artifact's last originating message, else its own."""
    messages = artifact.content.get("messages")
    if isinstance(messages, list):
        stamps = [
            str(m.get("timestamp"))
            for m in messages
            if isinstance(m, dict) and m.get("timestamp")
        ]
        if stamps:
            return max(stamps)
    return artifact.timestamp.isoformat(timespec="seconds")


async def artifact_thread(
    storage: Storage,
    workspace: str,
    artifact_id: str,
    *,
    offset: int = 0,
    limit: int = 40,
) -> dict[str, object]:
    """Return the originating message thread of an artifact, paginated backwards.

    Resolution order, so any connector path works: the transcript embedded in the
    artifact (``content['messages']``), then the ``source_events`` still in
    storage, then any ``message.*`` event of the workspace as a last resort.

    ``offset`` counts messages already loaded from the newest end; the window
    returned is the ``limit`` messages immediately older than that, enabling an
    infinite scroll towards the past. ``has_more`` signals older messages remain.
    """
    artifacts = list(await storage.list_artifacts(workspace))
    artifact = next((a for a in artifacts if str(a.id) == artifact_id), None)
    if artifact is None:
        return {"messages": [], "has_more": False, "next_offset": offset, "summary": None}

    ordered = await _resolve_thread_messages(storage, workspace, artifact)

    total = len(ordered)
    end = max(0, total - offset)
    start = max(0, end - limit)
    window = ordered[start:end]
    summary = artifact.content.get("summary") if offset == 0 else None
    return {
        "messages": window,
        "has_more": start > 0,
        "next_offset": offset + len(window),
        "total": total,
        "summary": summary,
        "title": artifact_friendly_title(artifact),
        "kind": artifact.kind,
    }


async def _resolve_thread_messages(
    storage: Storage, workspace: str, artifact: Artifact
) -> list[dict[str, object]]:
    """Best-effort recovery of the ordered messages behind an artifact."""
    embedded = artifact.content.get("messages")
    if isinstance(embedded, list) and embedded:
        return [_thread_row(m) for m in embedded if isinstance(m, dict)]

    events = list(await storage.list_events(workspace))
    source_ids = {str(sid) for sid in artifact.source_events}
    picked = [e for e in events if str(e.id) in source_ids]
    if not picked:
        channel = str(artifact.metadata.get("channel_id") or "")
        picked = [
            e
            for e in events
            if e.type.startswith("message.")
            and (not channel or str(e.payload.get("channel_id") or "") == channel)
        ]
    picked.sort(key=lambda e: e.timestamp)
    return [
        _thread_row(
            {
                "author": e.payload.get("author"),
                "text": e.payload.get("text"),
                "timestamp": e.payload.get("timestamp")
                or e.timestamp.isoformat(timespec="seconds"),
            }
        )
        for e in picked
    ]


def _thread_row(message: dict[str, object]) -> dict[str, object]:
    return {
        "role": "message",
        "author": str(message.get("author") or "unknown"),
        "text": str(message.get("text") or ""),
        "timestamp": str(message.get("timestamp") or ""),
    }



async def load_contributions(storage: Storage, workspace: str) -> list[Event]:
    """Return stored chat user messages as synthetic ``message.contribution`` events.

    These let the Resume pipeline weigh human *aportes* made from the chat (any
    user message in the workspace) when it re-summarizes, without the agent
    needing to know about chat internals: :class:`ResumeAgent` already renders
    any ``message.*`` event from its ``author``/``text``/``timestamp`` payload.
    Each synthetic event carries the stable originating chat event id in
    ``contribution_id`` so caches can fold it into their fingerprint.
    """
    events = await storage.list_events(workspace)
    contributions: list[Event] = []
    for event in sorted(events, key=lambda e: e.timestamp):
        if event.type != USER_MESSAGE:
            continue
        text = str(event.payload.get("message") or "").strip()
        if not text:
            continue
        author = str(event.payload.get("user_id") or "chat")
        contributions.append(
            Event(
                type=CONTRIBUTION_EVENT,
                source="chat",
                workspace=workspace,
                payload={
                    "author": f"aporte:{author}",
                    "text": text,
                    "timestamp": event.timestamp.isoformat(timespec="seconds"),
                    "contribution_id": str(event.id),
                },
            )
        )
    return contributions


def contribution_ids(contributions: Sequence[Event]) -> list[str]:
    """Stable ids of the chat events behind ``contributions`` (for cache keys)."""
    return [str(c.payload.get("contribution_id") or c.id) for c in contributions]

