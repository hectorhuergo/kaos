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
- [ ] Dashboard vivo (servicio FastAPI: filtrado, búsqueda)
- [ ] GitHub Connector
- [ ] Odoo Connector
- [ ] Multi-workspace


