"""Resolve friendly names and header details for workspaces.

The rest of KAOS reasons about canonical workspace ids (``discord:123``,
``github:owner/repo``). Operators, though, want to see the *name* of the channel
or forum. This module resolves those names (and, for the dashboard header, the
channel/guild indicators) best-effort via the Discord REST API, always falling
back to the raw id when there is no token or the lookup fails.

Results are memoized per process so listing subscriptions or rendering the
dashboard does not hit Discord repeatedly for the same id.
"""

from __future__ import annotations

import contextlib

import httpx

from kaos.core.config import Settings
from kaos.plugins.connectors.discord_rest import (
    count_admin_roles,
    fetch_channel,
    fetch_guild,
)

_DISCORD_PREFIX = "discord:"
_GITHUB_PREFIX = "github:"

# Per-process memoization: workspace -> label, and workspace -> header dict.
_label_cache: dict[str, str] = {}
_header_cache: dict[str, dict[str, object]] = {}


def _channel_id(workspace: str) -> str | None:
    """Return the Discord channel id embedded in a workspace, if any."""
    if workspace.startswith(_DISCORD_PREFIX):
        return workspace[len(_DISCORD_PREFIX) :]
    return None


def fallback_label(workspace: str) -> str:
    """A readable label without any network lookup.

    GitHub workspaces already read well as ``owner/repo``; Discord ones degrade
    to the raw id until a token lets us resolve the channel name.
    """
    if workspace.startswith(_GITHUB_PREFIX):
        return workspace[len(_GITHUB_PREFIX) :]
    return workspace


async def resolve_label(
    workspace: str, settings: Settings, *, client: httpx.AsyncClient | None = None
) -> str:
    """Return a friendly label for a workspace (channel/forum name).

    Best-effort: without a Discord token, or on any error, returns
    :func:`fallback_label`. Results are cached per process.
    """
    if workspace in _label_cache:
        return _label_cache[workspace]

    label = fallback_label(workspace)
    channel_id = _channel_id(workspace)
    token = settings.discord_token
    if channel_id and token:
        try:
            channel = await fetch_channel(token, channel_id, client=client)
            if channel.get("name"):
                label = str(channel["name"])
        except (httpx.HTTPError, KeyError, ValueError):
            label = fallback_label(workspace)

    _label_cache[workspace] = label
    return label


async def resolve_labels(
    workspaces: list[str], settings: Settings, *, client: httpx.AsyncClient | None = None
) -> dict[str, str]:
    """Resolve labels for many workspaces, sharing one HTTP client."""
    if not workspaces:
        return {}
    owns = client is None and bool(settings.discord_token)
    http = client if client is not None else (httpx.AsyncClient() if owns else None)
    try:
        return {ws: await resolve_label(ws, settings, client=http) for ws in workspaces}
    finally:
        if owns and http is not None:
            await http.aclose()


async def resolve_header(
    workspace: str, settings: Settings, *, client: httpx.AsyncClient | None = None
) -> dict[str, object] | None:
    """Return channel/guild details + indicators for a workspace header.

    Only meaningful for Discord workspaces with a token; returns ``None`` when
    nothing can be resolved (the dashboard then shows its plain header).
    """
    if workspace in _header_cache:
        return _header_cache[workspace] or None

    channel_id = _channel_id(workspace)
    token = settings.discord_token
    if not channel_id or not token:
        return None

    owns = client is None
    http = client or httpx.AsyncClient()
    header: dict[str, object] = {"workspace": workspace}
    try:
        try:
            channel = await fetch_channel(token, channel_id, client=http)
            header["channel"] = channel
        except (httpx.HTTPError, KeyError, ValueError):
            return None

        guild_id = channel.get("guild_id") or settings.discord_guild_id
        if guild_id:
            try:
                guild = await fetch_guild(token, str(guild_id), client=http)
                with contextlib.suppress(httpx.HTTPError, KeyError, ValueError):
                    guild["admin_roles"] = await count_admin_roles(
                        token, str(guild_id), client=http
                    )
                header["guild"] = guild
            except (httpx.HTTPError, KeyError, ValueError):
                pass
    finally:
        if owns:
            await http.aclose()

    # Cache the label too, so the section heading agrees with the header.
    cached_channel = header.get("channel")
    if isinstance(cached_channel, dict) and cached_channel.get("name"):
        _label_cache[workspace] = str(cached_channel["name"])
    _header_cache[workspace] = header
    return header


def clear_cache() -> None:
    """Drop memoized labels/headers (useful in tests)."""
    _label_cache.clear()
    _header_cache.clear()


# Re-exported for callers that want the canonical form.
__all__ = [
    "clear_cache",
    "fallback_label",
    "resolve_header",
    "resolve_label",
    "resolve_labels",
]



