# KAOS — Quick Start

Poné KAOS a andar en minutos. Hay dos caminos: el **demo offline** (sin
credenciales) y una **corrida real** contra Discord + un LLM.

---

## 0. Requisitos

- **Python ≥ 3.13** (obligatorio)
- [uv](https://docs.astral.sh/uv/) (recomendado) o `venv` + `pip`
- Docker (opcional, para PostgreSQL/Redis/MinIO)

```bash
git clone https://github.com/hectorhuergo/kaos.git
cd kaos
python bootstrap_kaos.py          # valida el entorno (Python 3.13, git, docker, uv)
```

## 1. Instalar

```bash
uv sync
uv pip install -e .               # paquete kaos
# extras opcionales:
uv pip install -e .[discord]      # bot/gateway de Discord
uv pip install -e .[postgres]     # persistencia PostgreSQL
uv pip install -e .[dashboard]    # dashboard vivo (uvicorn)
```

Verificá:

```bash
kaos doctor        # -> Environment OK (beta)
kaos version       # -> KAOS 1.0.0-beta.1
```

## 2. Demo offline (0 credenciales, ~1 min)

Sin `.env`, KAOS corre una conversación de ejemplo y publica el resumen por
consola:

```bash
kaos up --offline
```

Esto ejercita el pipeline completo **Connector → Agent → Publisher** con el
`EchoLLMProvider` (sin red, determinístico). `kaos up` a secas arranca el runtime
según tu `.env`.

## 3. Corrida real (Discord + LLM, ~5 min)

### 3.1 Configurar `.env`

```bash
cp .env.example .env
```

Completá lo mínimo para resumir con **GitHub Models** y publicar en Discord:

```dotenv
KAOS_LLM_PROVIDER=github
KAOS_LLM_MODEL=gpt-4o-mini
KAOS_GITHUB_TOKEN=<token con permiso 'Models'>

KAOS_DISCORD_TOKEN=<token del bot>
KAOS_DISCORD_RESUME_THREAD_ID=<id del hilo donde publicar>
```

Comprobá qué proveedor quedó activo (no imprime secretos):

```bash
kaos providers
```

### 3.2 Resumir un foro

```bash
# previsualizar (no publica): imprime el resumen por consola
kaos backfill-forum <forum_id> --guild <guild_id> --consolidated --dry-run

# publicar el consolidado "📊 Estado del Proyecto" en el resume-thread
kaos backfill-forum <forum_id> --guild <guild_id> --consolidated
```

Los resúmenes se **cachean** (por hilo + contenido + modelo): re-correr no vuelve
a llamar al LLM si nada cambió. Con `KAOS_DATABASE_URL` la cache persiste.

### 3.3 Persistir en PostgreSQL (opcional)

```bash
docker compose -f docker/docker-compose.yml up -d postgres
# .env -> KAOS_DATABASE_URL=postgresql://kaos:kaos@localhost:5432/kaos
```

### 3.4 Resumir un repo de GitHub (dogfooding)

```bash
kaos github hectorhuergo/kaos --dry-run   # resume commits/issues/PRs por consola
kaos github <owner/repo>                  # publica según tu configuración
```

## 4. Automatizar con suscripciones + scheduler

```bash
kaos subscribe <forum_id> --guild <guild_id> --resume-thread <thread_id>
kaos subscriptions                       # listar
kaos run --consolidated                  # resume todo lo suscripto (idempotente)
kaos schedule --consolidated             # lo mismo, en bucle (cada 900s)
```

`run`/`schedule` publican **solo si hubo cambios**.

## 5. Ver el conocimiento

```bash
kaos knowledge --workspace <forum_id>              # lista de artifacts
kaos knowledge --workspace <forum_id> --format mermaid   # grafo
kaos dashboard --workspace <forum_id>              # HTML autocontenido
kaos serve --port 8000                             # dashboard vivo (FastAPI)
```

Dashboard vivo en `http://127.0.0.1:8000` (rutas: `/`, `/api/knowledge`,
`/api/artifacts`, `/api/workspaces`).

## 6. Crear un plugin (dogfooding)

```bash
kaos new agent mi-agente
kaos new connector mi-conector
kaos new publisher mi-publisher
```

Genera el plugin (implementando su contrato) + su test, sin tocar el Core.

---

## Troubleshooting rápido

| Síntoma | Causa / arreglo |
|---------|-----------------|
| `requires a different Python: 3.13` | Instalá Python 3.13 (`uv python install 3.13`). |
| `The 'models' permission is required` | El token de GitHub necesita permiso **Models: read**. |
| Mensajes con `len=0` en backfill | Activá **Message Content Intent** en el Developer Portal del bot. |
| `403 Missing Access` | El bot no está en el server / sin acceso al canal. Invitalo. |
| `429` (rate limit) | GitHub Models limita ~2 req/min; KAOS reintenta solo. |
| Modelo lento (razonamiento) | Subí `KAOS_LLM_TIMEOUT` (p. ej. 240). |
| `falta 'uvicorn'` en `kaos serve` | `uv pip install -e .[dashboard]`. |

## Siguiente paso

- Arquitectura: [`ARCHITECTURE.md`](../ARCHITECTURE.md)
- Decisiones: [`docs/adr/`](adr/)
- Contribuir: [`CONTRIBUTING.md`](../CONTRIBUTING.md)

