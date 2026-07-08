# AGENTS.md

# KAOS — Agent Context

- **Project:** KAOS (Knowledge Analysis & Orchestration System)
- **Status:** v1.0.0-beta

## Purpose

KAOS es una plataforma para transformar información no estructurada (conversaciones, documentos,
eventos y sistemas externos) en conocimiento organizacional estructurado mediante agentes
especializados.

El proyecto comenzó con un caso de uso concreto: un bot para Discord capaz de resumir
conversaciones y generar conocimiento. Durante el diseño se decidió generalizar la solución y
convertirla en una plataforma extensible orientada a eventos.

Discord pasa a ser simplemente el primer **Connector** del sistema.

## Vision

KAOS debe convertirse en un "Sistema Operativo para el Conocimiento Organizacional".

El objetivo no es producir texto.

El objetivo es construir conocimiento persistente, trazable y reutilizable.

Los reportes, resúmenes y dashboards son únicamente distintas vistas de ese conocimiento.

## Core Principles

- Event First
- Plugin First
- Core Agnostic
- AI Provider Agnostic
- Structured Knowledge
- Immutable Evidence
- Everything is Traceable
- Knowledge before Reports

## Architecture

La arquitectura se divide en capas claramente desacopladas:

1. Connectors
2. Event Bus
3. Runtime / Core
4. Agents
5. Knowledge Layer
6. Publishers

- Los **Connectors** producen eventos.
- El **Runtime** orquesta la ejecución.
- Los **Agents** transforman contexto en conocimiento.
- Los **Publishers** exponen ese conocimiento.

## Repository Structure

```
KAOS/
src/
    kaos/
        bootstrap/
        cli/
        core/
        runtime/
        sdk/
        domain/
        contracts/
        plugins/
docker/
docs/
project/
templates/
tests/
```

La estructura del repositorio queda congelada durante la etapa alpha.

## Technology Stack

- **Lenguaje:** Python 3.13
- **Gestión del proyecto:** uv
- **Calidad:**
  - Ruff
  - MyPy
  - Pytest
- **Infraestructura:**
  - Docker Compose
  - PostgreSQL
  - Redis
  - MinIO
- **API:** FastAPI
- **Modelado:** Pydantic v2

## Development Philosophy

El proyecto se desarrolla siguiendo prácticas de ingeniería:

- Semantic Versioning
- ADR para decisiones arquitectónicas
- RFC para visión y cambios estratégicos
- Commits semánticos
- Arquitectura incremental
- Dogfooding

KAOS debe terminar administrando su propio desarrollo.

## Current Documentation

### ADR

- ADR-0001 — Foundation
- ADR-0002 — Domain Model & Ontology
- ADR-0003 — Kernel Contracts
- ADR-0004 — CLI Scaffolding & Dogfooding
- ADR-0005 — Conversation Context & LLM Provider
- ADR-0006 — Configuration & Composition Root
- ADR-0007 — Summary Cache & Knowledge Reuse
- ADR-0008 — Subscriptions & Persistent Configuration
- ADR-0009 — Scheduler & Provider Catalog
- ADR-0010 — Knowledge Layer & Graph
- ADR-0011 — Live Dashboard (FastAPI)

### RFC

- RFC-0001 — The KAOS Philosophy

### Project Documents

- ARCHITECTURE.md
- ROADMAP.md
- CONTRIBUTING.md

## Coding Principles

- Preferir composición sobre herencia.
- El Core no debe depender de proveedores externos.
- Los plugins nunca modifican el Runtime.
- Toda funcionalidad nueva debe implementarse mediante contratos públicos.
- Evitar dependencias circulares.
- Mantener compatibilidad hacia atrás siempre que sea posible.

## Initial Contracts

El Kernel girará alrededor de estos contratos:

- Agent
- Connector
- Publisher
- Storage
- LLMProvider
- Runtime
- EventBus
- Context
- Artifact

Estos contratos deben permanecer estables y evolucionar con mucho cuidado.

## Initial Roadmap

### Alpha

- Bootstrap
- CLI
- Runtime
- SDK
- Event Bus
- Plugin Registry
- Discord Connector
- Resume Agent

### Beta

- Knowledge Graph
- Dashboard
- GitHub Connector
- Odoo Connector
- Multi-workspace

### Version 1.0

- Stable SDK
- Distributed Runtime
- Marketplace de Plugins
- Production Documentation

## Definition of Done

Ningún cambio se considera terminado si no cumple:

- Compila.
- Instala.
- Ejecuta.
- Tiene pruebas cuando corresponde.
- Mantiene la documentación actualizada.
- Respeta los ADR existentes o incorpora uno nuevo cuando introduce una decisión
  arquitectónica.

## Working Agreement

A partir de la etapa alpha, este proyecto deja de evolucionar mediante prototipos aislados.

Cada entrega representa un incremento real del repositorio y debe poder convertirse directamente en
uno o más commits.

El objetivo es construir una base estable sobre la que KAOS pueda evolucionar durante años sin perder
coherencia arquitectónica.

## Origin

Este documento resume las decisiones fundacionales tomadas durante el diseño inicial del proyecto y
debe considerarse el contexto mínimo que todo agente (humano o IA) debe leer antes de contribuir al
desarrollo de KAOS.

