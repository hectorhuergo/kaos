from __future__ import annotations

import asyncio
from collections.abc import Sequence
import pytest

from kaos.contracts.context import Context
from kaos.contracts.llm import Message
from kaos.plugins.agents.task_agent import TaskAgent


class ScriptedLLM:
    name = "scripted"

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.calls: list[Sequence[Message]] = []

    async def complete(self, messages: Sequence[Message], **_options: object) -> str:
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return "# Reporte Vacío"


def test_task_agent_consolidates_and_returns_artifact() -> None:
    # El mock contiene "endpoints v2."
    mock_markdown = (
        "# RESUMEN EJECUTIVO CONSOLIDADO\n"
        "El equipo resolvió las migraciones y actualizó los endpoints v2.\n"
        "## 🗓️ CRONOLOGÍA Y MARCO TEMPORAL\n"
        "- **Rango de ejecución de tareas:** 2026-07-10 al 2026-07-16"
    )
    llm = ScriptedLLM([mock_markdown])
    agent = TaskAgent(llm)

    context = Context(
        workspace="task:test",
        params={
            "hilos": "Hilo A: Juan hará las migraciones. Hilo B: Hay que migrar endpoints a v2."
        }
    )

    artifacts = asyncio.run(agent.run(context))

    # Verificaciones oficiales basadas en el contrato estricto de KAOS
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.kind == "task.report"
    assert art.produced_by == "task-agent"
    # CORRECCIÓN: Quitamos la "a" para que coincida exactamente con el mock_markdown
    assert "endpoints v2" in art.content["answer"]
