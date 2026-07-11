"""KAOS connectors."""

from __future__ import annotations

from kaos.plugins.connectors.discord_backfill import (
    DiscordBackfillSource,
    list_forum_threads,
)
from kaos.plugins.connectors.discord_connector import (
    DiscordConnector,
    DiscordMessage,
    DiscordMessageSource,
    StaticDiscordSource,
)
from kaos.plugins.connectors.discord_gateway import DiscordGatewaySource
from kaos.plugins.connectors.discord_rest import (
    count_admin_roles,
    fetch_channel,
    fetch_guild,
)
from kaos.plugins.connectors.github_connector import (
    GitHubActivitySource,
    GitHubConnector,
    GitHubItem,
    StaticGitHubSource,
)
from kaos.plugins.connectors.github_rest import GitHubRestSource

__all__ = [
    "DiscordBackfillSource",
    "DiscordConnector",
    "DiscordGatewaySource",
    "DiscordMessage",
    "DiscordMessageSource",
    "GitHubActivitySource",
    "GitHubConnector",
    "GitHubItem",
    "GitHubRestSource",
    "StaticDiscordSource",
    "StaticGitHubSource",
    "count_admin_roles",
    "fetch_channel",
    "fetch_guild",
    "list_forum_threads",
]

