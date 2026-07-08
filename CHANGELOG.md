# Changelog

## Unreleased
- GitHub Connector: `GitHubConnector` + `GitHubRestSource`
  (`src/kaos/plugins/connectors/`) turn a repository's recent commits and
  issues/PRs into `message.created` events, so the Resume Agent summarizes a
  repo's activity into knowledge (KAOS dogfooding its own development). CLI
  `kaos github [<owner/repo>] [--dry-run] [--limit N] [--no-issues]`; repo also
  via `KAOS_GITHUB_REPO`. ADR-0012.
- Docs: `docs/QUICKSTART.md` — get KAOS running in minutes (offline demo, real
  Discord + LLM run, subscriptions/scheduler, knowledge/dashboard, plugin
  scaffolding, troubleshooting); linked from the README.

## 1.0.0-beta.1 — 2026-07-08
- Live dashboard: `create_app()` (`src/kaos/plugins/dashboard/app.py`) serves a
  read-only FastAPI app that reads `Storage` on each request, so the view is
  always current. Routes: `/` (HTML), `/api/workspaces`, `/api/knowledge`
  (graph JSON), `/api/artifacts`. `kaos serve [--host] [--port]` runs it via
  uvicorn (optional extra `.[dashboard]`). A shared service
  (`plugins/dashboard/service.py`) backs both the CLI and the app. ADR-0011.
- License: MIT (`LICENSE`); declared in `pyproject.toml`.
- Knowledge Graph (`src/kaos/core/knowledge.py`): a read-model over the `Storage`
  contract that projects stored artifacts (and optionally their source events)
  into nodes/edges — no new datastore. Exports to dict (JSON) and Mermaid.
- Dashboard (`src/kaos/plugins/dashboard/`): a self-contained HTML view of the
  knowledge (summary cards + Mermaid traceability graph); no server needed.
  Mermaid loads as a classic UMD script (an ES-module import of the UMD build
  rendered as raw text) and the graph sits in a scrollable container so dense
  graphs stay legible; graph labels are sanitized for the Mermaid parser.
- CLI: `kaos knowledge [--workspace W] [--format text|mermaid|json] [--events]`
  and `kaos dashboard [--workspace W] [--out FILE] [--events]`. Workspaces default
  to the active subscriptions; a bare Discord id is normalized to `discord:<id>`.
- ADR-0010 — Knowledge Layer & Graph.
- Docs: aligned `ARCHITECTURE.md` (Core section: provider catalog, summary cache,
  redaction; Scheduler in Runtime; timestamp-aware transcripts), refreshed the
  `docs/` stubs (`ARCHITECTURE.md`, `ROADMAP.md`) and expanded `CONTRIBUTING.md`
  (semantic commits, quality gates, Definition of Done). README `.env` table gains
  `KAOS_LLM_TIMEOUT` and `KAOS_SCHEDULER_INTERVAL`.
- Resume Agent: timestamp-aware transcripts. Discord message timestamps
  (ISO-8601) are threaded from the source (backfill + gateway) into the event
  payload and prefixed on each transcript line, so the summary references real
  dates instead of inventing them; the system prompt instructs the model to use
  those marks and not fabricate dates.
- Provider catalog (`src/kaos/core/providers.py`): descriptive, Core-agnostic
  metadata for every LLM provider (default model, endpoint, required credential)
  kept in sync with `config.LLM_PROVIDERS`. CLI `kaos providers` lists them and
  marks the active one and whether its credential is present (secrets never
  printed).
- Scheduler (Beta): `Scheduler` (`src/kaos/runtime/scheduler.py`) runs an
  idempotent async job on a fixed interval with injectable time (fully testable).
  CLI `kaos schedule [--interval N] [--once] [--dry-run] [--consolidated]
  [--force]` wraps `kaos run` so KAOS keeps its published knowledge up to date;
  because `run` publishes only on change, scheduled runs over unchanged forums
  are no-ops. Interval via `KAOS_SCHEDULER_INTERVAL` (default 900s).
- ADR-0009 — Scheduler & Provider Catalog.
- Kernel: public contracts in `src/kaos/contracts/` (Event, Context, Artifact,
  Agent, Connector, Publisher, Storage, LLMProvider, EventBus, Runtime).
- Runtime: concrete `KaosRuntime`, `InMemoryEventBus` and `InMemoryStorage` in
  `src/kaos/runtime/`.
- Resume Agent: first agent (`src/kaos/plugins/agents/`) that summarizes a
  conversation into an executive Markdown report via the `LLMProvider` contract.
- SDK: `EchoLLMProvider` testing double (`src/kaos/sdk/`).
- CLI: `kaos new [agent|connector|publisher] <name>` scaffolds a plugin and its
  test from `templates/` (KAOS dogfooding its own extensibility).
- Discord Connector: first connector (`src/kaos/plugins/connectors/`) that maps
  Discord messages to `message.created` events via a `DiscordMessageSource`
  abstraction (testable without a network connection).
- Runtime: minimal Context Engine — accumulates events per workspace and passes
  the whole conversation as Context; `conversation.completed` trigger event so
  conversation-level agents run once.
- CLI: `kaos up` runs a demo pipeline (Discord -> ResumeAgent -> Console).
- LLM: `OpenAICompatibleLLMProvider` (`src/kaos/plugins/providers/`) targeting
  any OpenAI-compatible endpoint, incl. GitHub Models (`github_models` factory).
- LLM: Claude support via the `anthropic` provider (Anthropic's OpenAI-compatible
  endpoint); `KAOS_LLM_PROVIDER=anthropic` + `KAOS_ANTHROPIC_API_KEY`, default
  model `claude-3-5-haiku-latest`.
- LLM: configurable request timeout (`KAOS_LLM_TIMEOUT`, default 120s) so slow
  reasoning models (e.g. gpt-5 via GitHub Models) don't hit the previous 30s
  `ReadTimeout`.
- Console Publisher (`src/kaos/plugins/publishers/`).
- Configuration: `Settings.from_env()` (`src/kaos/core/config.py`) and a
  composition root `build_runtime()` (`src/kaos/bootstrap/factory.py`); `kaos up`
  now honours `.env`. See `.env.example`.
- Real Discord: `DiscordGatewaySource` (discord.py, optional extra `.[discord]`)
  and `DiscordPublisher` + `DiscordRestPoster` (posts summaries to the
  "📋 Resume" thread).
- `DiscordWebhookPublisher`: publishes summaries via a Discord webhook (no bot
  token) into a specific thread (`KAOS_DISCORD_WEBHOOK_URL` /
  `KAOS_DISCORD_RESUME_THREAD_ID`).
- `DiscordBackfillSource`: reads a thread/channel history via the Discord REST
  API (paginated, chronological) and summarizes it once
  (`KAOS_DISCORD_BACKFILL_CHANNEL_ID` / `KAOS_DISCORD_MESSAGE_LIMIT`).
- CLI: `kaos backfill <channel_id> [--dry-run] [--limit N]`.
- CLI: `kaos backfill-forum <forum_channel_id> [--guild G] [--dry-run] [--limit N]`
  discovers every thread of a forum (active + archived) and summarizes each,
  labeled by thread name.
- Forum backfill: `--consolidated` merges every thread summary into a single
  `project.status` report ("📊 Estado del Proyecto"), published as one artifact
  that traces back to every source event across all threads.
- Summary cache (`src/kaos/core/cache.py`): read-through cache over the `Storage`
  contract keyed by thread + content fingerprint. `kaos backfill-forum` reuses a
  stored summary when a conversation hasn't changed (no LLM call) and persists
  evidence + summary otherwise; `--force` recomputes every thread. Durable across
  runs with `PostgresStorage`.
- Summary cache is model-aware: the LLM model is part of the cache identity
  (`model` metadata), so switching models (e.g. gpt-4o-mini -> gpt-5) recomputes
  instead of reusing another model's summary, keeping knowledge model-specific.
  `backfill-forum` prints per-thread progress (`· <thread>: resumiendo con <model>…`).
- Subscriptions: `Subscription` domain entity (`src/kaos/domain/`) and
  `SubscriptionStore` contract, with in-memory and PostgreSQL
  (`kaos_subscriptions`) backends. Config split: secrets stay in the environment,
  subscriptions persist in the DB (`KAOS_DATABASE_URL`).
- CLI: `kaos subscribe`, `kaos unsubscribe`, `kaos subscriptions`, and `kaos run`
  (summarize every active subscription, reusing the summary cache).
- Idempotent publishing: `kaos run` (and `backfill-forum --only-if-changed`)
  publishes only when at least one thread changed. Re-running with no new
  messages produces no new publication — the rule the scheduler follows.
- Config: automatic `.env` loading at the CLI entrypoint (`load_dotenv`).
- LLM provider: automatic retry/backoff on HTTP 429 rate limits.
- Forum backfill: detects empty message content (missing Message Content Intent)
  and skips the thread instead of wasting an LLM call.
- Discord publishers: split long summaries into several messages within Discord's
  2000-char limit (`chunk_message`).
- Security: secret redaction (`src/kaos/core/redaction.py`). The Resume Agent
  scrubs seed phrases, private keys, API tokens and labeled passwords from the
  transcript before it reaches the LLM provider and from the summary before it
  becomes a published artifact (Immutable Evidence keeps the raw event).
- Persistence: `PostgresStorage` (`src/kaos/plugins/storage/`, optional extra
  `.[postgres]`) wired via `KAOS_DATABASE_URL`; events and artifacts stored
  immutably in PostgreSQL (JSONB). Verified against the docker-compose container.
- ADR-0004 — CLI Scaffolding & Dogfooding.
- ADR-0005 — Conversation Context & LLM Provider.
- ADR-0006 — Configuration & Composition Root.
- Tests for the contracts, the runtime pipeline, the Resume Agent, the CLI
  scaffolding, the Discord Connector, the `kaos up` demo and the LLM provider
  (incl. end-to-end MVP pipeline).
- Bootstrap: validates Python >= 3.13, Git, Docker and uv; refuses to create a
  venv with an incompatible interpreter.
- README with initialization instructions.
- `docs/dev/KAOS-History.md`: foundational chat transcript.
- ADR-0003 — Kernel Contracts.
- Align docs with AGENTS.md: ADR-0001 principles, MinIO in docker-compose,
  dependencies and tooling (Ruff/MyPy/Pytest) in pyproject.toml.

## 1.0.0-alpha.1
- Foundation.
