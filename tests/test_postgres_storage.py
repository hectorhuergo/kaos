"""Integration tests for PostgresStorage.

Skipped unless ``KAOS_TEST_DATABASE_URL`` is set and asyncpg is installed.
Run against the docker-compose postgres container, e.g.:

    docker compose -f docker/docker-compose.yml up -d postgres
    $env:KAOS_TEST_DATABASE_URL = "postgresql://kaos:kaos@localhost:5432/kaos"
    pytest tests/test_postgres_storage.py
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from kaos.contracts import Artifact, Event

DSN = os.environ.get("KAOS_TEST_DATABASE_URL")

asyncpg = pytest.importorskip("asyncpg")
pytestmark = pytest.mark.skipif(not DSN, reason="KAOS_TEST_DATABASE_URL not set")


def test_postgres_roundtrip() -> None:
    from kaos.plugins.storage import PostgresStorage

    workspace = f"test:{uuid4()}"
    storage = PostgresStorage(DSN)  # type: ignore[arg-type]

    event = Event(
        type="message.created",
        source="pytest",
        workspace=workspace,
        payload={"author": "ana", "text": "hola"},
    )
    artifact = Artifact(
        kind="conversation.summary",
        workspace=workspace,
        produced_by="resume-agent",
        content={"summary": "# Resumen"},
        source_events=(event.id,),
        metadata={"channel_id": "100"},
    )

    async def scenario() -> None:
        await storage.save_event(event)
        await storage.save_event(event)  # idempotent (immutable evidence)
        await storage.save_artifact(artifact)

        events = await storage.list_events(workspace)
        artifacts = await storage.list_artifacts(workspace)
        fetched = await storage.get_artifact(artifact.id)
        await storage.close()

        assert len(events) == 1
        assert events[0].payload == {"author": "ana", "text": "hola"}
        assert len(artifacts) == 1
        assert fetched is not None
        assert fetched.content == {"summary": "# Resumen"}
        assert fetched.source_events == (event.id,)
        assert fetched.metadata == {"channel_id": "100"}

    asyncio.run(scenario())

