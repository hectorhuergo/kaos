"""`kaos dev`: run the Dev Agent (an active teammate) on a task.

The agent works over the local repository with a safe, confined toolbox
(read/list/search files, run whitelisted commands) and produces a traceable
``dev.session`` artifact. With ``--dry-run`` nothing is persisted; otherwise the
session is stored in the knowledge base and shows up in the dashboard.
"""

from __future__ import annotations

from pathlib import Path

from kaos.bootstrap.factory import build_llm, build_storage, load_settings
from kaos.contracts.context import Context
from kaos.core.config import Settings
from kaos.plugins.agents import DevAgent
from kaos.plugins.tools import default_dev_tools


async def run_dev(
    task: str,
    *,
    repo_root: str = ".",
    max_steps: int = 8,
    dry_run: bool = False,
    settings: Settings | None = None,
) -> int:
    """Run the Dev Agent on ``task`` over ``repo_root``."""
    if not task.strip():
        print("error: falta la tarea (kaos dev \"<tarea>\")")
        return 1

    settings = await load_settings(settings)
    try:
        llm = build_llm(settings)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    root = Path(repo_root).resolve()
    if not root.is_dir():
        print(f"error: no existe el directorio: {repo_root}")
        return 1

    workspace = f"dev:{root.name}"
    tools = default_dev_tools(root)
    agent = DevAgent(llm, tools, max_steps=max_steps)


    context = Context(workspace=workspace, params={"task": task})
    print(
        f"KAOS dev — {agent.name} · modelo {settings.llm_model} · "
        f"repo {root.name} (dry_run={dry_run})\n"
    )
    artifacts = await agent.run(context)
    if not artifacts:
        print("(sin resultado)")
        return 1
    artifact = artifacts[0]

    # Show the session.
    for step in artifact.content.get("steps", []):
        if "tool" in step:
            print(f"· {step['tool']}({step.get('args', {})})")
    print("\n" + "-" * 48)
    print(artifact.content.get("answer", ""))
    print("-" * 48)

    if not dry_run:
        storage = build_storage(settings)
        try:
            await storage.save_artifact(artifact)
        finally:
            close = getattr(storage, "close", None)
            if close is not None:
                await close()
        print(f"\nGuardado en el knowledge base (workspace {workspace}).")
    else:
        print("\n(dry-run: no se persistió el artefacto)")
    print("Done.")
    return 0

