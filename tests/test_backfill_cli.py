"""Tests for the forum backfill consolidation logic."""

from __future__ import annotations

from uuid import uuid4

from kaos.cli.backfill import _build_consolidated_report, _should_publish
from kaos.contracts.artifact import Artifact


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


def test_build_consolidated_report_merges_threads() -> None:
    a = _thread_summary("Implementación", "# Resumen\n## Estado\n- a", 3, 50)
    b = _thread_summary("PMO", "# Resumen\n## Estado\n- b", 2, 33)
    summaries = [("t1", "Implementación", a), ("t2", "PMO", b)]

    report = _build_consolidated_report("FORUM", "discord:FORUM", summaries)

    # A single, consolidated knowledge artifact.
    assert report.kind == "project.status"
    assert report.workspace == "discord:FORUM"
    assert report.content["thread_count"] == 2
    # Aggregated message count and full traceability across all threads.
    assert report.content["message_count"] == 83
    assert len(report.source_events) == 5
    assert set(report.source_events) == set(a.source_events) | set(b.source_events)
    # One report body with a header and every thread labeled.
    summary = report.content["summary"]
    assert "# 📊 Estado del Proyecto" in summary
    assert "Consolidado de 2 hilos" in summary
    assert "# 🧵 Implementación" in summary
    assert "# 🧵 PMO" in summary
    assert summary.index("Implementación") < summary.index("PMO")
    assert report.metadata["forum_channel_id"] == "FORUM"

