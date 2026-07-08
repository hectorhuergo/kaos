# Architecture

KAOS se organiza en capas desacopladas:

```
Connectors -> Event Bus -> Runtime / Core -> Agents -> Knowledge -> Publishers
```

- Los **Connectors** producen eventos.
- El **Runtime** orquesta la ejecución.
- Los **Agents** transforman contexto en conocimiento.
- Los **Publishers** exponen ese conocimiento.

## Kernel Contracts

El Kernel gira alrededor de contratos públicos estables en
`src/kaos/contracts/`:

- **Datos inmutables (Pydantic v2):** `Event`, `Context`, `Artifact`.
- **Comportamiento (`typing.Protocol`):** `Agent`, `Connector`, `Publisher`,
  `Storage`, `SubscriptionStore`, `LLMProvider`, `EventBus`, `Runtime`.

Toda funcionalidad nueva se implementa satisfaciendo estos contratos. Ver
`docs/adr/ADR-0001.md`, `docs/adr/ADR-0002.md` y `docs/adr/ADR-0003.md`.

## Domain

`src/kaos/domain/` contiene las entidades de dominio. `Subscription` registra qué
foro/canal de Discord observa KAOS y a qué thread publica. Es **estado de dominio
persistente** (no un secreto): se guarda vía `SubscriptionStore`
(`InMemorySubscriptionStore` o `PostgresSubscriptionStore`). La separación es
deliberada: los secretos viven en el entorno; las suscripciones, en la base de
datos (ver `docs/adr/ADR-0008.md`).

## Runtime

`src/kaos/runtime/` provee la implementación concreta de un solo proceso:

- `InMemoryEventBus` — bus publish/subscribe en memoria (tipos + wildcard `*`).
- `InMemoryStorage` — persistencia en memoria de eventos y artifacts.
- `KaosRuntime` — orquesta el pipeline
  `Connectors -> EventBus -> Agents -> Publishers`, construyendo un `Context`
  por evento, ejecutando los Agents que lo aceptan y publicando los Artifacts
  resultantes (con persistencia opcional vía `Storage`). Acumula los eventos por
  `workspace` (motor de contexto mínimo) para que los agentes de nivel
  conversación reciban la conversación completa; el evento
  `conversation.completed` actúa como disparador.
- `Scheduler` — lazo agnóstico del Core que corre un job async idempotente en un
  intervalo fijo, con el tiempo inyectable (testeable sin esperas reales).
  `kaos schedule` lo usa para disparar `kaos run` periódicamente; como `run`
  publica solo si algo cambió, las corridas sobre fuentes sin cambios no generan
  publicaciones nuevas (ver `docs/adr/ADR-0009.md`).

Estas implementaciones son intercambiables (p. ej. bus sobre Redis, storage
sobre PostgreSQL/MinIO) sin tocar Connectors, Agents ni Publishers.

## Core

`src/kaos/core/` es el núcleo agnóstico (sin dependencias de proveedores):

- `config.py` — `Settings` cargadas del entorno (`.env`); pura data, sin importar
  plugins. La composición vive en `src/kaos/bootstrap/factory.py`.
- `providers.py` — **catálogo descriptivo** de proveedores LLM (modelo por
  defecto, endpoint, credencial requerida), sincronizado con `LLM_PROVIDERS`.
  `kaos providers` lo lista, marca el activo e indica si tiene credencial (nunca
  imprime secretos). Ver `docs/adr/ADR-0009.md`.
- `cache.py` — **cache de resúmenes** *read-through* sobre `Storage`, indexada por
  hilo + huella de contenido + modelo: una conversación sin cambios no vuelve a
  consultar al LLM. Persiste entre corridas con `PostgresStorage`
  (`docs/adr/ADR-0007.md`).
- `redaction.py` — redacción de secretos (seed phrases, claves privadas, tokens)
  antes de que un texto llegue al LLM o se publique como Artifact.

## Agents

Los agentes viven en `src/kaos/plugins/agents/` y dependen solo de contratos:

- **Resume Agent** — consume los eventos de mensajes de una conversación y
  produce un `Artifact` (`conversation.summary`) con un resumen ejecutivo en
  Markdown. Usa el contrato `LLMProvider`, por lo que es agnóstico del proveedor
  de IA; el `EchoLLMProvider` del SDK permite probarlo sin proveedor externo. El
  transcript que recibe el LLM prefija cada línea con la fecha/hora del mensaje
  (ISO-8601) cuando el evento la trae, de modo que el resumen referencia fechas
  reales en vez de inventarlas.

## LLM Providers

`src/kaos/plugins/providers/` contiene implementaciones de `LLMProvider`. El
`OpenAICompatibleLLMProvider` habla con cualquier endpoint OpenAI-compatible
(OpenAI, Azure, **GitHub Models**, Anthropic, Ollama, ...). Para usar GitHub como
backend:

```python
from kaos.plugins.providers import OpenAICompatibleLLMProvider

llm = OpenAICompatibleLLMProvider.github_models(token=os.environ["GITHUB_TOKEN"])
```

El catálogo de proveedores (`src/kaos/core/providers.py`) describe las opciones
disponibles y `kaos providers` reporta cuál está activo y si tiene credencial.
La selección concreta la resuelve la composición root según `KAOS_LLM_PROVIDER`
(ver `docs/adr/ADR-0005.md` y `docs/adr/ADR-0009.md`).

## Knowledge Layer

El conocimiento acumulado son los `Artifact`s persistidos, y como cada uno traza
a sus `source_events`, esa estructura ya es un grafo. `src/kaos/core/knowledge.py`
la **proyecta** (sin datastore nuevo): `build_graph()` produce nodos
(`workspace`, `artifact`, `event`) y aristas (`contains`, `derived_from`) sobre
el contrato `Storage`, con exportadores a JSON y Mermaid. El
`src/kaos/plugins/dashboard/` renderiza esa proyección como un HTML autocontenido
(tarjetas de resumen + grafo de trazabilidad). `kaos knowledge` y `kaos dashboard`
son las vistas de CLI (Knowledge before Reports; ver `docs/adr/ADR-0010.md`).

