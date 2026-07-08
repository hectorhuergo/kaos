"""Demo assembly wired for `kaos up`.

Builds a fully functional KAOS pipeline using only in-repo plugins and no
external services:

    DiscordConnector -> EventBus -> ResumeAgent -> ConsolePublisher

It uses a `StaticDiscordSource` with a sample conversation and the SDK's
`EchoLLMProvider`, so `kaos up` demonstrates the whole flow end to end without a
Discord token or an AI provider. Real plugins can replace these later.
"""

from __future__ import annotations

from kaos.contracts.publisher import Publisher
from kaos.plugins.agents import ResumeAgent
from kaos.plugins.connectors import DiscordConnector, DiscordMessage, StaticDiscordSource
from kaos.plugins.publishers import ConsolePublisher
from kaos.runtime import InMemoryStorage, KaosRuntime
from kaos.sdk import EchoLLMProvider

SAMPLE_CONVERSATION = [
    DiscordMessage(
        message_id="1", channel_id="100", guild_id="42",
        author="ana", text="Avanzamos con el módulo de Odoo.",
    ),
    DiscordMessage(
        message_id="2", channel_id="100", guild_id="42",
        author="juan", text="Decidimos usar PostgreSQL y descartar Mongo.",
    ),
    DiscordMessage(
        message_id="3", channel_id="100", guild_id="42",
        author="ana", text="Riesgo: falta definir los permisos.",
    ),
]

SAMPLE_SUMMARY = (
    "# Resumen Ejecutivo\n\n"
    "## Estado\n- Se avanzó sobre el módulo de Odoo.\n\n"
    "## Decisiones\n- Se usará PostgreSQL.\n- Se descarta Mongo.\n\n"
    "## Riesgos\n- Falta definir los permisos.\n\n"
    "## Próximos pasos\n- Definir el esquema de permisos."
)


def build_demo_runtime(publisher: Publisher | None = None) -> KaosRuntime:
    """Wire a demo KaosRuntime with the in-repo plugins."""
    runtime = KaosRuntime(storage=InMemoryStorage())
    runtime.register_connector(
        DiscordConnector(StaticDiscordSource(list(SAMPLE_CONVERSATION)), emit_completed=True)
    )
    runtime.register_agent(ResumeAgent(EchoLLMProvider(response=SAMPLE_SUMMARY)))
    runtime.register_publisher(publisher if publisher is not None else ConsolePublisher())
    return runtime


async def run_demo() -> None:
    """Start a runtime from the environment, process events, then stop.

    Builds the runtime via the composition root (`kaos.bootstrap.factory`), so
    `kaos up` honours `.env`. With no Discord token it runs this offline demo.
    """
    from kaos.bootstrap.factory import build_runtime
    from kaos.core.config import Settings

    runtime = build_runtime(Settings.from_env())
    print("KAOS up — starting runtime (Connectors -> Agents -> Publishers)\n")
    await runtime.start()
    await runtime.stop()
    print("Done.")


async def run_offline_demo() -> None:
    """Run the fully offline demo pipeline, ignoring the environment.

    Uses in-repo plugins only (StaticDiscordSource + EchoLLMProvider +
    ConsolePublisher), so it always works without any credential — deterministic
    for demos and first runs regardless of what `.env` contains.
    """
    runtime = build_demo_runtime()
    print("KAOS up (offline) — Connector -> Agent -> Publisher (sin credenciales)\n")
    await runtime.start()
    await runtime.stop()
    print("Done.")


