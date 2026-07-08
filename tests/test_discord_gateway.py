"""Tests for the Discord gateway source message mapping (no network)."""

from __future__ import annotations

from types import SimpleNamespace

from kaos.plugins.connectors import DiscordGatewaySource


class _Author:
    def __init__(self, name: str, bot: bool = False) -> None:
        self._name = name
        self.bot = bot

    def __str__(self) -> str:
        return self._name


def test_to_discord_message_maps_fields() -> None:
    msg = SimpleNamespace(
        id=555,
        content="hola equipo",
        author=_Author("ana"),
        channel=SimpleNamespace(id=100),
        guild=SimpleNamespace(id=42),
    )

    result = DiscordGatewaySource.to_discord_message(msg)

    assert result.message_id == "555"
    assert result.channel_id == "100"
    assert result.guild_id == "42"
    assert result.author == "ana"
    assert result.text == "hola equipo"


def test_accepts_filters_bots_and_channels() -> None:
    source = DiscordGatewaySource(token="t", guild_id="42", channel_ids=["100"])

    human = _Author("ana", bot=False)
    bot = _Author("botty", bot=True)

    ok = SimpleNamespace(author=human, channel=SimpleNamespace(id=100), guild=SimpleNamespace(id=42))
    from_bot = SimpleNamespace(author=bot, channel=SimpleNamespace(id=100), guild=SimpleNamespace(id=42))
    other_channel = SimpleNamespace(author=human, channel=SimpleNamespace(id=999), guild=SimpleNamespace(id=42))
    other_guild = SimpleNamespace(author=human, channel=SimpleNamespace(id=100), guild=SimpleNamespace(id=1))

    assert source._accepts(ok) is True  # type: ignore[attr-defined]
    assert source._accepts(from_bot) is False  # type: ignore[attr-defined]
    assert source._accepts(other_channel) is False  # type: ignore[attr-defined]
    assert source._accepts(other_guild) is False  # type: ignore[attr-defined]

