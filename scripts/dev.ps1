# KAOS — entorno de desarrollo local (Windows PowerShell)
#
# Uso:
#   .\scripts\dev.ps1
#   .\scripts\dev.ps1 -NoOllama
#   .\scripts\dev.ps1 -NoServe
#   .\scripts\dev.ps1 -Port 8000

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$NoOllama,
    [switch]$NoServe
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Compose = @('compose', '-f', 'docker/docker-compose.yml')
$DockerDesktop = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$env:KAOS_DATABASE_URL = 'postgresql://kaos:kaos@localhost:5432/kaos'

function Resolve-Python {
    $venv = Join-Path $Root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }

    throw 'No encuentro Python. Creá .venv o instalá Python 3.13.'
}

function Wait-Docker {
    docker info *> $null
    if ($LASTEXITCODE -eq 0) { return }

    if (-not (Test-Path $DockerDesktop)) {
        throw "Docker Engine no responde y Docker Desktop no existe en: $DockerDesktop"
    }

    Write-Host 'Iniciando Docker Desktop...' -ForegroundColor Cyan
    Start-Process $DockerDesktop

    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        docker info *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'Docker Engine listo.' -ForegroundColor Green
            return
        }
    }

    throw 'Docker Desktop se inició, pero Docker Engine no quedó disponible a tiempo.'
}

function Wait-Postgres {
    Write-Host 'Levantando PostgreSQL...' -ForegroundColor Cyan
    docker @Compose up -d postgres | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar PostgreSQL.' }

    for ($i = 0; $i -lt 40; $i++) {
        docker @Compose exec -T postgres pg_isready -U kaos -d kaos *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host 'PostgreSQL listo.' -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 1
    }

    throw 'PostgreSQL no quedó listo a tiempo.'
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'No encuentro docker.exe en PATH. Instalá Docker Desktop o corregí PATH.'
}

$Py = Resolve-Python
$UseInstalledKaos = [bool](Get-Command kaos -ErrorAction SilentlyContinue)
if (-not $UseInstalledKaos) { $env:PYTHONPATH = 'src' }

function Invoke-Kaos {
    if ($UseInstalledKaos) {
        & kaos @args
    } else {
        & $Py -m kaos.cli.main @args
    }

    if ($LASTEXITCODE -ne 0) {
        throw "KAOS terminó con código $LASTEXITCODE."
    }
}

Write-Host "Python: $Py" -ForegroundColor DarkGray
Wait-Docker
Wait-Postgres

if (-not $NoOllama) {
    Write-Host 'Levantando Ollama...' -ForegroundColor Cyan
    docker @Compose up -d ollama
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo iniciar Ollama.' }
    Write-Host 'Ollama iniciado en http://localhost:11434.' -ForegroundColor Green
}

Write-Host 'Verificando KAOS...' -ForegroundColor Cyan
Invoke-Kaos doctor

if ($NoServe) {
    Write-Host 'Infraestructura de desarrollo lista.' -ForegroundColor Green
    exit 0
}

Write-Host "Iniciando KAOS en http://localhost:$Port ..." -ForegroundColor Magenta
Invoke-Kaos serve --host 127.0.0.1 --port $Port