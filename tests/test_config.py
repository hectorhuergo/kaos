"""Tests for KAOS configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from kaos.core.config import Settings, load_dotenv


def test_defaults_when_env_empty() -> None:
    settings = Settings.from_env({})
    assert settings.llm_provider == "echo"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.discord_enabled is False
    assert settings.discord_channel_ids == ()
    assert settings.resume_thread_name == "📋 Resume"


def test_reads_llm_and_discord_env() -> None:
    settings = Settings.from_env(
        {
            "KAOS_LLM_PROVIDER": "github",
            "KAOS_LLM_MODEL": "gpt-4o",
            "KAOS_GITHUB_TOKEN": "ght",
            "KAOS_DISCORD_TOKEN": "dtoken",
            "KAOS_DISCORD_GUILD_ID": "42",
            "KAOS_DISCORD_CHANNEL_IDS": "100, 200 ,300",
        }
    )
    assert settings.llm_provider == "github"
    assert settings.llm_model == "gpt-4o"
    assert settings.github_token == "ght"
    assert settings.discord_enabled is True
    assert settings.discord_guild_id == "42"
    assert settings.discord_channel_ids == ("100", "200", "300")


def test_github_token_falls_back_to_standard_env() -> None:
    settings = Settings.from_env({"GITHUB_TOKEN": "std"})
    assert settings.github_token == "std"


def test_invalid_provider_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.from_env({"KAOS_LLM_PROVIDER": "banana"})


def test_load_dotenv_populates_without_override(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "export KAOS_LLM_MODEL='gpt-4o'\n"
        'KAOS_DISCORD_GUILD_ID="42"\n'
        "KAOS_EXISTING=fromfile\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("KAOS_LLM_MODEL", raising=False)
    monkeypatch.setenv("KAOS_EXISTING", "fromenv")

    load_dotenv(env_file)

    assert os.environ["KAOS_LLM_MODEL"] == "gpt-4o"
    assert os.environ["KAOS_DISCORD_GUILD_ID"] == "42"
    # Existing variables are not overridden.
    assert os.environ["KAOS_EXISTING"] == "fromenv"


def test_load_dotenv_missing_file_is_noop(tmp_path: Path) -> None:
    load_dotenv(tmp_path / "does-not-exist.env")  # must not raise


