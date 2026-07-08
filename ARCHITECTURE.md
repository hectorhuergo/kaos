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

Estas implementaciones son intercambiables (p. ej. bus sobre Redis, storage
sobre PostgreSQL/MinIO) sin tocar Connectors, Agents ni Publishers.

## Agents

Los agentes viven en `src/kaos/plugins/agents/` y dependen solo de contratos:

- **Resume Agent** — consume los eventos de mensajes de una conversación y
  produce un `Artifact` (`conversation.summary`) con un resumen ejecutivo en
  Markdown. Usa el contrato `LLMProvider`, por lo que es agnóstico del proveedor
  de IA; el `EchoLLMProvider` del SDK permite probarlo sin proveedor externo.

## LLM Providers

`src/kaos/plugins/providers/` contiene implementaciones de `LLMProvider`. El
`OpenAICompatibleLLMProvider` habla con cualquier endpoint OpenAI-compatible
(OpenAI, Azure, **GitHub Models**, Ollama, ...). Para usar GitHub como backend:

```python
from kaos.plugins.providers import OpenAICompatibleLLMProvider

llm = OpenAICompatibleLLMProvider.github_models(token=os.environ["GITHUB_TOKEN"])
```

