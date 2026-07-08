"""Tests for the CLI plugin scaffolding."""

from __future__ import annotations

import py_compile
import shutil
from pathlib import Path

import pytest

from kaos.cli.scaffold import ScaffoldError, derive_names, find_templates_dir, scaffold


@pytest.mark.parametrize(
    ("kind", "raw", "class_name", "module_name", "plugin_name"),
    [
        ("agent", "resume", "ResumeAgent", "resume_agent", "resume-agent"),
        ("connector", "discord", "DiscordConnector", "discord_connector", "discord-connector"),
        ("publisher", "discord", "DiscordPublisher", "discord_publisher", "discord-publisher"),
        # suffix already present must not be duplicated
        ("agent", "resume-agent", "ResumeAgent", "resume_agent", "resume-agent"),
        # camelCase and multi-word names
        ("connector", "GitHub", "GitHubConnector", "git_hub_connector", "git-hub-connector"),
    ],
)
def test_derive_names(kind, raw, class_name, module_name, plugin_name) -> None:
    names = derive_names(kind, raw)
    assert names.class_name == class_name
    assert names.module_name == module_name
    assert names.plugin_name == plugin_name


def test_derive_names_rejects_unknown_kind() -> None:
    with pytest.raises(ScaffoldError):
        derive_names("widget", "foo")


def test_derive_names_rejects_empty() -> None:
    with pytest.raises(ScaffoldError):
        derive_names("agent", "!!!")


def _prepare_root(tmp_path: Path) -> Path:
    """Copy templates into a temporary project root so scaffold can find them."""
    templates = find_templates_dir()
    shutil.copytree(templates, tmp_path / "templates")
    (tmp_path / "src" / "kaos" / "plugins").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    return tmp_path


def test_scaffold_creates_valid_files(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    created = scaffold("agent", "weekly-report", root=root)

    assert len(created) == 2
    plugin_file, test_file = created
    assert plugin_file == root / "src" / "kaos" / "plugins" / "agents" / "weekly_report_agent.py"
    assert test_file == root / "tests" / "test_weekly_report_agent.py"

    # Rendered files must be syntactically valid Python.
    for path in created:
        py_compile.compile(str(path), doraise=True)

    content = plugin_file.read_text(encoding="utf-8")
    assert "class WeeklyReportAgent" in content
    assert 'name = "weekly-report-agent"' in content
    # The package marker was created.
    assert (root / "src" / "kaos" / "plugins" / "agents" / "__init__.py").exists()


def test_scaffold_refuses_to_overwrite(tmp_path: Path) -> None:
    root = _prepare_root(tmp_path)
    scaffold("connector", "discord", root=root)
    with pytest.raises(ScaffoldError):
        scaffold("connector", "discord", root=root)

