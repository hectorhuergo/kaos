# KAOS — Demo reproducible (Windows PowerShell)
#
# Ejecuta la demo en el orden correcto, esperando a que Postgres esté listo y
# usando `python -m kaos.cli.main` cuando el ejecutable `kaos` no está instalado
# (típico en Windows si el venv no es 3.13).
#
# Uso:
#   .\scripts\demo.ps1                # demo guiada (pausa en cada paso)
#   .\scripts\demo.ps1 -NoPause       # sin pausas
#   .\scripts\demo.ps1 -Offline       # solo lo que no requiere credenciales
#   .\scripts\demo.ps1 -KeepUp        # no baja Postgres al final
#
# Repo/foro por defecto (se pueden sobreescribir por parámetro o entorno):
#   -Repo hectorhuergo/kaos  -ForumId <id>  -GuildId <id>

[CmdletBinding()]
param(
    [string]$Repo = "hectorhuergo/kaos",
    [string]$ForumId = $env:KAOS_DEMO_FORUM_ID,
    [string]$GuildId = $env:KAOS_DEMO_GUILD_ID,
    [switch]$Offline,
    [switch]$NoPause,
    [switch]$KeepUp
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Compose = @('compose', '-f', 'docker/docker-compose.yml')
$DbUrl = 'postgresql://kaos:kaos@localhost:5432/kaos'

# --- Resolución de Python / kaos ---------------------------------------------
function Resolve-Python {
    $venv = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "No encuentro Python. Creá el venv (.venv) o instalá Python 3.13."
}

$script:Py = Resolve-Python
$script:UseInstalled = [bool](Get-Command kaos -ErrorAction SilentlyContinue)
if (-not $script:UseInstalled) { $env:PYTHONPATH = 'src' }

function kaos {
    # Usa el ejecutable `kaos` si está instalado; si no, `python -m kaos.cli.main`.
    if ($script:UseInstalled) { & kaos @args }
    else { & $script:Py -m kaos.cli.main @args }
}

# --- Utilidades ---------------------------------------------------------------
function Step($title) {
    Write-Host ""
    Write-Host "=== $title ===" -ForegroundColor Cyan
    if (-not $NoPause) { [void](Read-Host "  (Enter para ejecutar)") }
}

function Info($msg) { Write-Host $msg -ForegroundColor DarkGray }

function Get-Conf($key) {
    $v = [Environment]::GetEnvironmentVariable($key)
    if ($v) { return $v }
    $envFile = Join-Path $Root '.env'
    if (Test-Path $envFile) {
        $rx = "^\s*$([regex]::Escape($key))\s*="
        $line = Select-String -Path $envFile -Pattern $rx -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($line) { return ($line.Line -replace $rx, '').Trim().Trim('"', "'") }
    }
    return $null
}

function Wait-Postgres {
    Info "Levantando Postgres y esperando a que esté listo (healthcheck)..."
    docker @Compose up -d postgres | Out-Null
    for ($i = 0; $i -lt 40; $i++) {
        docker @Compose exec -T postgres pg_isready -U kaos -d kaos *> $null
        if ($LASTEXITCODE -eq 0) { Write-Host "  Postgres listo." -ForegroundColor Green; return }
        Start-Sleep -Seconds 1
    }
    throw "Postgres no quedó listo a tiempo."
}

# --- Prerrequisitos -----------------------------------------------------------
$HasDocker = [bool](Get-Command docker -ErrorAction SilentlyContinue)
$HasGitHub = [bool]((Get-Conf 'KAOS_GITHUB_TOKEN') -or (Get-Conf 'GITHUB_TOKEN'))
$HasDiscord = [bool](Get-Conf 'KAOS_DISCORD_TOKEN')
if (-not $ForumId)  { $ForumId  = Get-Conf 'KAOS_DISCORD_BACKFILL_CHANNEL_ID' }
if (-not $GuildId)  { $GuildId  = Get-Conf 'KAOS_DISCORD_GUILD_ID' }

Write-Host "KAOS demo — invocación: $([string]::Join(' ', @(if ($script:UseInstalled) {'kaos'} else {"$($script:Py) -m kaos.cli.main"})))" -ForegroundColor Magenta
Info "docker=$HasDocker  github=$HasGitHub  discord=$HasDiscord  repo=$Repo  forum=$ForumId  guild=$GuildId"

# --- 1. Entorno ---------------------------------------------------------------
Step "1. Entorno (doctor + versión)"
kaos doctor
kaos version

# --- 2. Proveedores LLM -------------------------------------------------------
Step "2. Proveedores LLM disponibles"
kaos providers

# --- 3. Demo offline (0 credenciales) -----------------------------------------
Step "3. Demo offline (pipeline Connector -> Agent -> Publisher, sin red)"
kaos up --offline

if ($Offline) {
    Write-Host "`nDemo offline completa. (usa sin -Offline para dogfooding + Discord)" -ForegroundColor Green
    return
}

# A partir de acá usamos GitHub Models para resúmenes reales.
if ($HasGitHub) {
    $env:KAOS_LLM_PROVIDER = 'github'
    $env:KAOS_LLM_MODEL = 'gpt-4o-mini'
}

# --- 4. Dogfooding: KAOS se resume a sí mismo ---------------------------------
if ($HasGitHub) {
    Step "4. Dogfooding — KAOS resume su propio repo ($Repo)"
    kaos github $Repo --dry-run --limit 20
} else {
    Info "`n(salteo dogfooding: falta KAOS_GITHUB_TOKEN en .env)"
}

# --- 5. Run de Discord (foro) + conocimiento ----------------------------------
if ($HasDiscord -and $ForumId -and $GuildId -and $HasDocker) {
    Wait-Postgres
    $env:KAOS_DATABASE_URL = $DbUrl

    Step "5. Run de Discord — resume el foro (consolidado, dry-run)"
    kaos backfill-forum $ForumId --guild $GuildId --consolidated --dry-run

    Step "6. Ver el conocimiento (grafo, texto)"
    kaos knowledge --workspace $ForumId

    Step "7. Dashboard estático (HTML autocontenido)"
    kaos dashboard --workspace $ForumId --out kaos-dashboard.html
    Start-Process (Resolve-Path .\kaos-dashboard.html).Path

    Step "8. Dashboard vivo (FastAPI) — se abre en el navegador"
    $job = Start-Job -ScriptBlock {
        param($cwd, $py, $installed, $db)
        Set-Location $cwd; $env:PYTHONPATH = 'src'; $env:KAOS_DATABASE_URL = $db
        if ($installed) { & kaos serve --port 8000 } else { & $py -m kaos.cli.main serve --port 8000 }
    } -ArgumentList $Root, $script:Py, $script:UseInstalled, $DbUrl
    Start-Sleep -Seconds 6
    Start-Process "http://127.0.0.1:8000/?workspace=discord:$ForumId"
    if (-not $NoPause) { [void](Read-Host "  (Enter para detener el dashboard vivo)") }
    Stop-Job $job -ErrorAction SilentlyContinue | Out-Null
    Remove-Job $job -Force -ErrorAction SilentlyContinue | Out-Null
} else {
    Info "`n(salteo Discord/dashboard: faltan KAOS_DISCORD_TOKEN / foro / guild / docker)"
}

# --- Cleanup ------------------------------------------------------------------
if (-not $KeepUp) {
    Step "Limpieza (bajar Postgres, borrar HTML temporal)"
    Remove-Item (Join-Path $Root 'kaos-dashboard.html') -ErrorAction SilentlyContinue
    if ($HasDocker) { docker @Compose down -v | Out-Null }
    Write-Host "Listo." -ForegroundColor Green
} else {
    Write-Host "`n(-KeepUp: Postgres queda arriba)" -ForegroundColor Yellow
}

