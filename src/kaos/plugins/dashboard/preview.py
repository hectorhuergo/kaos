"""Dry-run previews for the web console: summarize without publishing.

Runs the same pipelines as the CLI (`kaos github`, `kaos backfill[-forum]`) but
with a :class:`CapturingPublisher`, so the resulting summary can be shown in the
console **without ever posting to Discord** — even when a real Discord token is
present in the environment. Reading Discord/GitHub still happens (that is how a
summary is produced); only publishing is suppressed.
"""

from __future__ import annotations

import httpx

from kaos.cli.backfill import run_backfill, run_forum_backfill
from kaos.cli.github import run_github
from kaos.contracts.artifact import Artifact
from kaos.contracts.subscription import SubscriptionStore
from kaos.core.config import Settings
from kaos.domain.subscription import FORUM, GITHUB
from kaos.plugins.publishers import CapturingPublisher


class PreviewError(Exception):
    """Raised when a preview cannot be produced (bad input or a failed run)."""


def _http_message(exc: httpx.HTTPError) -> str:
    """A friendly, retriable message for a network/HTTP error during a preview."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return (
            f"la fuente respondió HTTP {code} "
            f"(revisá el repo/canal, el token y los permisos)"
        )
    if isinstance(exc, httpx.TimeoutException):
        return (
            "se agotó el tiempo de espera. Si usás un modelo local (Ollama), el "
            "primer resumen tras arrancar puede tardar en cargar el modelo — "
            "reintentá."
        )
    return f"error de red al generar la vista previa ({exc.__class__.__name__})"


async def preview_github(
    settings: Settings, repo: str, *, limit: int = 30, extra_instructions: str = ""
) -> list[Artifact]:
    """Summarize a GitHub repo in dry-run and return the captured artifacts."""
    if not repo.strip():
        raise PreviewError("repo is required (owner/repo)")
    capturing = CapturingPublisher()
    try:
        rc = await run_github(
            repo.strip(),
            dry_run=True,
            limit=limit,
            settings=settings,
            publisher=capturing,
            extra_instructions=extra_instructions,
        )
    except httpx.HTTPError as exc:
        raise PreviewError(_http_message(exc)) from exc
    if rc != 0 and not capturing.published:
        raise PreviewError("no se pudo generar la vista previa (ver logs del servidor)")
    return capturing.published


async def preview_subscription(
    settings: Settings,
    channel_id: str,
    *,
    subscription_store: SubscriptionStore,
    extra_instructions: str = "",
) -> list[Artifact]:
    """Summarize a subscription (forum consolidated, channel or repo) in dry-run.

    Looks up the subscription to know its kind and guild, runs the matching
    pipeline with a capturing publisher and returns the artifacts that *would*
    have been published.
    """
    subscription = await subscription_store.get(channel_id)
    if subscription is None:
        raise PreviewError(f"no existe una suscripción para {channel_id}")

    capturing = CapturingPublisher()
    if subscription.kind == FORUM:
        try:
            rc = await run_forum_backfill(
                subscription.channel_id,
                guild_id=subscription.guild_id,
                dry_run=True,
                consolidated=True,
                settings=settings,
                publisher=capturing,
                extra_instructions=extra_instructions,
            )
        except httpx.HTTPError as exc:
            raise PreviewError(_http_message(exc)) from exc
    elif subscription.kind == GITHUB:
        try:
            rc = await run_github(
                subscription.channel_id,
                dry_run=True,
                settings=settings,
                publisher=capturing,
                extra_instructions=extra_instructions,
            )
        except httpx.HTTPError as exc:
            raise PreviewError(_http_message(exc)) from exc
    else:
        try:
            rc = await run_backfill(
                subscription.channel_id,
                dry_run=True,
                settings=settings,
                publisher=capturing,
                extra_instructions=extra_instructions,
            )
        except httpx.HTTPError as exc:
            raise PreviewError(_http_message(exc)) from exc
    if rc != 0 and not capturing.published:
        raise PreviewError("no se pudo generar la vista previa (ver logs del servidor)")
    return capturing.published

