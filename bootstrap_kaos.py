#!/usr/bin/env python3
"""KAOS bootstrap: verifies the environment and prepares it for development.

The script is dependency-free (standard library only). It never creates a
virtual environment with an incompatible interpreter: it validates the Python
version first and fails clearly when a requirement is not met.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_PYTHON = (3, 13)


def _fmt(ok: bool) -> str:
    return "OK" if ok else "MISSING"


def check_python() -> bool:
    """Return whether the running interpreter satisfies REQUIRED_PYTHON."""
    ok = sys.version_info[:2] >= REQUIRED_PYTHON
    required = ".".join(str(n) for n in REQUIRED_PYTHON)
    print(f"Python: {sys.version.split()[0]} (require >= {required}) -> {_fmt(ok)}")
    return ok


def check_tool(name: str) -> bool:
    """Report whether an executable is available on PATH."""
    ok = shutil.which(name) is not None
    print(f"{name.capitalize()}: {_fmt(ok)}")
    return ok


def create_venv() -> None:
    """Create .venv using the current (already validated) interpreter."""
    if Path(".venv").exists():
        print(".venv: already exists")
        return
    print("Creating .venv ...")
    subprocess.run([sys.executable, "-m", "venv", ".venv"], check=False)


def main() -> int:
    print("KAOS Bootstrap — v1.0.0-beta")
    print(f"OS: {platform.system()} {platform.release()}")

    python_ok = check_python()
    git_ok = check_tool("git")
    docker_ok = check_tool("docker")
    uv_ok = check_tool("uv")

    print("-" * 48)

    if not python_ok:
        required = ".".join(str(n) for n in REQUIRED_PYTHON)
        print(f"ERROR: KAOS requires Python >= {required}.")
        print("Install it (e.g. `uv python install 3.13`) and re-run this script")
        print("with that interpreter. The .venv was NOT created.")
        return 1

    if not git_ok:
        print("ERROR: Git is required to work on KAOS. Install it and re-run.")
        return 1

    if uv_ok:
        print("uv detected. Recommended setup:")
        print("  uv sync")
        print("  uv run kaos doctor")
    else:
        print("uv not found (recommended). Falling back to venv + pip.")
        create_venv()
        activate = (
            ".venv\\Scripts\\activate"
            if platform.system() == "Windows"
            else "source .venv/bin/activate"
        )
        print("Next steps:")
        print(f"  {activate}")
        print("  python -m pip install -e .[dev]")
        print("  kaos doctor")

    if not docker_ok:
        print("Note: Docker not found. It is needed for `docker compose up`")
        print("(PostgreSQL, Redis, MinIO), but not to run the CLI or tests.")

    print("Bootstrap complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
