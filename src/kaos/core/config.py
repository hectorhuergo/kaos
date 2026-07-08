"""KAOS configuration loaded from the environment.

Pure data (no plugin imports) so the Core stays agnostic. The composition root
(`kaos.bootstrap.factory`) turns these settings into concrete plugins.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, field_validator

LLM_PROVIDERS = ("echo", "openai", "github", "anthropic")


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> None:
    """Load ``KEY=VALUE`` pairs from a ``.env`` file into ``os.environ``.

    Dependency-free. Existing environment variables are kept unless
    ``override`` is set. Lines starting with ``#`` and blank lines are ignored;
    surrounding quotes are stripped.
    """
    file = Path(path)
    if not file.exists():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


class Settings(BaseModel):
    """Runtime configuration for a KAOS instance."""

    # LLM
    llm_provider: str = "echo"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_timeout: float = 120.0
    github_token: str | None = None
    anthropic_api_key: str | None = None

    # GitHub connector (summarize a repository's recent activity)
    github_repo: str | None = None

    # Discord
    discord_token: str | None = None
    discord_guild_id: str | None = None
    discord_channel_ids: tuple[str, ...] = ()
    discord_webhook_url: str | None = None
    discord_resume_thread_id: str | None = None
    resume_thread_name: str = "📋 Resume"

    # Discord backfill (read a thread/channel history via REST)
    discord_backfill_channel_id: str | None = None
    discord_message_limit: int = 100

    # Persistence
    database_url: str | None = None

    # Scheduler (Beta): seconds between recurring `kaos run` passes.
    scheduler_interval: float = 900.0

    @field_validator("llm_provider")
    @classmethod
    def _valid_provider(cls, value: str) -> str:
        if value not in LLM_PROVIDERS:
            raise ValueError(f"llm_provider must be one of {LLM_PROVIDERS}, got '{value}'")
        return value

    @property
    def discord_enabled(self) -> bool:
        """Whether a real Discord integration is configured."""
        return bool(self.discord_token)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """Build settings from environment variables (``KAOS_*``).

        Reads ``os.environ`` by default. Loading a ``.env`` file is the job of
        the CLI entrypoint (`kaos.cli.main`), so this stays pure and testable.
        """
        env = environ if environ is not None else os.environ

        def get(key: str) -> str | None:
            value = env.get(key)
            return value if value else None

        channels_raw = get("KAOS_DISCORD_CHANNEL_IDS") or ""
        channels = tuple(c.strip() for c in channels_raw.split(",") if c.strip())

        limit_raw = get("KAOS_DISCORD_MESSAGE_LIMIT")
        message_limit = int(limit_raw) if limit_raw and limit_raw.isdigit() else 100

        timeout_raw = get("KAOS_LLM_TIMEOUT")
        try:
            llm_timeout = float(timeout_raw) if timeout_raw else 120.0
        except ValueError:
            llm_timeout = 120.0

        interval_raw = get("KAOS_SCHEDULER_INTERVAL")
        try:
            scheduler_interval = float(interval_raw) if interval_raw else 900.0
        except ValueError:
            scheduler_interval = 900.0

        return cls(
            llm_provider=get("KAOS_LLM_PROVIDER") or "echo",
            llm_model=get("KAOS_LLM_MODEL") or "gpt-4o-mini",
            llm_api_key=get("KAOS_LLM_API_KEY"),
            llm_base_url=get("KAOS_LLM_BASE_URL"),
            llm_timeout=llm_timeout,
            github_token=get("KAOS_GITHUB_TOKEN") or get("GITHUB_TOKEN"),
            anthropic_api_key=get("KAOS_ANTHROPIC_API_KEY") or get("ANTHROPIC_API_KEY"),
            github_repo=get("KAOS_GITHUB_REPO"),
            discord_token=get("KAOS_DISCORD_TOKEN"),
            discord_guild_id=get("KAOS_DISCORD_GUILD_ID"),
            discord_channel_ids=channels,
            discord_webhook_url=get("KAOS_DISCORD_WEBHOOK_URL"),
            discord_resume_thread_id=get("KAOS_DISCORD_RESUME_THREAD_ID"),
            resume_thread_name=get("KAOS_RESUME_THREAD_NAME") or "📋 Resume",
            discord_backfill_channel_id=get("KAOS_DISCORD_BACKFILL_CHANNEL_ID"),
            discord_message_limit=message_limit,
            database_url=get("KAOS_DATABASE_URL"),
            scheduler_interval=scheduler_interval,
        )

