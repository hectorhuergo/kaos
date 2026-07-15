"""Interactive run for the web console: generate summaries **and persist them**.

Unlike :mod:`kaos.plugins.dashboard.preview` (a dry-run that shows a summary
without persisting or publishing), this runs the real pipeline so the results are
stored in the knowledge base and the **summary cache is populated** — exactly
what a scheduled ``kaos run`` would produce. By default it captures the output
(nothing is posted to Discord); with ``publish=True`` it also sends the result to
the configured publisher (a deliberate action). ``run_all`` does the same across
every active subscription.
"""

from __future__ import annotations

import httpx

from kaos.bootstrap.factory import build_publisher
from kaos.cli.backfill import run_backfill, run_forum_backfill
from kaos.cli.github import run_github
from kaos.contracts.artifact import Artifact
from kaos.contracts.publisher import Publisher
from kaos.contracts.subscription import SubscriptionStore
from kaos.core.config import Settings
from kaos.domain.subscription import FORUM, GITHUB
from kaos.plugins.dashboard.preview import _http_message
from kaos.plugins.publishers import CapturingPublisher


class RunError(Exception):
    """Raised when an interactive run cannot complete (bad input or failed run)."""


class _TeePublisher:
    """Fan-out publisher: forwards each artifact to several publishers.

    Used to both **publish for real** (Discord) and **capture** the artifacts so
    the console can display what was published in the same request.
    """

    name = "tee-publisher"

    def __init__(self, *publishers: Publisher) -> None:
        self._publishers = publishers

    async def publish(self, artifact: Artifact) -> None:
        for pub in self._publishers:
            await pub.publish(artifact)


def _publisher_for(
    settings: Settings, *, publish: bool, capturing: CapturingPublisher
) -> Publisher:
    """Choose the run publisher: capture-only, or publish-to-Discord + capture."""
    if not publish:
        return capturing
    try:
        real = build_publisher(settings)
    except ValueError as exc:  # no Discord configured
        raise RunError(f"no se puede publicar: {exc}") from exc
    return _TeePublisher(real, capturing)


async def run_subscription(
    settings: Settings,
    channel_id: str,
    *,
    subscription_store: SubscriptionStore,
    publish: bool = False,
    force: bool = False,
    consolidated: bool = True,
    extra_instructions: str = "",
    llm_provider: str | None = None,
    llm_model: str | None = None,
    agent_id: str | None = None,
) -> list[Artifact]:
    """Run a subscription for real (persist + cache), optionally publishing.

    Reads the source (Discord/GitHub), summarizes it, **stores** the artifacts
    and **populates the summary cache**, and returns the artifacts that would be
    published. With ``publish=True`` the result is also sent to the configured
    publisher (Discord); otherwise nothing is posted. ``force`` re-summarizes
    ignoring the cache; otherwise unchanged conversations reuse the cache.

    The LLM override defaults to the subscription's stored ``llm_provider``/
    ``llm_model``; an explicit ``llm_provider``/``llm_model`` argument (e.g. from
    the dashboard confirm modal) wins for this run. ``agent_id`` likewise
    defaults to the subscription's stored agent.
    """
    subscription = await subscription_store.get(channel_id)
    if subscription is None:
        raise RunError(f"no existe una suscripción para {channel_id}")

    provider = llm_provider or subscription.llm_provider
    model = llm_model or subscription.llm_model
    agent = agent_id or subscription.agent_id

    # Publish to *this subscription's* resume thread when it has one, falling back
    # to the global default only when the subscription does not set it. Without
    # this the console run would always use the env-wide
    # ``KAOS_DISCORD_RESUME_THREAD_ID``, overriding the per-subscription value
    # (matching the CLI ``run_subscriptions`` precedence).
    run_settings = settings.model_copy(
        update={
            "discord_resume_thread_id": (
                subscription.resume_thread_id or settings.discord_resume_thread_id
            )
        }
    )

    capturing = CapturingPublisher()
    publisher = _publisher_for(run_settings, publish=publish, capturing=capturing)
    try:
        if subscription.kind == FORUM:
            rc = await run_forum_backfill(
                subscription.channel_id,
                guild_id=subscription.guild_id,
                dry_run=False,  # real storage → persists artifacts + cache
                consolidated=consolidated,
                force=force,
                only_if_changed=False,  # always surface the current summaries
                settings=run_settings,
                publisher=publisher,
                extra_instructions=extra_instructions,
                llm_provider=provider,
                llm_model=model,
                agent_id=agent,
            )
        elif subscription.kind == GITHUB:
            rc = await run_github(
                subscription.channel_id,
                dry_run=False,
                settings=run_settings,
                publisher=publisher,
                extra_instructions=extra_instructions,
                llm_provider=provider,
                llm_model=model,
                agent_id=agent,
            )
        else:
            rc = await run_backfill(
                subscription.channel_id,
                dry_run=False,
                settings=run_settings,
                publisher=publisher,
                extra_instructions=extra_instructions,
                llm_provider=provider,
                llm_model=model,
                agent_id=agent,
            )
    except httpx.HTTPError as exc:
        raise RunError(_http_message(exc)) from exc
    if rc != 0 and not capturing.published:
        raise RunError("no se pudo completar la corrida (ver logs del servidor)")
    return capturing.published


async def run_all(
    settings: Settings,
    *,
    subscription_store: SubscriptionStore,
    publish: bool = False,
    force: bool = False,
    extra_instructions: str = "",
) -> list[Artifact]:
    """Run every active subscription (persist + cache), optionally publishing.

    Aggregates the artifacts produced across all subscriptions. A failing
    subscription raises; partial results before the failure are lost, mirroring
    the CLI ``kaos run`` semantics (each run is idempotent, so retrying is safe).
    """
    subs = await subscription_store.list(active_only=True)
    artifacts: list[Artifact] = []
    for sub in subs:
        produced = await run_subscription(
            settings,
            sub.channel_id,
            subscription_store=subscription_store,
            publish=publish,
            force=force,
            extra_instructions=extra_instructions,
        )
        artifacts.extend(produced)
    return artifacts



