"""Composition root: builds a KaosRuntime from Settings.

This is the one place allowed to know about every plugin. It selects the LLM
provider, connector and publisher according to configuration, keeping the Core
and the plugins decoupled from each other.
"""

from __future__ import annotations

from kaos.contracts.llm import LLMProvider
from kaos.contracts.storage import Storage
from kaos.contracts.subscription import SubscriptionStore
from kaos.core.config import Settings
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import (
    DiscordBackfillSource,
    DiscordConnector,
    DiscordGatewaySource,
    StaticDiscordSource,
)
from kaos.plugins.publishers import (
    ConsolePublisher,
    DiscordPublisher,
    DiscordRestPoster,
    DiscordWebhookPublisher,
)
from kaos.plugins.providers import OPENAI_BASE_URL, OpenAICompatibleLLMProvider
from kaos.runtime import InMemoryStorage, KaosRuntime
from kaos.runtime import InMemorySubscriptionStore
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


def build_llm(settings: Settings) -> LLMProvider:
    """Select the LLM provider from configuration."""
    if settings.llm_provider == "github":
        token = settings.github_token or settings.llm_api_key
        if not token:
            raise ValueError(
                "KAOS_GITHUB_TOKEN is required for the 'github' LLM provider"
            )
        return OpenAICompatibleLLMProvider.github_models(token=token, model=settings.llm_model)
    if settings.llm_provider == "openai":
        if not settings.llm_api_key:
            raise ValueError(
                "KAOS_LLM_API_KEY is required for the 'openai' LLM provider"
            )
        return OpenAICompatibleLLMProvider(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url or OPENAI_BASE_URL,
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


def build_publisher(settings):  # type: ignore[no-untyped-def]
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



