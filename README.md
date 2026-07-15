# KAOS — Knowledge Analysis & Orchestration System

**v1.0.0-beta**

KAOS es una plataforma para transformar información no estructurada
(conversaciones, documentos, eventos y sistemas externos) en **conocimiento
organizacional estructurado, trazable y reutilizable** mediante agentes
especializados.

> El objetivo no es producir texto. El objetivo es construir conocimiento
> persistente. Los reportes, resúmenes y dashboards son solo vistas de ese
> conocimiento.

## Arquitectura

Capas desacopladas orientadas a eventos:

```
Connectors -> Event Bus -> Runtime / Core -> Agents -> Knowledge -> Publishers
```

- **Connectors** producen eventos (Discord es el primero).
- El **Runtime** orquesta la ejecución.
- Los **Agents** transforman contexto en conocimiento (Artifacts).
- Los **Publishers** exponen ese conocimiento.

El Kernel gira alrededor de contratos públicos estables en
`src/kaos/contracts/`. Ver `ARCHITECTURE.md` y los ADR en `docs/adr/`.

> 🚀 **¿Apurado?** Seguí la [Quick Start](docs/QUICKSTART.md) para arrancar en minutos.

## Requisitos

| Herramienta | Versión | Necesario para |
|-------------|---------|----------------|
| Python      | >= 3.13 | Ejecutar KAOS |
| [uv](https://docs.astral.sh/uv/) | reciente | Gestión del proyecto (recomendado) |
| Git         | cualquiera | Control de versiones |
| Docker      | reciente | Servicios (PostgreSQL, Redis, MinIO) |

## Inicialización

### 1. Clonar y verificar el entorno

```bash
git clone <repo-url> kaos
cd kaos
python bootstrap_kaos.py
```

`bootstrap_kaos.py` valida el entorno (Python >= 3.13, Git, Docker, uv) y te
indica los siguientes pasos. **No crea el entorno virtual si la versión de
Python es incompatible.**

Si no tienes Python 3.13, puedes instalarlo con uv:

```bash
uv python install 3.13
```

### 2. Instalar dependencias

Con **uv** (recomendado):

```bash
uv sync                 # crea el entorno e instala dependencias
uv pip install -e .     # instalación editable del paquete kaos
```

Sin uv (fallback con venv + pip):

```bash
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

python -m pip install -e .[dev]
```

### 3. Verificar la instalación

```bash
uv run kaos doctor      # o simplemente: kaos doctor
uv run kaos version
```

Salida esperada:

```
Environment OK (beta)
KAOS 1.0.0-beta.1
```

### 4. Levantar la infraestructura (opcional)

```bash
docker compose -f docker/docker-compose.yml up -d
```

Levanta PostgreSQL (5432), Redis (6379) y MinIO (9000 / consola 9001).

## Configuración (.env)

`kaos up` se arma desde variables de entorno. Copia `.env.example` a `.env` y
completa lo que necesites. **Todo es opcional**: `kaos up --offline` corre un
demo determinístico (conversación estática + salida por consola, sin
credenciales); `kaos up` a secas arranca el runtime según tu `.env`.

| Variable | Descripción |
|----------|-------------|
| `KAOS_LLM_PROVIDER` | `echo` (default), `openai`, `github`, `copilot`, `anthropic` u `ollama` |
| `KAOS_LLM_MODEL` | Modelo, p. ej. `gpt-4o-mini` o `claude-3-5-haiku-latest` |
| `KAOS_LLM_API_KEY` | API key para `openai` |
| `KAOS_LLM_BASE_URL` | Endpoint OpenAI-compatible (OpenAI, Azure, Ollama…) |
| `KAOS_LLM_TIMEOUT` | Timeout (s) por llamada al LLM; súbelo para modelos de razonamiento (default 120) |
| `KAOS_GITHUB_TOKEN` / `GITHUB_TOKEN` | Token para GitHub Models (`github`) |
| `KAOS_COPILOT_TOKEN` | Token de GitHub Copilot (`copilot`); obtenelo con `kaos copilot login` |
| `KAOS_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | API key para Claude (`anthropic`) |
| `KAOS_DISCORD_TOKEN` | Token del bot; si está, usa Discord real |
| `KAOS_DISCORD_GUILD_ID` | Guild a observar (workspace) |
| `KAOS_DISCORD_CHANNEL_IDS` | IDs de canales separados por coma (vacío = todos) |
| `KAOS_RESUME_THREAD_NAME` | Thread destino del resumen (default `📋 Resume`) |
| `KAOS_DISCORD_WEBHOOK_URL` | Webhook para publicar (solo escritura, sin bot token) |
| `KAOS_DISCORD_RESUME_THREAD_ID` | ID del thread destino del webhook (p. ej. "PMO") |
| `KAOS_DISCORD_BACKFILL_CHANNEL_ID` | Hilo/canal a leer por REST y resumir (backfill) |
| `KAOS_DISCORD_MESSAGE_LIMIT` | Máximo de mensajes históricos a leer (default 100) |
| `KAOS_DATABASE_URL` | DSN de PostgreSQL; si está, persiste eventos y artifacts |
| `KAOS_SCHEDULER_INTERVAL` | Segundos entre corridas de `kaos schedule` (default 900) |

Para usar Discord real instala el extra:

```bash
uv pip install -e .[discord]
```

Para persistencia en PostgreSQL:

```bash
uv pip install -e .[postgres]
docker compose -f docker/docker-compose.yml up -d postgres
# .env -> KAOS_DATABASE_URL=postgresql://kaos:kaos@localhost:5432/kaos
kaos up
```

## Desarrollo

### Crear un plugin

KAOS genera sus propios plugins (dogfooding) desde plantillas:

```bash
kaos new agent resume         # -> src/kaos/plugins/agents/resume_agent.py + test
kaos new connector discord    # -> src/kaos/plugins/connectors/discord_connector.py + test
kaos new publisher discord    # -> src/kaos/plugins/publishers/discord_publisher.py + test
```

Cada comando crea el plugin (implementando el contrato correspondiente) y su
prueba. No modifica el Core.

### Backfill de un hilo de Discord

Lee el historial de un canal/hilo por REST y lo resume (requiere
`KAOS_DISCORD_TOKEN` en `.env` y que el bot tenga acceso al canal):

```bash
kaos backfill <channel_id> --dry-run   # imprime el resumen en consola
kaos backfill <channel_id>             # publica según tu configuración (.env)
```

Resumir **todos los hilos de un foro** (el foro es el workspace):

```bash
kaos backfill-forum <forum_channel_id> --guild <guild_id> --dry-run
kaos backfill-forum <forum_channel_id> --guild <guild_id>
```

Por defecto publica un resumen por hilo. Con `--consolidated` los combina en un
**único informe** "📊 Estado del Proyecto" (una sola publicación):

```bash
kaos backfill-forum <forum_channel_id> --guild <guild_id> --consolidated --dry-run
```

Los resúmenes se **cachean** (por hilo + huella de contenido): volver a correr el
backfill no vuelve a consultar al LLM si la conversación no cambió. Con
`KAOS_DATABASE_URL` la cache persiste entre ejecuciones. Usa `--force` para
recomputar todos los hilos:

```bash
kaos backfill-forum <forum_channel_id> --guild <guild_id> --consolidated --force
```

### Suscripciones

En vez de repetir ids en cada corrida, **suscribí** los foros/canales que KAOS
debe gestionar. Las suscripciones persisten en la base de datos
(`KAOS_DATABASE_URL`); los secretos siguen en el entorno.

```bash
kaos subscribe <forum_channel_id> --guild <guild_id> --resume-thread <thread_id>
kaos subscribe <owner/repo> --github        # suscribir un repositorio de GitHub
kaos subscriptions          # listar activas
kaos unsubscribe <forum_channel_id>
```

Luego `kaos run` resume todas las suscripciones activas (reutilizando la cache):

```bash
kaos run --consolidated --dry-run   # previsualizar
kaos run --consolidated             # publicar en el resume-thread de cada una
```

### GitHub (dogfooding)

KAOS puede resumir la actividad de un repositorio (commits, issues, PRs) —
incluido el suyo propio. Requiere `KAOS_GITHUB_TOKEN` con acceso de lectura:

```bash
kaos github hectorhuergo/kaos --dry-run   # imprime el resumen por consola
kaos github <owner/repo>                  # publica según tu configuración
```

El repo también puede fijarse con `KAOS_GITHUB_REPO`.

### Proveedores LLM

Inspeccioná qué proveedores hay, cuál está activo y si tiene credencial (no se
imprimen secretos):

```bash
kaos providers
```

Seleccioná con `KAOS_LLM_PROVIDER=<echo|openai|github|copilot|anthropic|ollama>` y
`KAOS_LLM_MODEL=<modelo>`. Este es el default global; desde la consola web podés
además elegir proveedor + modelo **por corrida** (Chat, Vista previa, el modal de
Dashboards) y **por suscripción** (persistente: lo respetan el scheduler y
`kaos run`). El selector se puebla con los modelos que expone cada proveedor
(`GET /api/providers/{id}/models`); si no puede listarlos, queda un campo de texto.

Para **GitHub Copilot** (requiere suscripción) autenticá con el device flow:

```bash
kaos copilot login     # abrí la URL, ingresá el código; guarda el token
kaos copilot status    # verifica que el token pueda generar una sesión
```

Luego activá `KAOS_LLM_PROVIDER=copilot`.

### Scheduler (Beta)

`kaos schedule` corre `kaos run` periódicamente. Como `run` es idempotente
(publica solo si algún hilo cambió), correrlo de forma programada sobre foros sin
cambios no genera publicaciones nuevas:

```bash
kaos schedule --consolidated                 # cada KAOS_SCHEDULER_INTERVAL s (default 900), Ctrl-C para detener
kaos schedule --interval 300 --consolidated  # cada 5 min
kaos schedule --once --consolidated          # una sola pasada (para un cron externo)
```

### Conocimiento (Knowledge Graph & Dashboard)

El conocimiento acumulado (los `Artifact`s) se puede **consultar** como grafo.
Los workspaces se toman de `--workspace` o, si se omite, de las suscripciones
activas:

```bash
kaos knowledge                              # lista los artifacts de las suscripciones
kaos knowledge --workspace <forum_id>       # un workspace puntual (id o discord:<id>)
kaos knowledge --format mermaid --events    # grafo de trazabilidad (con eventos)
kaos knowledge --format json                # export JSON
```

Y generar un **dashboard HTML autocontenido** (resúmenes + grafo de
trazabilidad), sin servidor: se abre en el navegador.

```bash
kaos dashboard --workspace <forum_id> --out kaos-dashboard.html
```

O levantar el **dashboard vivo** (FastAPI): siempre refleja el estado actual,
con API JSON. Requiere el extra `.[dashboard]` (uvicorn):

```bash
uv pip install -e .[dashboard]
kaos serve --port 8000            # http://127.0.0.1:8000
```

Rutas: `/` (HTML), `/api/workspaces`, `/api/knowledge`, `/api/artifacts`
(todas aceptan `?workspace=<id>` y `?events=true`).

### Pruebas

```bash
uv run pytest
```

### Calidad

```bash
uv run ruff check .
uv run ruff format .
uv run mypy
```

## Estructura del repositorio

```
src/kaos/
    bootstrap/      # preparación del entorno
    cli/            # interfaz de línea de comandos (kaos ...)
    contracts/      # contratos públicos del Kernel
    core/           # núcleo agnóstico
    runtime/        # EventBus, Runtime y Storage concretos
    sdk/            # SDK para construir plugins
    domain/         # modelo de dominio y ontología
    plugins/        # agents, connectors y publishers
docker/             # docker-compose (PostgreSQL, Redis, MinIO)
docs/               # ADR, RFC y documentación de diseño
project/            # backlog, milestones y decisiones
tests/              # pruebas
```

## Documentación

- `AGENTS.md` — contexto mínimo para agentes (humanos o IA).
- `docs/QUICKSTART.md` — guía para arrancar en minutos.
- `docs/DEMO.md` — guion de demo + `scripts/demo.ps1` reproducible.
- `ARCHITECTURE.md` — visión de arquitectura.
- `ROADMAP.md` — hoja de ruta.
- `CONTRIBUTING.md` — guía de contribución.
- `docs/adr/` — Architecture Decision Records.
- `docs/rfc/` — Requests for Comments.
- `docs/dev/KAOS-History.md` — historia y decisiones fundacionales.

## Licencia

MIT — ver [`LICENSE`](LICENSE).
