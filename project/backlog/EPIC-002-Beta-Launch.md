# EPIC-002 — Wider Beta Launch (final touch)

## Goal

Cerrar las capacidades que faltan para abrir un beta test más amplio: agentes
que reutilizan conocimiento, suscripciones autónomas, escritura de código
trazable y una consola conversacional de agentes.

## Stories

### S1 — Subscription selects Provider, Model & Agent

- Extender `Subscription` con `llm_provider`, `llm_model` y `agent` (opcionales;
  fallback a la config activa). Persistir en el store (Postgres + in-memory).
- El runner de la suscripción arma el `LLMProvider`/agente según esos campos.
- CLI (`kaos subscribe … --provider … --model … --agent …`) y consola
  (formulario de suscripción) los exponen.
- **AC:** una suscripción corre con su provider/modelo/agente propio sin cambiar
  el `.env` global; se ve en `GET /api/subscriptions`.

### S2 — Code publisher for the Dev Agent (reusable)

- Completar un `Publisher` que materialice el output de código (aplicar cambios /
  escribir archivos / abrir PR) de forma **trazable** y **confinada**, detrás del
  contrato `Publisher`, reutilizable por cualquier agente que escriba código.
- Salvaguardas: allowlist/confinamiento al repo, dry-run, evidencia inmutable del
  cambio (diff en el artifact). Nueva ADR con el modelo de riesgo.
- **AC:** el Dev Agent produce un artifact de cambio de código y el publisher lo
  aplica/propone; el mismo publisher lo usa otro agente sin cambios.

### S3 — Agents reuse artifacts by default (unless force)

- Generalizar el patrón del `SummaryCache` a un reuse-by-default a nivel de
  agente: si ya existe un artifact vigente para el sujeto, reutilizarlo salvo
  `force`.
- **AC:** re-ejecutar sin `force` no vuelve a llamar al LLM; con `force` regenera
  y crea una nueva versión (se ve como solapa en el grafo).

### S4 — Agent interaction console

- Vista en la web console para **interactuar con un agente** (elegir agente →
  enviar tarea/prompt → ver la sesión/artifact). Reutiliza el catálogo de agentes
  (`/api/agents`) y el prompt aumentable por agente.
- **AC:** desde la consola se lanza una interacción con un agente (p. ej. Dev
  Agent) y se ve el resultado trazable.

### S5 — (Optional) GitHub Copilot API as LLMProvider

- Evaluar/implementar un `LLMProvider` para la GitHub Copilot API, generalizando
  de paso el catálogo de providers (auth, base_url, modelos).
- **AC:** seleccionable desde la consola como cualquier otro provider; si no es
  viable, queda documentado el porqué (ADR).

### S6 — Missing agents (initial spec)

- Crear los agentes pendientes de la especificación inicial (más allá de Resume y
  Dev), cada uno como plugin bajo el contrato `Agent`, con su entrada en el
  catálogo.
- **AC:** los nuevos agentes aparecen en `/api/agents`, tienen tests y se pueden
  ejecutar desde CLI/consola.

## Acceptance Criteria (epic)

Un beta tester puede: configurar una suscripción con su propio provider/modelo/
agente, ejecutar agentes que reutilizan conocimiento (o fuerzan regeneración),
escribir código de forma trazable con un publisher compartido, e interactuar con
los agentes desde la consola — todo con el quality gate verde y ADRs por cada
decisión arquitectónica.

