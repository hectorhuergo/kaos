# Roadmap
- Foundation
- CLI
- Kernel
- SDK
- Discord

## Alpha — progreso
- [x] Kernel contracts (`src/kaos/contracts/`)
- [x] Runtime (EventBus, Runtime, Storage)
- [x] SDK (EchoLLMProvider)
- [x] Resume Agent
- [x] Discord Connector
- [x] CLI `up` que arranca el Runtime con plugins
- [x] LLM Provider (OpenAI-compatible / GitHub Models)
- [x] Persistencia real (PostgreSQL) + cache de resúmenes (reutiliza conocimiento)
- [x] Suscripciones persistidas (`kaos subscribe` / `kaos run`)

## Beta — progreso
- [x] Configuración de providers (`kaos providers`, catálogo agnóstico)
- [x] Scheduler (`kaos schedule`, corre `kaos run` idempotente en intervalo)
- [x] Knowledge Graph (`kaos knowledge`, proyección sobre artifacts/eventos)
- [x] Dashboard estático (`kaos dashboard`, HTML autocontenido)
- [x] Dashboard vivo (`kaos serve`, app FastAPI read-only con API JSON)
- [x] GitHub Connector (`kaos github`, resume la actividad de un repo)
- [x] Suscripciones a repositorios GitHub (`kaos subscribe <owner/repo> --github`)
- [x] Consola web — vista de Agentes (`/api/agents`) + prompt aumentable del Resume Agent
- [x] Scheduler como app (`docker compose --profile app up`, servicios `scheduler`/`dashboard`)
- [ ] Lectura general de Git (integración del trabajo de Maxi)
- [ ] Odoo Connector
- [ ] Multi-workspace

## Beta test amplio — toque final (M1 · EPIC-002)
- [ ] Suscripciones con Provider, Modelo y Agente propios (además del plan)
- [ ] Publisher del Dev Agent para escribir código (reusable por cualquier agente)
- [ ] Agentes reutilizan artifacts por defecto (salvo `force`)
- [ ] Consola para interactuar con los agentes
- [ ] (Opcional) GitHub Copilot API como `LLMProvider` (generalizar providers)
- [ ] Crear los agentes faltantes de la especificación inicial
- [ ] Descanso y dogfooding 🎉

## Integraciones futuras
- [ ] Integración con el sistema de usuarios de **proyecto-x-grid**
      (autenticación/identidad compartida para autores, permisos y multi-tenant)


