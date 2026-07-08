"""Plugin scaffolding for the KAOS CLI.

Generates a new agent, connector or publisher (plus its test) from the
templates in ``templates/``. This is KAOS dogfooding its own extensibility:
plugins are created through the public contracts, never by touching the Core.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

KIND_DIRS = {"agent": "agents", "connector": "connectors", "publisher": "publishers"}
VALID_KINDS = tuple(KIND_DIRS)

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


class ScaffoldError(Exception):
    """Raised when a plugin cannot be scaffolded."""


@dataclass(frozen=True)
class Names:
    """The derived identifiers for a scaffolded plugin."""

    kind: str
    class_name: str
    module_name: str
    plugin_name: str


def _tokens(raw: str) -> list[str]:
    """Split ``raw`` into lowercase word tokens (handles kebab/snake/camel)."""
    parts = re.split(r"[^a-zA-Z0-9]+", raw)
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        tokens.extend(t.lower() for t in _CAMEL_BOUNDARY.split(part))
    return tokens


def derive_names(kind: str, raw_name: str) -> Names:
    """Derive class, module and plugin names for ``kind`` and ``raw_name``."""
    if kind not in KIND_DIRS:
        raise ScaffoldError(f"unknown kind '{kind}'. Use one of: {', '.join(VALID_KINDS)}")
    tokens = _tokens(raw_name)
    if not tokens:
        raise ScaffoldError("plugin name must contain at least one alphanumeric character")
    if tokens[-1] == kind:  # avoid ResumeAgentAgent
        tokens = tokens[:-1]
    if not tokens:
        raise ScaffoldError("plugin name cannot be only the kind suffix")

    base_class = "".join(t.capitalize() for t in tokens)
    base_snake = "_".join(tokens)
    base_slug = "-".join(tokens)
    return Names(
        kind=kind,
        class_name=f"{base_class}{kind.capitalize()}",
        module_name=f"{base_snake}_{kind}",
        plugin_name=f"{base_slug}-{kind}",
    )


def find_templates_dir(start: Path | None = None) -> Path:
    """Locate the repository ``templates`` directory by walking up from here."""
    origin = (start or Path(__file__)).resolve()
    for parent in [origin, *origin.parents]:
        candidate = parent / "templates"
        if (candidate / "agent" / "agent.py.tmpl").exists():
            return candidate
    raise ScaffoldError("could not locate the 'templates' directory")


def _render(template: Path, names: Names) -> str:
    text = template.read_text(encoding="utf-8")
    return (
        text.replace("__CLASS_NAME__", names.class_name)
        .replace("__MODULE_NAME__", names.module_name)
        .replace("__PLUGIN_NAME__", names.plugin_name)
    )


def _ensure_package(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    init = directory / "__init__.py"
    if not init.exists():
        init.write_text('"""KAOS plugins."""\n', encoding="utf-8")


def scaffold(kind: str, raw_name: str, root: Path | None = None) -> list[Path]:
    """Create a new plugin and its test. Returns the created file paths."""
    names = derive_names(kind, raw_name)
    base = (root or Path.cwd()).resolve()
    templates = find_templates_dir()

    plugin_dir = base / "src" / "kaos" / "plugins" / KIND_DIRS[kind]
    tests_dir = base / "tests"
    plugin_file = plugin_dir / f"{names.module_name}.py"
    test_file = tests_dir / f"test_{names.module_name}.py"

    for target in (plugin_file, test_file):
        if target.exists():
            raise ScaffoldError(f"{target} already exists")

    _ensure_package(plugin_dir)
    tests_dir.mkdir(parents=True, exist_ok=True)

    plugin_file.write_text(
        _render(templates / kind / f"{kind}.py.tmpl", names), encoding="utf-8"
    )
    test_file.write_text(
        _render(templates / kind / f"test_{kind}.py.tmpl", names), encoding="utf-8"
    )
    return [plugin_file, test_file]

