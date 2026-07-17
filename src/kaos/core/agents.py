"""Agent catalog: a read-only description of the agents KAOS ships.

Analogous to the LLM provider catalog (:mod:`kaos.core.providers`): pure data, no
plugin imports, so the CLI and the web console can *list* the available agents
without pulling in their implementations. The agents themselves remain plugins
(:mod:`kaos.plugins.agents`); this module only describes them (id, what they
produce, what triggers them and whether their prompt can be augmented).

Adding an agent to the catalog is metadata only — it does not register or wire
the agent into a runtime; composition still happens in the bootstrap factory.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentInfo:
    """A static description of an agent for catalog/UI purposes."""

    id: str
    label: str
    description: str
    produces: str  # the artifact kind it emits
    trigger: str  # what makes it run
    augmentable: bool  # accepts extra prompt instructions


AGENT_CATALOG: tuple[AgentInfo, ...] = (
    AgentInfo(
        id="resume-agent",
        label="Resume Agent",
        description=(
            "Resume una conversación en un informe ejecutivo en Markdown "
            "(Estado, Decisiones, Riesgos, Próximos pasos)."
        ),
        produces="conversation.summary",
        trigger="conversation.completed",
        augmentable=True,
    ),
    AgentInfo(
        id="dev-agent",
        label="Dev Agent",
        description=(
            "Compañero activo: usa herramientas confinadas sobre el repositorio "
            "local y produce una sesión trazable (dev.session)."
        ),
        produces="dev.session",
        trigger="tarea (kaos dev / evento dev.task)",
        augmentable=True,
    ),
    AgentInfo(
        id="task-agent",
        label="Task Agent",
        description=(
            "Consolida múltiples hilos en un reporte ejecutivo unificado con "
            "cronología, plan de acción y horas estimadas."
        ),
        produces="task.report",
        trigger="evento task.consolidate",
        augmentable=True,
    ),
)


def agent_catalog() -> tuple[AgentInfo, ...]:
    """Return the catalog of agents KAOS ships."""
    return AGENT_CATALOG

