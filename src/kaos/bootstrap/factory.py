"""Composition root: builds a KaosRuntime from Settings.

This is the one place allowed to know about every plugin. It selects the LLM
provider, connector and publisher according to configuration, keeping the Core
and the plugins decoupled from each other.
"""

from __future__ import annotations

from kaos.contracts.config_store import ConfigStore
from kaos.contracts.credential_store import CredentialStore
from kaos.contracts.llm import LLMProvider
from kaos.contracts.publisher import Publisher
from kaos.contracts.storage import Storage
from kaos.contracts.subscription import SubscriptionStore
from kaos.core.config import Settings
from kaos.core.providers import secret_field
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import (
    DiscordBackfillSource,
    DiscordConnector,
    DiscordGatewaySource,
    StaticDiscordSource,
)
from kaos.plugins.providers import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OLLAMA_MODEL,
    OLLAMA_BASE_URL,
    OPENAI_BASE_URL,
    OpenAICompatibleLLMProvider,
)
from kaos.plugins.publishers import (
    ConsolePublisher,
    DiscordPublisher,
    DiscordRestPoster,
    DiscordWebhookPublisher,
)
from kaos.runtime import (
    InMemoryConfigStore,
    InMemoryCredentialStore,
    InMemoryStorage,
    InMemorySubscriptionStore,
    KaosRuntime,
)
from kaos.runtime.demo import SAMPLE_CONVERSATION, SAMPLE_SUMMARY
from kaos.sdk import EchoLLMProvider


def build_storage(settings: Settings) -> Storage:
    """Select the storage backend from configuration."""
    if settings.database_url:
        from kaos.plugins.storage import PostgresStorage

        return PostgresStorage(settings.database_url)
    return InMemoryStorage()


def build_subscription_store(settings: Settings) -> SubscriptionStore:
    """Select the subscription store: PostgreSQL if configured, else in-memory.

    Subscriptions are only useful when durable, so a `DATABASE_URL` is expected
    in real use; in-memory is provided for tests and offline runs.
    """
    if settings.database_url:
        from kaos.plugins.storage import PostgresSubscriptionStore

        return PostgresSubscriptionStore(settings.database_url)
    return InMemorySubscriptionStore()


def build_config_store(settings: Settings) -> ConfigStore:
    """Select the config store: PostgreSQL if configured, else in-memory.

    Holds the persisted runtime selection (LLM provider + model) edited from the
    web console. Like subscriptions, it is only durable with a `DATABASE_URL`.
    """
    if settings.database_url:
        from kaos.plugins.storage import PostgresConfigStore

        return PostgresConfigStore(settings.database_url)
    return InMemoryConfigStore()


def build_credential_store(settings: Settings) -> CredentialStore:
    """Select the credential store: PostgreSQL if configured, else in-memory.

    Holds the per-provider secrets (API keys/tokens) edited from the web console.
    The environment stays as the fallback (see :func:`load_settings`), so a
    provider works with either a persisted credential or its `.env` value.
    """
    if settings.database_url:
        from kaos.plugins.storage import PostgresCredentialStore

        return PostgresCredentialStore(settings.database_url)
    return InMemoryCredentialStore()


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


async def load_settings(base: Settings | None = None) -> Settings:
    """Return ``base`` (or env settings) overlaid with the persisted config.

    Two kinds of durable, non-environment state are overlaid so a change made in
    the web console takes effect on the next run without a redeploy:

    1. The active runtime selection (LLM provider + model) from the
       :class:`ConfigStore`.
    2. The active provider's credential (API key/token + optional model/base_url
       overrides) from the :class:`CredentialStore`.

    The environment is the **fallback**: when nothing is persisted the value from
    ``base`` (i.e. ``.env``) is kept. Without a ``database_url`` this is a no-op.
    """
    base = base if base is not None else Settings.from_env()
    if not base.database_url:
        return base

    updates: dict[str, object] = {}

    config_store = build_config_store(base)
    try:
        config = await config_store.get()
    finally:
        await _close(config_store)
    if config is not None:
        updates["llm_provider"] = config.llm_provider
        updates["llm_model"] = config.llm_model

    # Resolve the credential for whichever provider is now active.
    provider = str(updates.get("llm_provider", base.llm_provider))
    credential_store = build_credential_store(base)
    try:
        credential = await credential_store.get(provider)
    finally:
        await _close(credential_store)
    if credential is not None:
        if credential.model:
            updates["llm_model"] = credential.model
        if credential.base_url:
            updates["llm_base_url"] = credential.base_url
        field = secret_field(provider)
        if field and credential.api_key:
            updates[field] = credential.api_key

    if not updates:
        return base
    return base.model_copy(update=updates)


def build_llm(settings: Settings) -> LLMProvider:
    """Select the LLM provider from configuration."""
    if settings.llm_provider == "github":
        token = settings.github_token or settings.llm_api_key
        if not token:
            raise ValueError(
                "KAOS_GITHUB_TOKEN is required for the 'github' LLM provider"
            )
        return OpenAICompatibleLLMProvider.github_models(
            token=token, model=settings.llm_model, timeout=settings.llm_timeout
        )
    if settings.llm_provider == "anthropic":
        key = settings.anthropic_api_key or settings.llm_api_key
        if not key:
            raise ValueError(
                "KAOS_ANTHROPIC_API_KEY is required for the 'anthropic' LLM provider"
            )
        # Honour a Claude model if set; otherwise default to Haiku.
        model = settings.llm_model if "claude" in settings.llm_model else DEFAULT_ANTHROPIC_MODEL
        return OpenAICompatibleLLMProvider.anthropic(
            api_key=key, model=model, timeout=settings.llm_timeout
        )
    if settings.llm_provider == "ollama":
        # Local, no secret. Use the configured base URL/model, falling back to
        # Ollama's defaults when the app-wide default model is still in place.
        base_url = settings.llm_base_url or OLLAMA_BASE_URL
        default_model = Settings.model_fields["llm_model"].default
        model = (
            settings.llm_model
            if settings.llm_model and settings.llm_model != default_model
            else DEFAULT_OLLAMA_MODEL
        )
        return OpenAICompatibleLLMProvider.ollama(
            model=model, base_url=base_url, timeout=settings.llm_timeout
        )
    if settings.llm_provider == "openai":
        if not settings.llm_api_key:
            raise ValueError(
                "KAOS_LLM_API_KEY is required for the 'openai' LLM provider"
            )
        return OpenAICompatibleLLMProvider(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or OPENAI_BASE_URL,
            timeout=settings.llm_timeout,
        )
    return EchoLLMProvider(response=SAMPLE_SUMMARY)


def build_runtime(settings: Settings) -> KaosRuntime:
    """Wire a KaosRuntime according to ``settings``.

    With no Discord token configured, `kaos up` reads the offline demo
    conversation; the summary is published to Discord if a webhook/token is set,
    otherwise to the console.
    """
    runtime = KaosRuntime(storage=build_storage(settings))
    runtime.register_connector(build_connector(settings))
    runtime.register_agent(ResumeAgent(build_llm(settings)))
    runtime.register_publisher(build_publisher(settings))
    return runtime


def build_connector(settings: Settings) -> DiscordConnector:
    """Select the connector: Discord backfill, live gateway, or the demo source."""
    if settings.discord_token:
        if settings.discord_backfill_channel_id:
            source: object = DiscordBackfillSource(
                token=settings.discord_token,
                channel_id=settings.discord_backfill_channel_id,
                guild_id=settings.discord_guild_id,
                limit=settings.discord_message_limit,
            )
        else:
            source = DiscordGatewaySource(
                token=settings.discord_token,
                guild_id=settings.discord_guild_id,
                channel_ids=settings.discord_channel_ids,
            )
        return DiscordConnector(source, emit_completed=True)  # type: ignore[arg-type]
    return DiscordConnector(StaticDiscordSource(list(SAMPLE_CONVERSATION)), emit_completed=True)


def build_publisher(settings: Settings) -> Publisher:
    """Select the publisher: bot REST (preferred), webhook (fallback), or console.

    The bot posts into the configured resume thread by id
    (`KAOS_DISCORD_RESUME_THREAD_ID`, e.g. "PMO"). The webhook is a write-only
    fallback for channels where the bot isn't authorized.
    """
    if settings.discord_token:
        return DiscordPublisher(
            DiscordRestPoster(settings.discord_token),
            thread_id=settings.discord_resume_thread_id,
            thread_name=settings.resume_thread_name,
        )
    if settings.discord_webhook_url:
        return DiscordWebhookPublisher(
            settings.discord_webhook_url,
            thread_id=settings.discord_resume_thread_id,
        )
    return ConsolePublisher()



