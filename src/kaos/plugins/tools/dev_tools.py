"""Dev tools: a safe, workspace-confined toolbox for the Dev Agent.

Every tool is confined to a *root* directory (the repository): paths are resolved
and rejected if they escape the root, and :class:`RunCommandTool` only runs
commands whose token prefix is explicitly allowed. Output is truncated so a large
file or a chatty command cannot blow up the context.

These are plain plugins implementing the :class:`~kaos.contracts.tool.Tool`
contract; the Core never imports them.
"""

from __future__ import annotations

import asyncio
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_MAX_OUTPUT = 4000  # chars returned to the model per observation


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncado, {len(text) - limit} caracteres más]"


class _Confined:
    """Resolves paths within a root directory, rejecting traversal."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def resolve(self, path: str) -> Path:
        candidate = (self.root / (path or ".")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ValueError(f"ruta fuera del workspace: {path}")
        return candidate


class ReadFileTool:
    """Read a UTF-8 text file within the workspace."""

    name = "read_file"
    description = "Lee un archivo de texto del repo. args: {path}"

    def __init__(self, root: str | Path) -> None:
        self._c = _Confined(root)

    async def run(self, args: dict[str, Any]) -> str:
        path = str(args.get("path", "")).strip()
        if not path:
            return "error: falta 'path'"
        try:
            target = self._c.resolve(path)
        except ValueError as exc:
            return f"error: {exc}"
        if not target.is_file():
            return f"error: no es un archivo: {path}"
        try:
            return _truncate(target.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            return f"error al leer {path}: {exc}"


class ListDirTool:
    """List the entries of a directory within the workspace."""

    name = "list_dir"
    description = "Lista el contenido de un directorio del repo. args: {path?}"

    def __init__(self, root: str | Path) -> None:
        self._c = _Confined(root)

    async def run(self, args: dict[str, Any]) -> str:
        path = str(args.get("path", ".")).strip() or "."
        try:
            target = self._c.resolve(path)
        except ValueError as exc:
            return f"error: {exc}"
        if not target.is_dir():
            return f"error: no es un directorio: {path}"
        entries = sorted(
            (p.name + ("/" if p.is_dir() else "") for p in target.iterdir()),
            key=str.lower,
        )
        return _truncate("\n".join(entries) or "(vacío)")


class SearchCodeTool:
    """Search for a substring across text files in the workspace."""

    name = "search_code"
    description = (
        "Busca un texto en los archivos del repo. args: {query, ext?} "
        "(ext p. ej. '.py'). Devuelve rutas y líneas coincidentes."
    )
    _SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache"}

    def __init__(self, root: str | Path, *, max_matches: int = 50) -> None:
        self._c = _Confined(root)
        self._max = max_matches

    async def run(self, args: dict[str, Any]) -> str:
        query = str(args.get("query", "")).strip()
        if not query:
            return "error: falta 'query'"
        ext = str(args.get("ext", "")).strip()
        root = self._c.root
        matches: list[str] = []
        for path in root.rglob("*"):
            if any(part in self._SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            if not path.is_file():
                continue
            if ext and path.suffix != ext:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if query in line:
                    rel = path.relative_to(root).as_posix()
                    matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                    if len(matches) >= self._max:
                        matches.append("… [más coincidencias omitidas]")
                        return _truncate("\n".join(matches))
        return _truncate("\n".join(matches) or "(sin coincidencias)")


# Command token-prefixes the Dev Agent may run. Anything not starting with one
# of these is rejected. Deliberately narrow: read-only/analysis commands only.
DEFAULT_ALLOWED_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("ruff", "check"),
    ("ruff", "format", "--check"),
    ("mypy",),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
    ("git", "show"),
)


class RunCommandTool:
    """Run a whitelisted, non-interactive command inside the workspace.

    Commands run with ``cwd=root`` and **no shell** (arguments are split with
    :func:`shlex.split`), so there is no shell injection. Only commands whose
    token prefix matches ``allowed`` are executed; everything else is refused.
    """

    name = "run_command"
    description = (
        "Ejecuta un comando permitido (solo lectura/análisis) en el repo. "
        "args: {command}. Permitidos: pytest, python -m pytest, ruff check, "
        "mypy, git status|diff|log|show."
    )

    def __init__(
        self,
        root: str | Path,
        *,
        allowed: Sequence[Sequence[str]] = DEFAULT_ALLOWED_COMMANDS,
        timeout: float = 120.0,
    ) -> None:
        self._root = Path(root).resolve()
        self._allowed = tuple(tuple(a) for a in allowed)
        self._timeout = timeout

    def _is_allowed(self, tokens: Sequence[str]) -> bool:
        return any(
            len(tokens) >= len(prefix) and tuple(tokens[: len(prefix)]) == prefix
            for prefix in self._allowed
        )

    async def run(self, args: dict[str, Any]) -> str:
        command = str(args.get("command", "")).strip()
        if not command:
            return "error: falta 'command'"
        try:
            tokens = shlex.split(command)
        except ValueError as exc:
            return f"error: comando inválido: {exc}"
        if not tokens or not self._is_allowed(tokens):
            return (
                f"error: comando no permitido: {command!r}. "
                "Solo se permiten comandos de solo lectura/análisis."
            )
        try:
            proc = await asyncio.create_subprocess_exec(
                *tokens,
                cwd=str(self._root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except (OSError, ValueError) as exc:
            return f"error al ejecutar: {exc}"
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except TimeoutError:
            proc.kill()
            return f"error: el comando superó el tiempo límite ({self._timeout:.0f}s)"
        output = (stdout or b"").decode("utf-8", errors="replace")
        return _truncate(f"[exit {proc.returncode}]\n{output}")


def default_dev_tools(
    root: str | Path,
    *,
    allow_commands: Sequence[Sequence[str]] = DEFAULT_ALLOWED_COMMANDS,
) -> list[Any]:
    """Return the standard read/analyze toolbox confined to ``root``."""
    return [
        ReadFileTool(root),
        ListDirTool(root),
        SearchCodeTool(root),
        RunCommandTool(root, allowed=allow_commands),
    ]

