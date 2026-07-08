# Contributing

## Commits

Usa **commits semánticos**: `feat(...)`, `fix(...)`, `refactor(...)`,
`docs(...)`, `test(...)`, `chore(...)`.

## Ramas

- `main` — estable
- `feature/*` — nuevas funcionalidades
- `hotfix/*` — correcciones urgentes

## Quality Gates

Antes de abrir un cambio, verifica:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Definition of Done

Ningún cambio se considera terminado si no:

- Compila, instala y ejecuta.
- Tiene pruebas cuando corresponde.
- Mantiene la documentación actualizada.
- Respeta los ADR existentes o incorpora uno nuevo cuando introduce una decisión
  arquitectónica.

Los cambios arquitectónicos requieren un nuevo ADR en `docs/adr/`. Toda
funcionalidad nueva se implementa satisfaciendo los contratos públicos del
Kernel (`src/kaos/contracts/`); los plugins nunca modifican el Runtime.

Ver `AGENTS.md` para el contexto de arquitectura y `docs/CONTRIBUTING.md`.
