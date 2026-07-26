# Changelog

## Unreleased
- GitHub run — dynamic designated agent (normalized with the forum path): the
  single-workspace GitHub run (`kaos github` / `POST /api/run/subscription`) now
  **honors the agent selected per-run or per-subscription** instead of always
  behaving as the resume-agent and merely stamping the id. The resume-agent
  always produces the **chunk-aware reduced summary** of the activity (so it fits
  the model's context window); the default run publishes that summary, while a
  designated **task/dev agent synthesizes the final report from that compact
  summary** — never from the oversized raw activity, so it can't overflow the
  context. Reuses the shared `consolidate_sections` dispatcher (renamed from
  `_consolidate_sections`); one report per run is persisted and attributed to the
  producing agent (`produced_by`/`metadata.agent_id`), carrying the summary's
  transcript and `source_events` for traceability.
- LLM provider — strict-template compatibility: consecutive same-role messages are
  now **folded into a single block** before the request is sent
  (`_consolidate_roles`). Strict chat templates (e.g. CodeGemma's Jinja template)
  `raise_exception` when roles don't strictly alternate `user`/`assistant`, and
  KAOS' prompt-chunking and tool-use paths legitimately emit several consecutive
  `user` (or `assistant`) messages — which those backends rejected with a 500
  (*"Conversation roles must alternate…"*). Folding runs of the same role keeps the
  sequence perfectly alternating while preserving all content (blocks joined with a
  blank line); providers that don't care about alternation see identical text. The
  normalization applies to both the OpenAI-compatible path and Ollama's native
  `/api/chat` path.
- Traceability graph — clickable workspace nodes: a **workspace/subscription node**
  (e.g. `proyecto-x`, `JoseValperga/proyecto-x-grid`) now **links to its cards
  section** instead of leading nowhere. Each dashboard `<section>` gets a safe
  `id="ws-<slug>"` anchor and every graph node is wired via a new explicit
  `KnowledgeGraph.to_mermaid(anchors=…)` map (node.id → href): artifacts →
  `#node-<id>` (revealed on demand via card pagination), workspaces →
  `#ws-<slug>` (always present server-side). `click_prefix` is kept for backward
  compatibility; `anchors` takes precedence when both are given.
- Console «Más opciones» polish: the read-only thread **metadata now renders as
  inline chips** (flex-wrap) instead of a one-pair-per-row grid, and opening a
  session **loads its title into the Título field** (it stayed blank before even
  when the thread had a title). Node → card navigation in the dashboard graph is
  already robust: clicking a node not yet in view pulls card pages on demand until
  the target loads, then scrolls to it.
- Translate Agent: a new `translate-agent` localizes Gettext `.pot` files into
  Spanish `.po`, producing a `translation.artifact`. It reads the source through
  the injected `file_read` tool (KAOS `Tool` contract, `run(args)`), so it stays
  storage-agnostic and testable. Registered in the agent catalog (visible in the
  console) with its base prompt wired for prompt augmentation. Batch scripts
  `scripts/translate_file.py` (single file, safe 40-entry segmentation) and
  `scripts/translate_all.py` (whole folder) drive the real pipeline, loading the
  `.env` via `load_dotenv()` + `Settings.from_env()` so `KAOS_LLM_NUM_CTX` is
  honored.
- Dashboard cards pagination: a workspace's artifact cards now render the first
  page server-side and **lazily load the rest as you scroll down** (a downward
  infinite scroll, the reverse of the chat's upward one), via a new
  `/api/dashboard/cards?workspace=&offset=&limit=` endpoint that returns the
  **same server-rendered card markup** (version carousel + `#node-<id>` anchors).
  Node → card links keep working: navigating to a not-yet-loaded card's anchor
  pulls pages until it appears, then scrolls to it. New pure helper
  `kaos.plugins.dashboard.render_cards_page`.
- Traceability graph UX: the dashboard graph now renders nodes at a **natural,
  constant size and scrolls** when the diagram is larger than the viewport
  (Mermaid `useMaxWidth: false`), instead of squeezing many nodes into the
  container (unreadable) or blowing up a few to fill it. Label sizes are
  **responsive** (14/12/11px across lg/md/xs). Each artifact **node links to its
  card**: clicking a node jumps to `#node-<id>` (highlighted via `.card:target`),
  wired through a new `KnowledgeGraph.to_mermaid(click_prefix=…)` (default output
  unchanged). Card pagination / on-demand loading of events & older versions is
  the next step.
- Chat context (scoped): a chat turn can now include knowledge **beyond the
  current thread** (ADR-0025). A new "Contexto" selector in the console's «Más
  opciones» chooses the scope — Ninguno / Proyecto / Workspace / Relaciones —
  sent as `context_scope`. `send_message` builds a grounding block from the most
  recent artifact summaries across the scoped workspaces (project via the
  ADR-0019 grouping, relations via the knowledge graph), packed newest-first up
  to `KAOS_CHAT_CONTEXT_TOKENS` (`Settings.chat_context_tokens`, default 2000),
  excluding the live session's own turns. Default `none` keeps the historical
  thread-only behaviour (backward compatible). New helper
  `kaos.plugins.dashboard.chat.gather_context`.
- Console chat UX: chat thread headers are **normalized** to match the artifact
  run headers (agent · N msg · 🤖 model · date), and «Más opciones» now shows a
  read-only **metadata** panel with every field of the active thread (session,
  agent, model, workspace, project, kind, user, messages/turns/artifacts,
  created/updated).
- Consolidated forum reports: running a forum subscription now produces a **single
  unified executive report** instead of N per-thread summaries stacked under
  headers. The **designated agent** (`agent_id` from the subscription/console run)
  consolidates: the resume-agent reduces the summaries, the task-agent runs its
  dated consolidation prompt, and a tool-using agent (dev-agent) runs its loop
  over them; the report is attributed to that agent (`produced_by`/`agent_id`) and
  saved to the designated thread (PMO / per-subscription `resume_thread_id`). It
  reuses the ADR-0024 map-reduce (respecting the agent's structured prompt +
  `extra_instructions`); with a small `KAOS_LLM_NUM_CTX` the reduce is
  hierarchical so it fits; if the synthesis is empty it falls back to the previous
  labeled concatenation. Traceability is preserved (every source event and the
  aggregated message/thread counts).
- LLM errors: a request timeout now surfaces an explicit reason instead of a bare
  `No se pudo contactar a ollama:` (httpx timeouts stringify empty). The message
  names the timeout, the configured limit and hints at `KAOS_LLM_TIMEOUT` — the
  common cause being slow local CPU inference.
- Summaries: the `resume-agent` now summarizes oversized conversations via
  **map-reduce** (ADR-0024) instead of sending one huge prompt. When the model's
  context window (`KAOS_LLM_NUM_CTX` → `ResumeAgent(context_tokens=…)`) is known
  and a conversation would overflow it, the transcript is split into ordered
  chunks, each condensed into notes (*map*), and the notes synthesized into a
  single coherent report (*reduce*, hierarchical if still too big). This keeps
  the required Markdown structure intact — unlike concatenating partial summaries
  — and works on servers with a small, fixed context window (Lemonade/llama.cpp)
  that ignore a per-request `num_ctx`. New pure helper `kaos.core.chunking`
  (`estimate_tokens`, `group_by_token_budget`); traceability (source events,
  message count) is preserved. With no known context window the behaviour stays
  single-shot (backward compatible). `KAOS_LLM_NUM_CTX` now means "the model's
  real context window in tokens": raise it for real Ollama, set it to the loaded
  value for Lemonade/llama.cpp so the agent chunks to fit.
- LLM: configurable context window for local providers (`KAOS_LLM_NUM_CTX`,
  `Settings.llm_num_ctx`). Ollama's OpenAI-compatible endpoint ignores
  `num_ctx`, so when it is set for the `ollama` provider KAOS now calls Ollama's
  **native** `/api/chat` API with `options.num_ctx`, raising the small default
  context (4k) — fixing `exceeds available context size` on long conversations
  without any prompt chunking (which would degrade summaries). Omitted by
  default, so hosted providers are unaffected (backward compatible). The
  `scripts/translate_all.py` pipeline now loads `.env` and reads `Settings.from_env()`
  so it honours the same configuration.
- LLM: raised the default request timeout to 300s (`KAOS_LLM_TIMEOUT`) so slower
  reasoning/large models have room to answer before timing out.
- LLM errors: providers now raise a clear `LLMError` (new, in `kaos.contracts.llm`)
  carrying the provider's own reason, the model and the upstream status, instead of a
  raw `httpx.HTTPStatusError`. `OpenAICompatibleLLMProvider.complete` parses the error
  body (OpenAI-style `{"error": {"code","message"}}`) and wraps transport failures too.
  The chat endpoint maps it to the upstream 4xx (or 502) with the message as `detail`,
  and the console shows a "⚠ No se pudo generar la respuesta" bubble with the reason
  (dropping the pending spinner). Fixes the opaque `500` when picking a model the GitHub
  Models legacy host *lists* but its inference endpoint rejects (e.g. Meta-Llama →
  `400 unknown_model`).
- PostgreSQL: fixed a **schema-init deadlock** on concurrent first use. Each store's
  `_ensure_pool` was unguarded, so two requests arriving together (the console loads
  several panels at once) both created a pool and ran the schema DDL on separate
  connections, deadlocking on `AccessExclusiveLock` (and leaking a pool) — a 500 that
  surfaced mainly with slower providers like GitHub Models, whose network latency widens
  the race window. Initialization is now serialized with an `asyncio.Lock`
  (double-checked, publishing the pool only after the schema is applied), and the DDL is
  wrapped in a short deadlock retry (`_apply_schema`) to also cover multi-instance races
  (e.g. API server + scheduler starting together). Applies to storage, subscriptions,
  runtime-config and credential stores.
- Chat: **cancelar** una generación en curso. `POST /api/chat/send` corre como una
  tarea rastreada por `(workspace, session_id)` en un `ChatSessionManager`; cancelarla
  propaga por `await llm.complete(...)` y aborta la request HTTP al proveedor (devuelve
  `499`). Nuevo `POST /api/chat/cancel`. La consola genera el `session_id` en el cliente
  (así se puede cancelar incluso el primer turno), muestra un botón **⏹ Cancelar**
  mientras genera y renderiza "generación cancelada" en vez de un error.
- Chat: **previsualización de Markdown** en las burbujas del asistente vía `markdown-it`
  + `DOMPurify` cargados por CDN (mismo patrón que Mermaid en el dashboard), con
  degradación a texto plano escapado cuando no hay red. Estilos para código, listas,
  tablas, citas y encabezados dentro de la burbuja.
- GitHub Models: corregido el listado de modelos (`OpenAICompatibleLLMProvider.list_models`).
  El endpoint `GET https://models.inference.ai.azure.com/models` devuelve `id` como URI de
  recurso `azureml://…/models/<name>/versions/<n>`; el parser anterior tomaba el último
  segmento y exponía el **número de versión** (1, 2, 3). Ahora usa el campo `name` cuando el
  `id` es un URI y filtra los modelos que no son de chat (embeddings) del selector; los `id`
  planos de OpenAI/Ollama quedan intactos.
- Per-subscription agent selection: choose which agent processes a subscription in
  **Ejecutar** (per-run override) and **Suscripciones** (persistent, so the scheduler
  and `kaos run` honor it), plus **Vista previa**. `Subscription` gains a nullable
  `agent_id` (Postgres `ADD COLUMN IF NOT EXISTS`; `None` → the default `resume-agent`).
  Threaded through `run_backfill`, `run_forum_backfill`, `run_github`,
  `preview_subscription` and `run_subscription` (the latter two defaulting to the
  subscription's stored agent; an explicit `agent_id` wins per run). The selected
  agent drives which persisted extra-instructions augment the summary and is stamped
  on the artifact's `metadata["agent_id"]` (which dashboards/metrics already consume)
  without changing `produced_by` or the summary structure — a forward-compatible base
  for future multi-agent orchestration. API bodies accept optional `agent_id`; console
  adds a reusable agent selector in Subscriptions, Vista previa and the Ejecutar modal,
  and a 🧠 pill on subscription cards. ADR-0023.
- Console UX: removed the redundant top header bar and the Chat section's
  heading/description to free vertical space. Subscriptions `PATCH`/`DELETE` routes now
  use a `:path` converter so GitHub `owner/repo` ids (encoded `%2F`) route correctly
  (was 404). The Dashboards "Ejecutar" publish lookup uses `getElementById` so a `/` in
  a GitHub channel id no longer breaks the CSS selector. Providers "Modelo" field is now
  the reusable model selector (turns into a `<select>` when the provider lists models).
- Per-run provider & model selection: choose the LLM `provider` + `model` per run
  wherever KAOS produces knowledge. `load_settings(base, *, provider=, model=)`
  takes an explicit override that wins over the persisted config and drives which
  provider's credential is resolved (a provider switch without a model drops the
  other provider's persisted model so it can't leak); threaded through
  `run_backfill`, `run_forum_backfill`, `run_github`, `send_message`,
  `preview_subscription` and `run_subscription`. `Subscription` gains persistent
  `llm_provider`/`llm_model` (nullable; Postgres `ADD COLUMN IF NOT EXISTS`) so the
  scheduler and `kaos run` honor it too. New best-effort model listing
  (`OpenAICompatibleLLMProvider.list_models`, `factory.list_models`, `GET
  /api/providers/{id}/models`) — `[]` on any failure. Run/preview/chat/subscription
  API bodies accept optional `llm_provider`/`llm_model`. Console: a reusable
  provider+model selector (`<select>` when models can be listed, free-text input
  otherwise) in Subscriptions, Chat "Más opciones" and Vista previa, plus a new
  editable Dashboards **confirm modal** (provider/model + Publicar) replacing the
  `confirm()`. ADR-0022.
- GitHub Copilot provider (`copilot`): a new `LLMProvider` backed by the GitHub
  Copilot API (`https://api.githubcopilot.com`), distinct from GitHub Models.
  Auth is a two-step chain: a long-lived GitHub OAuth token (`gho_…`) obtained via
  the **device flow** (`kaos copilot login` — autologin, no manual PAT) is
  exchanged at request time for a short-lived Copilot session token
  (`copilot_internal/v2/token`), cached until shortly before it expires and sent
  with the editor headers Copilot requires. `CopilotLLMProvider` extends
  `OpenAICompatibleLLMProvider` via two additive hooks (`extra_headers` and an
  async `_auth_token()`), reusing the request + rate-limit retry logic. New
  `KAOS_COPILOT_TOKEN` setting, catalog entry, `build_llm` branch, and
  `kaos copilot login|status` CLI. Persists the token in the credential store
  (or prints it for `.env`). Console: item reorder — nav is now Dashboards,
  Subscriptions, Vista previa, Chat · Configuración (Agentes, Providers), landing
  on Dashboards; chat history interleaves each summary run chronologically
  instead of collapsing versions into one row; Dashboards drops the costly
  "Previsualizar" for a per-row **Publicar** checkbox (reflecting the
  subscription's default) and a `confirm()` before Ejecutar. Fixed: an explicit
  model chosen in the console now wins over a credential's stored model
  (`load_settings`). ADR-0021.
- Chat over knowledge & artifact threads: the console chat is no longer a silo —
  it enriches and reuses the same knowledge (artifacts + events). `POST
  /api/chat/send` accepts `about_artifact` to anchor a chat on **any** stored
  artifact; the sidebar lists all knowledge with a simple search, friendly titles
  (`artifact_friendly_title`) and last-activity dates (`artifact_last_activity`).
  Human chat messages become synthetic `message.contribution` events
  (`load_contributions`) that `ResumeAgent` folds into the next summary (with
  `contribution_id` in the cache fingerprint). Tool-using agents (Dev Agent) run a
  tool loop from the chat. `ResumeAgent` now embeds the originating transcript in
  the artifact (`content["messages"]`, redacted), so the thread is self-contained
  across connectors and re-runs. New `GET /api/artifacts/thread` returns that
  thread paginated backwards (infinite scroll), with a fallback to `source_events`
  then workspace `message.*` for pre-existing artifacts. The chat knowledge list
  groups artifacts by logical subject (`workspace + kind + thread_name`, same key
  as the dashboard) so a thread's many summary versions collapse into one entry,
  navigable with **◀/▶** version arrows (each reconstructing its full thread);
  list ordered newest-first, thread opens pinned to the latest message. Console: provider/model
  **catalog** pills moved next to "Nueva sesión" and reflect the selection;
  metrics split into plain stats (Assets/Artefactos/Última ejecución/Sesiones/
  Mensajes) vs. Agentes/Modelos pills; nav regrouped (Chat/Subscriptions/
  Dashboards/Vista previa top-level, Providers+Agentes under **Configuración**),
  global collapsible sidebar. ADR-0020.
- Knowledge graph — Cross-Workspace Relations (project graph): workspaces are no
  longer isolated islands. A new `related_to` edge connects workspaces of the same
  project via three deterministic (no-LLM) signals in
  `kaos.core.knowledge.relate_workspaces(labels, *, projects=None, relations=None)`:
  (1) an explicit **`project`** grouping on subscriptions (so `kaos`, the *brain*
  of `proyecto-x`, joins the project despite its unrelated name), (2) ad-hoc
  **`related_to`** links an operator sets per subscription, and (3) a name-prefix
  heuristic (`proyecto-x` ↔ `proyecto-x-grid`). Graph nodes now render friendly
  workspace names (`KnowledgeGraph.relabel`) instead of the raw `discord:<id>`.
  Applied on the live dashboard (`GET /`, `/api/knowledge`) and the CLI
  (`kaos knowledge`/`dashboard`). ADR-0019.
- Subscriptions — project, relations & publish default: `Subscription` gains
  `project`, `related_to` (workspace list) and `publish_default` (persisted;
  `text`/`text[]`/`boolean` columns with `ADD COLUMN IF NOT EXISTS` migrations).
  `publish_default` (default `true`) gates whether an **automated** run (scheduler
  / `kaos run`) posts to Discord — off keeps a subscription *knowledge-only*
  (still summarized and persisted). Editable via `kaos subscribe … --project …
  --related … [--no-publish]`, the console form, inline **"Editar"** per card, and
  a new **`PATCH /api/subscriptions/{channel_id}`** partial-update route.
- Fix — subscription resume thread vs `.env`: the console run path
  (`dashboard.execute.run_subscription`) now honors each subscription's
  `resume_thread_id` over the global `KAOS_DISCORD_RESUME_THREAD_ID`, matching the
  CLI `run_subscriptions` precedence.
- Fix — GitHub Models credential detection in the console: the providers panel
  used the *selected*-provider flag to decide "credencial en .env", so a
  `KAOS_GITHUB_TOKEN` present in the environment showed as "sin credencial" when
  another provider was active. `GET /api/providers` now exposes a correct
  `env_ready` flag and the console reads it.
- Console — run & publish + "run all": the run action gains a **publish** toggle
  (route `POST /api/run/subscription` accepts `publish`; a `_TeePublisher`
  publishes to Discord *and* captures for display) and a new **`POST /api/run/all`**
  runs every active subscription. Persisting + cache-warming stays the default;
  publishing is opt-in. ADR-0017.
- Scheduler — per-subscription execution plan: `Subscription.interval_seconds`
  (persisted; `NULL`/`None` = every pass) sets how often the scheduler runs each
  subscription. `kaos schedule` now ticks at a base cadence and runs only the
  **due** subscriptions (pure `due_subscriptions`), tracking last-run per process;
  `run_subscriptions(only=…)` filters by channel. Set it with
  `kaos subscribe … --every SECONDS` or the console's "Plan" field. ADR-0016.
- Console — per-agent prompt augmentation: the "Agentes" tab now shows a prompt
  field **per augmentable agent** (by id); the summary pipeline consumes the
  resume-agent's. ADR-0017.
- Web console — interactive run (persist + cache): the "Vista previa" tab gains
  an **"Ejecutar"** action (route `POST /api/run/subscription`) that runs the
  real pipeline for a subscription so it **stores the summaries and populates the
  summary cache** — just like a scheduled `kaos run` — but with a
  `CapturingPublisher` so **nothing is posted to Discord** (publishing stays a
  deliberate CLI/scheduler step). Optional `force` re-summarizes ignoring the
  cache. New `kaos.plugins.dashboard.execute.run_subscription`. Preview stays a
  non-persisting dry-run.
- Web console — Agents view + prompt augmentation: new "Agentes" tab lists the
  agents KAOS ships (from a read-only catalog `kaos.core.agents`, exposed at
  `GET /api/agents`) and offers an "instrucciones extra" field that augments the
  Resume Agent's prompt (focus/tone) without changing its required structure.
  `ResumeAgent(llm, extra_instructions=...)` appends the guidance to the base
  system prompt; `extra_instructions` is threaded through `run_backfill`,
  `run_forum_backfill`, `run_github` and both preview routes
  (`POST /api/preview/{github,subscription}`).
- Subscriptions — decoupled dispatch: `run_subscriptions` now resolves the runner
  from a `SUBSCRIPTION_RUNNERS` registry (kind → handler) instead of an
  `if/elif` chain, so a new source kind only adds its runner. This keeps the
  subscription loop agnostic of the concrete connector behind each kind.
- Scheduler as an app: `docker/Dockerfile` (installs `kaos`) plus opt-in
  `scheduler` and `dashboard` services in `docker-compose.yml` (profile `app`,
  `docker compose --profile app up -d --build`). The default `up` still starts
  infra only. The scheduler runs `kaos schedule` (periodic, idempotent `kaos
  run`); it reads subscriptions from the store — it is a process, not a separate
  datastore.
- GitHub repo subscriptions: `kaos subscribe <owner/repo> --github` persists a
  subscription whose `kind` is `github` and whose `channel_id` is the repo slug
  (workspace `github:owner/name`). `kaos run`/`kaos schedule` and the web-console
  preview (`POST /api/preview/subscription`) now dispatch `github` subscriptions
  to `run_github`, alongside the existing forum/channel Discord flows. New domain
  helpers `Subscription.workspace_for_github` / `workspace_for_kind`; the console
  "Nueva suscripción" form gains a `github` option. (The general Git reader —
  Maxi's work — will be integrated next; see ROADMAP.)
- Knowledge graph deduplication: `build_graph(..., dedupe=True)` keeps only the
  most recent artifact per logical subject (its `thread_name`, else its `kind`),
  so re-summarizing the same conversation with a different model/run no longer
  shows the same knowledge duplicated once per model. The dashboard, instead of
  hiding the older versions, **groups them into a single navigable card**: when a
  node has more than one artifact, arrows switch between versions and the header
  shows the model and date of each (`group_artifacts`). `GET /api/artifacts`
  returns every version; the graph stays one node per subject.
- Dev Agent (first active teammate): a tool-using agent (ADR-0014) that works on
  the local repo. New `Tool` contract (`src/kaos/contracts/tool.py`) and a
  confined dev toolbox (`src/kaos/plugins/tools/dev_tools.py`): `ReadFileTool`,
  `ListDirTool`, `SearchCodeTool`, `RunCommandTool` — paths confined to the repo
  root and commands restricted to a read-only allowlist (pytest, ruff, mypy,
  git status|diff|log|show), run without a shell and with a timeout. `DevAgent`
  (`src/kaos/plugins/agents/dev_agent.py`) runs a bounded JSON tool-use loop
  (provider-agnostic, works with local Ollama models) and emits a traceable
  `dev.session` artifact (task, per-step tool+args+observation, final answer,
  dashboard-friendly summary). CLI `kaos dev "<task>" [--repo-root .]
  [--max-steps N] [--dry-run]`. Tiny models follow the protocol unreliably; a
  stronger instruct model (e.g. qwen2.5:7b) is recommended for real use.
- Web console dry-run preview: a "Vista previa" tab summarizes a subscription
  (forum consolidated / channel) or a GitHub repo and shows the result **without
  publishing to Discord** — even with a real Discord token in the environment.
  New `CapturingPublisher` (`src/kaos/plugins/publishers/`) collects artifacts
  instead of sending them; `run_backfill`/`run_forum_backfill`/`run_github` gain
  an optional `publisher` argument so the pipeline is reused unchanged. Routes
  `POST /api/preview/subscription` and `POST /api/preview/github` (both return
  `published: false`). Reading the source still happens; only publishing is
  suppressed. ADR-0013.
- Local LLM (dogfooding): `ollama` provider — a local, zero-cost,
  OpenAI-compatible backend served by Ollama in Docker (`docker/docker-compose.yml`
  `ollama` service, port 11434). `OpenAICompatibleLLMProvider.ollama()` needs no
  secret; default model `llama3.2:3b` (override with `KAOS_LLM_MODEL`, endpoint
  with `KAOS_LLM_BASE_URL`). Added to `LLM_PROVIDERS`, the provider catalog
  (always ready, no credential) and `build_llm`. Ideal for iterating on the
  upcoming agents offline. See QUICKSTART.
- Web console: an admin surface on the same FastAPI app (`GET /console`,
  `src/kaos/plugins/dashboard/console.py`) — a self-contained HTML page (vanilla
  JS, no build step) to manage the active LLM provider/model, **provider
  credentials**, subscriptions (add + deactivate) and browse the per-workspace
  dashboards. JSON routes: `GET /api/providers`, `PUT /api/config/provider`,
  `PUT/DELETE /api/providers/{id}/credential`, `GET/POST /api/subscriptions` and
  `DELETE /api/subscriptions/{channel_id}`. `kaos serve` also prints the console
  URL. ADR-0013.
- Persisted runtime config & credentials: `RuntimeConfig` +
  `ProviderCredential` domain entities and the `ConfigStore` + `CredentialStore`
  contracts, with in-memory and PostgreSQL (`kaos_runtime_config`,
  `kaos_provider_credentials`) backends selected by `build_config_store` /
  `build_credential_store`. The active LLM provider/model and each provider's
  **secret** can be persisted in PostgreSQL; `factory.load_settings()` overlays
  both onto the environment `Settings` so knowledge-producing commands
  (`backfill`, `backfill-forum`, `github`, and therefore `run`/`schedule`) honour
  them on the next run. The environment (`.env`) is the fallback; secrets are
  write-only over the API (never returned). Flexes the Config Split (ADR-0008).
- Demo: `docs/DEMO.md` (guion para presentar KAOS) + `scripts/demo.ps1` (demo
  reproducible en Windows que espera a Postgres por healthcheck y usa
  `python -m kaos.cli.main` cuando no existe el ejecutable `kaos`).
- CLI: `kaos up --offline` corre el demo determinístico (StaticDiscordSource +
  EchoLLMProvider + ConsolePublisher), ignorando `.env` — antes `kaos up`
  intentaba el gateway real si había `KAOS_DISCORD_TOKEN`.
- docker-compose: nombre de proyecto `kaos` (contenedor `kaos-postgres-1`, antes
  `docker-postgres-1`) y **healthcheck** de Postgres (`docker compose up -d
  --wait postgres` espera a que esté listo — sin reintentos).
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
