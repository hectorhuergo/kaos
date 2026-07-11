"""Read-only Discord REST helpers: resolve channel/forum and guild details.

These complement :mod:`kaos.plugins.connectors.discord_backfill` (which reads
message history) with the *metadata* KAOS needs to show human-friendly names and
indicators instead of raw ids (``discord:123…``): a channel's name/topic and a
guild's name, member/online counts and how many roles can administer it.

Everything here is best-effort and side-effect free. Callers pass a bot token;
without one (or on any transport/HTTP error) they should fall back to the raw id.
No discord.py dependency — plain httpx against the REST API.
"""

from __future__ import annotations

from typing import Any

import httpx

DISCORD_API = "https://discord.com/api/v10"

# Discord permission bit for ADMINISTRATOR (grants every permission).
_ADMINISTRATOR = 0x8

# A subset of channel type ids we care to label (Discord's numeric enum).
_CHANNEL_TYPES = {
    0: "canal de texto",
    2: "canal de voz",
    4: "categoría",
    5: "anuncios",
    10: "hilo de anuncios",
    11: "hilo público",
    12: "hilo privado",
    15: "foro",
    16: "media",
}


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bot {token}"}


async def fetch_channel(
    token: str, channel_id: str, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Return normalized details for a channel/forum/thread.

    Keys: ``id``, ``name``, ``topic``, ``type`` (numeric), ``type_label`` and
    ``guild_id``. Raises on transport/HTTP errors so the caller can fall back.
    """
    owns = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.get(
            f"{DISCORD_API}/channels/{channel_id}", headers=_headers(token)
        )
        resp.raise_for_status()
        raw = resp.json()
    finally:
        if owns:
            await http.aclose()
    ctype = raw.get("type")
    return {
        "id": str(raw.get("id", channel_id)),
        "name": raw.get("name") or None,
        "topic": raw.get("topic") or None,
        "type": ctype,
        "type_label": _CHANNEL_TYPES.get(ctype),
        "guild_id": str(raw["guild_id"]) if raw.get("guild_id") else None,
    }


async def fetch_guild(
    token: str, guild_id: str, *, client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    """Return normalized details + indicators for a guild (server).

    Keys: ``id``, ``name``, ``members`` (approximate), ``online`` (approximate
    presence), ``boosts`` (premium subscriptions) and ``owner_id``. Uses
    ``with_counts=true`` so member/online counts come back without the privileged
    members intent. Raises on transport/HTTP errors.
    """
    owns = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.get(
            f"{DISCORD_API}/guilds/{guild_id}",
            params={"with_counts": "true"},
            headers=_headers(token),
        )
        resp.raise_for_status()
        raw = resp.json()
    finally:
        if owns:
            await http.aclose()
    return {
        "id": str(raw.get("id", guild_id)),
        "name": raw.get("name") or None,
        "members": raw.get("approximate_member_count"),
        "online": raw.get("approximate_presence_count"),
        "boosts": raw.get("premium_subscription_count"),
        "owner_id": str(raw["owner_id"]) if raw.get("owner_id") else None,
    }


async def count_admin_roles(
    token: str, guild_id: str, *, client: httpx.AsyncClient | None = None
) -> int:
    """Return how many guild roles carry the ADMINISTRATOR permission.

    Listing members would need a privileged intent; roles do not. This is a good,
    cheap proxy for "how many roles can administer this server". Raises on
    transport/HTTP errors so the caller can fall back.
    """
    owns = client is None
    http = client or httpx.AsyncClient()
    try:
        resp = await http.get(
            f"{DISCORD_API}/guilds/{guild_id}/roles", headers=_headers(token)
        )
        resp.raise_for_status()
        roles = resp.json()
    finally:
        if owns:
            await http.aclose()
    admins = 0
    for role in roles:
        try:
            perms = int(role.get("permissions", "0"))
        except (TypeError, ValueError):
            perms = 0
        if perms & _ADMINISTRATOR:
            admins += 1
    return admins

