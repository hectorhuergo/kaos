from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from kaos.contracts.context import Context
from kaos.contracts.llm import Message
from kaos.plugins.agents.translate_agent import TranslateAgent


class ScriptedLLM:
    name = "scripted"

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.calls: list[Sequence[Message]] = []

    async def complete(self, messages: Sequence[Message], **_options: object) -> str:
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return "# Traducción Vacía"


def test_translate_agent_localizes_pot_file(tmp_path: Path) -> None:
    mock_po_content = 'msgid "Stock Available"\nmsgstr "Stock Disponible"'
    llm = ScriptedLLM([mock_po_content])

    # Instanciamos el tool simulado que devuelve el contenido del archivo .pot
    mock_pot_content = 'msgid "Stock Available"\nmsgstr ""'
    file_read_tool = ScriptedTool(name="file_read", mock_return=mock_pot_content)

    # Inyectamos el listado de herramientas en el constructor del agente
    agent = TranslateAgent(llm=llm, tools=[file_read_tool])

    # 2. Desviamos temporalmente la ruta de uploads al directorio virtual del test
    # Esto evita fallos si el archivo físico real no existe durante la ejecución del test suite
    agent.uploads_base_dir = tmp_path

    # 3. Creamos la estructura simulada y el archivo .pot de prueba dentro de tmp_path
    workspace_test = "proyecto-g"
    project_test = "Translate"
    filename_test = "stock_20260722.pot"

    file_dir = tmp_path / workspace_test / project_test
    file_dir.mkdir(parents=True, exist_ok=True)

    mock_source_pot = 'msgid "Stock Available"\nmsgstr ""'
    test_file_path = file_dir / filename_test
    test_file_path.write_text(mock_source_pot, encoding="utf-8")

    # 4. Configuramos el contexto con los mismos parámetros que enviamos desde el chat
    context = Context(
        workspace=workspace_test,
        params={
            "workspace": workspace_test,
            "proyecto": project_test,
            "titulo": filename_test
        }
    )

    # 5. Ejecutamos el agente de forma asíncrona
    artifacts = asyncio.run(agent.run(context))

    # 6. Verificaciones oficiales bajo contratos estrictos de KAOS
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.kind == "translation.artifact"
    assert art.produced_by == "translate-agent"
    assert "Stock Disponible" in art.content["answer"]
    assert art.content["meta"]["project"] == project_test

class ScriptedTool:
    def __init__(self, name: str, mock_return: str):
        self.name = name
        self.description = "test tool"
        self.mock_return = mock_return

    async def run(self, args: dict[str, object]) -> str:
        return self.mock_return

