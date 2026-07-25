"""Tests for the forum backfill consolidation logic."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from uuid import uuid4

from kaos.cli.backfill import _build_consolidated_report, _should_publish
from kaos.contracts.artifact import Artifact
from kaos.contracts.llm import Message
from kaos.plugins.agents import ResumeAgent


class _FusingLLM:
    """A fake LLM that returns a single unified report for the reduce call."""

    name = "fusing-llm"

    def __init__(self, unified: str) -> None:
        self._unified = unified
        self.calls: list[list[Message]] = []

    async def complete(self, messages: Sequence[Message], **_: object) -> str:
        self.calls.append(list(messages))
        return self._unified


def test_should_publish_rule() -> None:
    # Idempotent mode: publish only when something changed.
    assert _should_publish(0, only_if_changed=True) is False
    assert _should_publish(1, only_if_changed=True) is True
    # Default mode: always publish, regardless of changes.
    assert _should_publish(0, only_if_changed=False) is True
    assert _should_publish(3, only_if_changed=False) is True


def _thread_summary(name: str, body: str, n_events: int, n_msgs: int) -> Artifact:
    return Artifact(
        kind="conversation.summary",
        workspace="discord:FORUM",
        produced_by="resume-agent",
        content={"summary": body, "format": "markdown", "message_count": n_msgs},
        source_events=tuple(uuid4() for _ in range(n_events)),
    )


def test_build_consolidated_report_fuses_threads_via_llm() -> None:
    a = _thread_summary("Implementación", "# Resumen\n## Estado\n- a", 3, 50)
    b = _thread_summary("PMO", "# Resumen\n## Estado\n- b", 2, 33)
    summaries = [("t1", "Implementación", a), ("t2", "PMO", b)]
    unified = "# Resumen Ejecutivo\n## Estado\n- todo integrado en un solo flujo"
    llm = _FusingLLM(unified)
    agent = ResumeAgent(llm)

    report = asyncio.run(
        _build_consolidated_report("FORUM", "discord:FORUM", summaries, agent)
    )

    # A single, consolidated knowledge artifact synthesized by the agent.
    assert report.kind == "project.status"
    assert report.workspace == "discord:FORUM"
    assert report.content["thread_count"] == 2
    # Aggregated message count and full traceability across all threads.
    assert report.content["message_count"] == 83
    assert len(report.source_events) == 5
    assert set(report.source_events) == set(a.source_events) | set(b.source_events)
    # ONE unified report body (the LLM synthesis), not N stacked per-thread ones.
    summary = report.content["summary"]
    assert "# 📊 Estado del Proyecto" in summary
    assert unified in summary
    assert "## 🧵 Implementación" not in summary  # not stacked by thread
    assert report.metadata["forum_channel_id"] == "FORUM"
    # The agent ran a reduce over the per-thread summaries (a single LLM call).
    assert len(llm.calls) == 1


def test_consolidated_report_attributes_to_designated_agent() -> None:
    """A designated agent (task-agent) consolidates and is credited as author."""
    a = _thread_summary("Backend", "# Resumen\n- API", 3, 50)
    b = _thread_summary("Frontend", "# Resumen\n- vistas", 2, 33)
    summaries = [("t1", "Backend", a), ("t2", "Frontend", b)]
    llm = _FusingLLM("informe unificado por task-agent")
    agent = ResumeAgent(llm)

    report = asyncio.run(
        _build_consolidated_report(
            "FORUM", "discord:FORUM", summaries, agent, agent_id="task-agent", llm=llm
        )
    )

    # Attributed to the designated agent, not always resume-agent.
    assert report.produced_by == "task-agent"
    assert report.metadata["agent_id"] == "task-agent"
    assert report.kind == "project.status"
    assert "informe unificado por task-agent" in report.content["summary"]
    # Traceability across threads preserved regardless of the agent used.
    assert report.content["message_count"] == 83
    assert len(report.source_events) == 5


def test_build_consolidated_report_falls_back_to_concat_when_empty() -> None:
    a = _thread_summary("Implementación", "# Resumen\n## Estado\n- a", 3, 50)
    b = _thread_summary("PMO", "# Resumen\n## Estado\n- b", 2, 33)
    summaries = [("t1", "Implementación", a), ("t2", "PMO", b)]
    agent = ResumeAgent(_FusingLLM("   "))  # LLM returns blank -> fallback

    report = asyncio.run(
        _build_consolidated_report("FORUM", "discord:FORUM", summaries, agent)
    )

    summary = report.content["summary"]
    # Fallback keeps a labeled concatenation so a report still ships.
    assert "# 📊 Estado del Proyecto" in summary
    assert "## 🧵 Implementación" in summary
    assert "## 🧵 PMO" in summary
    assert summary.index("Implementación") < summary.index("PMO")

