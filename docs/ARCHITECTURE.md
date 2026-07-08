# KAOS Architecture

## Vision

KAOS (Knowledge Analysis & Orchestration System) is an event-driven platform that transforms conversations and operational events into structured organizational knowledge.

## Layered Architecture

1. Connectors
2. Event Bus
3. Runtime / Core
4. Agents
5. Knowledge Layer
6. Publishers

## Design Principles

- Plugin First
- Event First
- Core Agnostic
- AI Provider Agnostic
- Structured Knowledge
- Immutable Evidence
- Everything is Traceable
- Knowledge before Reports

## Runtime Flow

Connector → Event → Context Builder → Agent Pipeline → Artifacts → Publishers → Knowledge Store

## Components

- Bootstrap
- CLI (`kaos ...`)
- Runtime (EventBus, KaosRuntime, Scheduler)
- Plugin Registry / Composition Root
- EventBus
- Artifact Store (in-memory / PostgreSQL)
- Summary Cache (knowledge reuse)
- Console / Discord Publishers
- Discord Connector (live gateway + REST backfill)
- LLM Providers (OpenAI-compatible: OpenAI, GitHub Models, Anthropic, …)

> The canonical, up-to-date architecture document is the top-level
> [`ARCHITECTURE.md`](../ARCHITECTURE.md). This file keeps the high-level vision;
> see the ADRs in [`adr/`](adr/) for the detailed decisions.
