# Milestone M1 — Wider Beta Launch

## Objective

Dejar KAOS listo para un **beta test más amplio**: que cada suscripción sea
autónoma (provider/modelo/agente propios), que los agentes reutilicen el
conocimiento ya producido, que se pueda **escribir código** de forma trazable y
que haya una consola para conversar con los agentes.

## Deliverables (final touch)

1. **Suscripciones configurables**: cada suscripción especifica Provider, Modelo
   y Agente (además de su plan de ejecución).
2. **Publisher del Dev Agent**: completar el publisher que materializa el output
   de código, reutilizable por cualquier agente que escriba código.
3. **Reuse-by-default**: los agentes aprovechan los artifacts existentes salvo
   `force` (regeneración explícita).
4. **Consola de agentes**: una vista para interactuar (chat/tarea) con los
   agentes desde la web console.
5. **(Opcional) GitHub Copilot API**: evaluar integrarla como `LLMProvider` para
   generalizar de paso nuestros métodos de proveedor.
6. **Agentes faltantes**: crear los agentes que faltan para cumplir la
   especificación inicial (ver EPIC-002).
7. **Descanso y dogfooding**: disfrutar la creación; KAOS administrando su propio
   desarrollo.

## Exit Criteria

- Una suscripción puede correr con su propio provider/modelo/agente sin tocar
  `.env` global.
- Un agente que escribe código produce un artifact + lo publica de forma
  trazable, reutilizando el mismo publisher.
- Re-ejecutar sin `force` reutiliza el conocimiento (no repite trabajo del LLM).
- La consola permite lanzar y ver una interacción con un agente.
- Quality gate verde (Ruff · MyPy · Pytest) y ADRs por cada decisión nueva.

