"""PostgreSQL implementation of the Storage contract (asyncpg).

Events and artifacts are stored immutably (``ON CONFLICT DO NOTHING``),
supporting *Immutable Evidence*. ``asyncpg`` is imported lazily so the module
can be imported without the dependency; install it with the optional extra:
``pip install -e .[postgres]``.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from kaos.contracts.artifact import Artifact
from kaos.contracts.event import Event
from kaos.domain.provider_credential import ProviderCredential
from kaos.domain.runtime_config import SINGLETON, RuntimeConfig
from kaos.domain.subscription import Subscription

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kaos_events (
    id uuid PRIMARY KEY,
    type text NOT NULL,
    source text NOT NULL,
    workspace text NOT NULL,
    timestamp timestamptz NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    correlation_id uuid
);
CREATE INDEX IF NOT EXISTS ix_kaos_events_workspace ON kaos_events (workspace);

CREATE TABLE IF NOT EXISTS kaos_artifacts (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    workspace text NOT NULL,
    produced_by text NOT NULL,
    content jsonb NOT NULL DEFAULT '{}',
    source_events uuid[] NOT NULL DEFAULT '{}',
    timestamp timestamptz NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_kaos_artifacts_workspace ON kaos_artifacts (workspace);
"""

_SUBSCRIPTIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS kaos_subscriptions (
    id uuid PRIMARY KEY,
    workspace text NOT NULL,
    kind text NOT NULL,
    channel_id text NOT NULL UNIQUE,
    guild_id text,
    resume_thread_id text,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_kaos_subscriptions_active ON kaos_subscriptions (active);
"""

_RUNTIME_CONFIG_SCHEMA = """
CREATE TABLE IF NOT EXISTS kaos_runtime_config (
    name text PRIMARY KEY,
    llm_provider text NOT NULL,
    llm_model text NOT NULL,
    updated_at timestamptz NOT NULL
);
"""

_CREDENTIALS_SCHEMA = """
CREATE TABLE IF NOT EXISTS kaos_provider_credentials (
    provider text PRIMARY KEY,
    api_key text NOT NULL DEFAULT '',
    model text NOT NULL DEFAULT '',
    base_url text NOT NULL DEFAULT '',
    updated_at timestamptz NOT NULL
);
"""


class PostgresStorage:
    """Durable Storage backed by PostgreSQL via asyncpg."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _init_connection(self, conn: Any) -> None:
        # Encode/decode jsonb columns transparently as Python dicts.
        await conn.set_type_codec(
            "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # lazy import: only needed for PostgreSQL

            self._pool = await asyncpg.create_pool(self._dsn, init=self._init_connection)
            async with self._pool.acquire() as conn:
                await conn.execute(_SCHEMA)
        return self._pool

    async def save_event(self, event: Event) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            INSERT INTO kaos_events
                (id, type, source, workspace, timestamp, payload, correlation_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (id) DO NOTHING
            """,
            event.id,
            event.type,
            event.source,
            event.workspace,
            event.timestamp,
            event.payload,
            event.correlation_id,
        )

    async def save_artifact(self, artifact: Artifact) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            INSERT INTO kaos_artifacts
                (id, kind, workspace, produced_by, content, source_events, timestamp, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO NOTHING
            """,
            artifact.id,
            artifact.kind,
            artifact.workspace,
            artifact.produced_by,
            artifact.content,
            list(artifact.source_events),
            artifact.timestamp,
            artifact.metadata,
        )

    async def get_artifact(self, artifact_id: UUID) -> Artifact | None:
        pool = await self._ensure_pool()
        row = await pool.fetchrow("SELECT * FROM kaos_artifacts WHERE id = $1", artifact_id)
        return self._to_artifact(row) if row is not None else None

    async def list_events(self, workspace: str) -> list[Event]:
        pool = await self._ensure_pool()
        rows = await pool.fetch(
            "SELECT * FROM kaos_events WHERE workspace = $1 ORDER BY timestamp", workspace
        )
        return [self._to_event(row) for row in rows]

    async def list_artifacts(self, workspace: str) -> list[Artifact]:
        pool = await self._ensure_pool()
        rows = await pool.fetch(
            "SELECT * FROM kaos_artifacts WHERE workspace = $1 ORDER BY timestamp", workspace
        )
        return [self._to_artifact(row) for row in rows]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _to_event(row: Any) -> Event:
        return Event(
            id=row["id"],
            type=row["type"],
            source=row["source"],
            workspace=row["workspace"],
            timestamp=row["timestamp"],
            payload=row["payload"],
            correlation_id=row["correlation_id"],
        )

    @staticmethod
    def _to_artifact(row: Any) -> Artifact:
        return Artifact(
            id=row["id"],
            kind=row["kind"],
            workspace=row["workspace"],
            produced_by=row["produced_by"],
            content=row["content"],
            source_events=tuple(row["source_events"]),
            timestamp=row["timestamp"],
            metadata=row["metadata"],
        )


class PostgresSubscriptionStore:
    """Durable SubscriptionStore backed by PostgreSQL via asyncpg."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # lazy import: only needed for PostgreSQL

            self._pool = await asyncpg.create_pool(self._dsn)
            async with self._pool.acquire() as conn:
                await conn.execute(_SUBSCRIPTIONS_SCHEMA)
        return self._pool

    async def add(self, subscription: Subscription) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            INSERT INTO kaos_subscriptions
                (id, workspace, kind, channel_id, guild_id, resume_thread_id,
                 active, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (channel_id) DO UPDATE SET
                workspace = EXCLUDED.workspace,
                kind = EXCLUDED.kind,
                guild_id = EXCLUDED.guild_id,
                resume_thread_id = EXCLUDED.resume_thread_id,
                active = EXCLUDED.active
            """,
            subscription.id,
            subscription.workspace,
            subscription.kind,
            subscription.channel_id,
            subscription.guild_id,
            subscription.resume_thread_id,
            subscription.active,
            subscription.created_at,
        )

    async def get(self, channel_id: str) -> Subscription | None:
        pool = await self._ensure_pool()
        row = await pool.fetchrow(
            "SELECT * FROM kaos_subscriptions WHERE channel_id = $1", channel_id
        )
        return self._to_subscription(row) if row is not None else None

    async def list(self, *, active_only: bool = True) -> list[Subscription]:
        pool = await self._ensure_pool()
        query = "SELECT * FROM kaos_subscriptions"
        if active_only:
            query += " WHERE active = true"
        query += " ORDER BY created_at"
        rows = await pool.fetch(query)
        return [self._to_subscription(row) for row in rows]

    async def deactivate(self, channel_id: str) -> bool:
        pool = await self._ensure_pool()
        result = await pool.execute(
            "UPDATE kaos_subscriptions SET active = false WHERE channel_id = $1",
            channel_id,
        )
        # asyncpg returns a status like "UPDATE 1".
        return bool(result.rsplit(" ", 1)[-1] != "0")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _to_subscription(row: Any) -> Subscription:
        return Subscription(
            id=row["id"],
            workspace=row["workspace"],
            kind=row["kind"],
            channel_id=row["channel_id"],
            guild_id=row["guild_id"],
            resume_thread_id=row["resume_thread_id"],
            active=row["active"],
            created_at=row["created_at"],
        )


class PostgresConfigStore:
    """Durable ConfigStore backed by PostgreSQL via asyncpg.

    Persists the single active :class:`RuntimeConfig` as one upserted row.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # lazy import: only needed for PostgreSQL

            self._pool = await asyncpg.create_pool(self._dsn)
            async with self._pool.acquire() as conn:
                await conn.execute(_RUNTIME_CONFIG_SCHEMA)
        return self._pool

    async def get(self) -> RuntimeConfig | None:
        pool = await self._ensure_pool()
        row = await pool.fetchrow(
            "SELECT * FROM kaos_runtime_config WHERE name = $1", SINGLETON
        )
        if row is None:
            return None
        return RuntimeConfig(
            llm_provider=row["llm_provider"],
            llm_model=row["llm_model"],
            updated_at=row["updated_at"],
        )

    async def set(self, config: RuntimeConfig) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            INSERT INTO kaos_runtime_config
                (name, llm_provider, llm_model, updated_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (name) DO UPDATE SET
                llm_provider = EXCLUDED.llm_provider,
                llm_model = EXCLUDED.llm_model,
                updated_at = EXCLUDED.updated_at
            """,
            SINGLETON,
            config.llm_provider,
            config.llm_model,
            config.updated_at,
        )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


class PostgresCredentialStore:
    """Durable CredentialStore backed by PostgreSQL via asyncpg.

    Persists one :class:`ProviderCredential` per provider (upserted by id). The
    secret is stored as-is; keep DB access restricted. The API layer never
    returns it — only whether a credential exists.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any = None

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            import asyncpg  # lazy import: only needed for PostgreSQL

            self._pool = await asyncpg.create_pool(self._dsn)
            async with self._pool.acquire() as conn:
                await conn.execute(_CREDENTIALS_SCHEMA)
        return self._pool

    async def get(self, provider: str) -> ProviderCredential | None:
        pool = await self._ensure_pool()
        row = await pool.fetchrow(
            "SELECT * FROM kaos_provider_credentials WHERE provider = $1", provider
        )
        return self._to_credential(row) if row is not None else None

    async def set(self, credential: ProviderCredential) -> None:
        pool = await self._ensure_pool()
        await pool.execute(
            """
            INSERT INTO kaos_provider_credentials
                (provider, api_key, model, base_url, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (provider) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                model = EXCLUDED.model,
                base_url = EXCLUDED.base_url,
                updated_at = EXCLUDED.updated_at
            """,
            credential.provider,
            credential.api_key,
            credential.model,
            credential.base_url,
            credential.updated_at,
        )

    async def delete(self, provider: str) -> bool:
        pool = await self._ensure_pool()
        result = await pool.execute(
            "DELETE FROM kaos_provider_credentials WHERE provider = $1", provider
        )
        # asyncpg returns a status like "DELETE 1".
        return bool(result.rsplit(" ", 1)[-1] != "0")

    async def list(self) -> list[ProviderCredential]:
        pool = await self._ensure_pool()
        rows = await pool.fetch(
            "SELECT * FROM kaos_provider_credentials ORDER BY provider"
        )
        return [self._to_credential(row) for row in rows]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _to_credential(row: Any) -> ProviderCredential:
        return ProviderCredential(
            provider=row["provider"],
            api_key=row["api_key"],
            model=row["model"],
            base_url=row["base_url"],
            updated_at=row["updated_at"],
        )
