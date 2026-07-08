# KAOS — Guion de Demo

Demo reproducible para presentar KAOS al equipo (~10 min). Hay un **script
automatizado** (`scripts/demo.ps1`) y la **versión manual** paso a paso.

> **Windows:** si el paquete no está instalado (venv que no es Python 3.13), no
> existe el ejecutable `kaos`. Usá `python -m kaos.cli.main ...` con
> `PYTHONPATH=src`. El script `demo.ps1` lo resuelve solo.

---

## Opción A — Script automatizado

```powershell
# desde la raíz del repo
.\scripts\demo.ps1            # guiada (pausa en cada paso)
.\scripts\demo.ps1 -NoPause   # sin pausas
.\scripts\demo.ps1 -Offline   # solo lo que no requiere credenciales
```

El script:
- resuelve el `python` del `.venv` y usa `kaos` si está instalado, si no
  `python -m kaos.cli.main`;
- **espera a que Postgres esté listo** (healthcheck) antes de usar la base — sin
  reintentos manuales;
- corre todo en orden y limpia al final (`docker compose down -v`).

Parámetros útiles: `-Repo owner/repo`, `-ForumId <id>`, `-GuildId <id>`,
`-KeepUp` (no baja Postgres).

---

## Opción B — Manual, paso a paso

Preparación (una vez):

```powershell
# venv + dependencias (si aún no)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pydantic httpx asyncpg fastapi uvicorn
$env:PYTHONPATH = 'src'
# atajo para esta sesión:
function kaos { & .\.venv\Scripts\python.exe -m kaos.cli.main @args }
```

> Con el paquete instalado (`uv pip install -e .` en Python 3.13) el atajo no
> hace falta: usás `kaos ...` directamente.

### 1. Entorno

```powershell
kaos doctor      # Environment OK (beta)
kaos version     # KAOS 1.0.0-beta.1
```

**Decir:** KAOS es una plataforma orientada a eventos; el objetivo no es producir
texto sino **conocimiento persistente, trazable y reutilizable**.

### 2. Proveedores LLM

```powershell
kaos providers
```

**Decir:** *AI Provider Agnostic* — echo/openai/github/anthropic. Marca el activo
y si tiene credencial (nunca imprime secretos).

### 3. Demo offline (0 credenciales)

```powershell
kaos up --offline
```

**Decir:** ejercita el pipeline completo **Connector → Agent → Publisher** con el
`EchoLLMProvider`, sin red ni credenciales. `--offline` es determinístico
(ignora `.env`); `kaos up` a secas arranca el runtime según tu configuración.

### 4. Dogfooding — KAOS se resume a sí mismo

```powershell
$env:KAOS_LLM_PROVIDER = 'github'; $env:KAOS_LLM_MODEL = 'gpt-4o-mini'
kaos github hectorhuergo/kaos --dry-run --limit 20
```

**Decir:** el **GitHub Connector** lee commits/issues/PRs y el Resume Agent los
convierte en un "Estado del Proyecto". KAOS narra su propio desarrollo.

### 5. Run real de Discord (foro)

```powershell
docker compose -f docker/docker-compose.yml up -d --wait postgres
$env:KAOS_DATABASE_URL = 'postgresql://kaos:kaos@localhost:5432/kaos'
kaos backfill-forum <forum_id> --guild <guild_id> --consolidated --dry-run
```

**Decir:** un foro = un workspace; consolida los hilos en **📊 Estado del
Proyecto**, con fechas reales y **secretos redactados**. Los resúmenes se
**cachean** (por hilo + contenido + modelo): re-correr no vuelve a llamar al LLM.

### 6. Ver el conocimiento

```powershell
kaos knowledge --workspace <forum_id>                 # lista
kaos knowledge --workspace <forum_id> --format mermaid  # grafo
kaos dashboard --workspace <forum_id> --out kaos-dashboard.html
kaos serve --port 8000    # dashboard vivo (FastAPI), http://127.0.0.1:8000
```

**Decir:** *Knowledge before Reports* — el grafo y el dashboard son **vistas**
sobre el conocimiento. El dashboard vivo lee el estado actual y expone una API
JSON (`/api/knowledge`, `/api/artifacts`).

### 7. Extensibilidad

```powershell
kaos new connector odoo    # scaffolding de un plugin + su test
```

**Decir:** *Plugin First* — nueva funcionalidad vía contratos públicos, sin tocar
el Core. Próximo en el roadmap: Odoo Connector, multi-workspace.

---

## Notas de infraestructura

- El proyecto de docker-compose se llama **`kaos`** (`name: kaos`), así el
  contenedor es `kaos-postgres-1` (antes `docker-postgres-1`).
- Postgres tiene **healthcheck**; `docker compose up -d --wait postgres` (o el
  script) esperan a que esté listo — se evita el error `ConnectionRefused` por
  arrancar antes de tiempo.
- Limpieza: `docker compose -f docker/docker-compose.yml down -v`.

## Checklist de credenciales (`.env`)

| Paso | Necesita |
|------|----------|
| 1–3 (offline) | nada |
| 4 (dogfooding) | `KAOS_GITHUB_TOKEN` (permiso *Models* + lectura del repo) |
| 5–6 (Discord) | `KAOS_DISCORD_TOKEN`, foro/guild, Docker (Postgres) |

