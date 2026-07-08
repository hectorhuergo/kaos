"""Tests for the `kaos up` demo pipeline."""

from __future__ import annotations

import asyncio
import io

from kaos.contracts import Artifact
from kaos.plugins.publishers import ConsolePublisher
from kaos.runtime.demo import SAMPLE_SUMMARY, build_demo_runtime, run_demo


class _CollectingPublisher:
    name = "collecting-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)


def test_build_demo_runtime_processes_conversation() -> None:
    publisher = _CollectingPublisher()
    runtime = build_demo_runtime(publisher=publisher)

    asyncio.run(runtime.start())

    assert len(publisher.published) == 1
    artifact = publisher.published[0]
    assert artifact.kind == "conversation.summary"
    assert artifact.workspace == "discord:42"
    assert artifact.content["summary"] == SAMPLE_SUMMARY
    assert artifact.content["message_count"] == 3
    # Traceability: three source messages.
    assert len(artifact.source_events) == 3


def test_console_publisher_writes_summary() -> None:
    buffer = io.StringIO()
    publisher = ConsolePublisher(stream=buffer)
    runtime = build_demo_runtime(publisher=publisher)

    asyncio.run(runtime.start())

    output = buffer.getvalue()
    assert "conversation.summary" in output
    assert "# Resumen Ejecutivo" in output


def test_run_demo_smoke() -> None:
    # Should run end to end without raising.
    asyncio.run(run_demo())

