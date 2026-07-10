import argparse
from pathlib import Path

from kaos.cli.scaffold import VALID_KINDS, ScaffoldError, scaffold
from kaos.core.config import load_dotenv


def main() -> int:
    load_dotenv()  # composition root: make `.env` available to all commands
    p = argparse.ArgumentParser(prog="kaos")
    sub = p.add_subparsers(dest="cmd")
    for c in ("doctor", "version", "init", "down"):
        sub.add_parser(c)

    up_p = sub.add_parser("up", help="start the runtime from .env (or --offline demo)")
    up_p.add_argument(
        "--offline",
        action="store_true",
        help="run the deterministic offline demo (no credentials, ignores .env)",
    )

    new_p = sub.add_parser("new", help="scaffold a new plugin")
    new_p.add_argument("kind", choices=VALID_KINDS, help="plugin type")
    new_p.add_argument("name", help="plugin name, e.g. 'resume' or 'discord'")

    bf_p = sub.add_parser("backfill", help="read a Discord channel/thread and summarize it")
    bf_p.add_argument("channel_id", help="Discord channel/thread id to read")
    bf_p.add_argument(
        "--dry-run", action="store_true", help="print to console instead of publishing"
    )
    bf_p.add_argument("--limit", type=int, default=None, help="max messages to read")

    ff_p = sub.add_parser("backfill-forum", help="summarize every thread of a Discord forum")
    ff_p.add_argument("forum_channel_id", help="Discord forum channel id")
    ff_p.add_argument("--guild", default=None, help="guild id (overrides KAOS_DISCORD_GUILD_ID)")
    ff_p.add_argument(
        "--dry-run", action="store_true", help="print to console instead of publishing"
    )
    ff_p.add_argument("--limit", type=int, default=None, help="max messages per thread")
    ff_p.add_argument(
        "--consolidated",
        action="store_true",
        help="merge all thread summaries into a single 'Estado del Proyecto' report",
    )
    ff_p.add_argument(
        "--force",
        action="store_true",
        help="ignore the summary cache and re-summarize every thread",
    )
    ff_p.add_argument(
        "--only-if-changed",
        action="store_true",
        help="publish only when at least one thread changed (idempotent)",
    )

    sb_p = sub.add_parser("subscribe", help="watch a Discord forum/channel")
    sb_p.add_argument("channel_id", help="Discord forum/channel id to watch")
    sb_p.add_argument("--channel", action="store_true", help="subscribe a channel (default: forum)")
    sb_p.add_argument("--guild", default=None, help="guild id (overrides KAOS_DISCORD_GUILD_ID)")
    sb_p.add_argument("--resume-thread", default=None, help="thread id to publish summaries to")

    un_p = sub.add_parser("unsubscribe", help="stop watching a forum/channel")
    un_p.add_argument("channel_id", help="Discord forum/channel id to unsubscribe")

    sub.add_parser("subscriptions", help="list active subscriptions")

    run_p = sub.add_parser("run", help="summarize every active subscription")
    run_p.add_argument(
        "--dry-run", action="store_true", help="print to console instead of publishing"
    )
    run_p.add_argument(
        "--consolidated",
        action="store_true",
        help="merge each forum's thread summaries into a single report",
    )
    run_p.add_argument(
        "--force",
        action="store_true",
        help="ignore the summary cache and re-summarize everything",
    )

    sub.add_parser("providers", help="list LLM providers and their readiness")

    kn_p = sub.add_parser("knowledge", help="inspect the accumulated knowledge graph")
    kn_p.add_argument(
        "--workspace", default=None, help="workspace or Discord id (default: subscriptions)"
    )
    kn_p.add_argument(
        "--format",
        choices=("text", "mermaid", "json"),
        default="text",
        help="output format (default: text)",
    )
    kn_p.add_argument("--events", action="store_true", help="include source events as nodes")

    db_p = sub.add_parser("dashboard", help="write a self-contained HTML dashboard")
    db_p.add_argument(
        "--workspace", default=None, help="workspace or Discord id (default: subscriptions)"
    )
    db_p.add_argument("--out", default="kaos-dashboard.html", help="output HTML file")
    db_p.add_argument("--events", action="store_true", help="include source events in the graph")

    sv_p = sub.add_parser("serve", help="serve the live FastAPI dashboard")
    sv_p.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    sv_p.add_argument("--port", type=int, default=8000, help="bind port (default 8000)")

    gh_p = sub.add_parser("github", help="summarize a GitHub repository's recent activity")
    gh_p.add_argument("repo", nargs="?", default=None, help="owner/repo (default KAOS_GITHUB_REPO)")
    gh_p.add_argument(
        "--dry-run", action="store_true", help="print to console instead of publishing"
    )
    gh_p.add_argument("--limit", type=int, default=30, help="max items per kind (default 30)")
    gh_p.add_argument("--no-issues", action="store_true", help="commits only (skip issues/PRs)")

    sc_p = sub.add_parser("schedule", help="run subscriptions periodically (idempotent)")
    sc_p.add_argument(
        "--interval",
        type=float,
        default=None,
        help="seconds between runs (default KAOS_SCHEDULER_INTERVAL or 900)",
    )
    sc_p.add_argument(
        "--once", action="store_true", help="run a single pass and exit (for external cron)"
    )
    sc_p.add_argument(
        "--dry-run", action="store_true", help="print to console instead of publishing"
    )
    sc_p.add_argument(
        "--consolidated",
        action="store_true",
        help="merge each forum's thread summaries into a single report",
    )
    sc_p.add_argument("--force", action="store_true", help="ignore the summary cache")

    dev_p = sub.add_parser("dev", help="run the Dev Agent (active teammate) on a task")
    dev_p.add_argument("task", help="the task, e.g. \"revisá el módulo de cache y sugerí mejoras\"")
    dev_p.add_argument("--repo-root", default=".", help="repository root the agent works on")
    dev_p.add_argument("--max-steps", type=int, default=8, help="max tool-use steps (default 8)")
    dev_p.add_argument("--dry-run", action="store_true", help="do not persist the session artifact")

    a = p.parse_args()
    if a.cmd == "doctor":
        print("Environment OK (beta)")
    elif a.cmd == "version":
        print("KAOS 1.0.0-beta.1")
    elif a.cmd == "up":
        import asyncio

        from kaos.runtime.demo import run_demo, run_offline_demo

        asyncio.run(run_offline_demo() if a.offline else run_demo())
        return 0
    elif a.cmd == "backfill":
        import asyncio

        from kaos.cli.backfill import run_backfill

        return asyncio.run(
            run_backfill(a.channel_id, dry_run=a.dry_run, limit=a.limit)
        )
    elif a.cmd == "backfill-forum":
        import asyncio

        from kaos.cli.backfill import run_forum_backfill

        return asyncio.run(
            run_forum_backfill(
                a.forum_channel_id,
                guild_id=a.guild,
                dry_run=a.dry_run,
                limit=a.limit,
                consolidated=a.consolidated,
                force=a.force,
                only_if_changed=a.only_if_changed,
            )
        )
    elif a.cmd == "new":
        try:
            created = scaffold(a.kind, a.name, root=Path.cwd())
        except ScaffoldError as exc:
            print(f"error: {exc}")
            return 1
        print(f"Created {a.kind}:")
        for path in created:
            print(f"  {path.relative_to(Path.cwd())}")
        return 0
    elif a.cmd == "subscribe":
        import asyncio

        from kaos.cli.subscriptions import add_subscription
        from kaos.domain.subscription import CHANNEL, FORUM

        return asyncio.run(
            add_subscription(
                a.channel_id,
                kind=CHANNEL if a.channel else FORUM,
                guild_id=a.guild,
                resume_thread_id=a.resume_thread,
            )
        )
    elif a.cmd == "unsubscribe":
        import asyncio

        from kaos.cli.subscriptions import remove_subscription

        return asyncio.run(remove_subscription(a.channel_id))
    elif a.cmd == "subscriptions":
        import asyncio

        from kaos.cli.subscriptions import list_subscriptions

        return asyncio.run(list_subscriptions())
    elif a.cmd == "run":
        import asyncio

        from kaos.cli.subscriptions import run_subscriptions

        return asyncio.run(
            run_subscriptions(
                dry_run=a.dry_run, consolidated=a.consolidated, force=a.force
            )
        )
    elif a.cmd == "providers":
        from kaos.cli.providers import list_providers

        return list_providers()
    elif a.cmd == "knowledge":
        import asyncio

        from kaos.cli.knowledge import run_knowledge

        return asyncio.run(
            run_knowledge(workspace=a.workspace, fmt=a.format, include_events=a.events)
        )
    elif a.cmd == "dashboard":
        import asyncio

        from kaos.cli.knowledge import run_dashboard

        return asyncio.run(
            run_dashboard(workspace=a.workspace, out=a.out, include_events=a.events)
        )
    elif a.cmd == "serve":
        from kaos.cli.knowledge import run_serve

        return run_serve(host=a.host, port=a.port)
    elif a.cmd == "github":
        import asyncio

        from kaos.cli.github import run_github

        return asyncio.run(
            run_github(
                a.repo, dry_run=a.dry_run, limit=a.limit, include_issues=not a.no_issues
            )
        )
    elif a.cmd == "schedule":
        import asyncio

        from kaos.cli.schedule import run_scheduler

        return asyncio.run(
            run_scheduler(
                interval=a.interval,
                once=a.once,
                dry_run=a.dry_run,
                consolidated=a.consolidated,
                force=a.force,
            )
        )
    elif a.cmd == "dev":
        import asyncio

        from kaos.cli.dev import run_dev

        return asyncio.run(
            run_dev(
                a.task,
                repo_root=a.repo_root,
                max_steps=a.max_steps,
                dry_run=a.dry_run,
            )
        )
    elif a.cmd:
        print(f"{a.cmd}: pending")
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

