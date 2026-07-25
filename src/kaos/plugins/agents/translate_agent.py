from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from kaos.contracts.artifact import Artifact
from kaos.contracts.context import Context
from kaos.contracts.llm import LLMProvider, Message
from kaos.contracts.tool import Tool

# Default root under which uploaded ``.pot`` files live (relative to the working
# directory so the agent is portable). Override per-instance if needed.
DEFAULT_UPLOADS_DIR = Path("uploads")

SYSTEM_PROMPT = (  # fmt: skip
    "Eres un motor de traducción Gettext estricto integrado en KAOS.\n"
    "Se te proveerá un fragmento de un archivo .pot de Odoo.\n\n"

    "REGLAS OBLIGATORIAS:\n"
    "1. Traduce al español el texto que se encuentra dentro de 'msgid' e "
    "inyéctalo estrictamente dentro de las comillas de su respectivo 'msgstr'.\n"
    "2. NO dejes los campos 'msgstr' vacíos si el 'msgid' tiene texto.\n"
    "3. Deja intactas todas las variables de escape como %(transfer_list)s, %s, "
    "etc., dentro de tu traducción.\n"
    "4. Mantén los comentarios (#.) exactamente igual.\n\n"
    "5. Traducir todos los msgid.\n"
    "EJEMPLO DE ENTRADA:\n"
    "#: code:addons/stock/models.py\n"
    "msgid \"Transfers\"\n"
    "msgstr \"\"\n\n"
    "EJEMPLO DE SALIDA REQUERIDA:\n"
    "#: code:addons/stock/models.py\n"
    "msgid \"Transfers\"\n"
    "msgstr \"Transferencias\"\n\n"
    "Devuelve únicamente el archivo .po estructurado. No agregues introducciones, "
    "bloques de código markdown ``` ni explicaciones."
    "EXCEPCIONES:"
    "Si el 'msgid' está vacío, deja 'msgstr' vacío también. Si el 'msgid' contiene "
    "solo variables de escape, traduce el resto del texto y conserva las variables "
    "intactas.\n"
    "Existen casos como:\n"
    "msgid \"\"\n"
    "\"When different than 0, inventory count date for products stored at this\"\n"
    "\"location will be automatically set at the defined frequency.\"\n"
    "Donde el texto se encuentra en varias líneas, en esos casos traduce el "
    "contenido completo y conserva la estructura de múltiples líneas.\n"
    "Tener en cuenta que se abren y cierran comillas dobles en cada línea, "
    "pudiendo ser la primera \"\", y la traducción debe reflejar exactamente esa "
    "estructura de múltiples líneas."
    "Mantener el orden y la pertenencia de cada msgid con su msgstr "
    "correspondiente, sin mezclar traducciones entre diferentes entradas.\n"
    "** Evitar casos como: **\n"
    "#. module: stock\n"
    "#: model:ir.model.fields,help:stock.field_stock_location__cyclic_inventory_frequency"
    "#: model:ir.model.fields,help:stock.field_stock_quant__cyclic_inventory_frequency"
    "msgid \"\"\n"
    "\"Cuando diferente de 0, la fecha de conteo de inventario para los "
    "productos almacenados en esta\""
    "\"ubicación se establecerá automáticamente en la frecuencia definida.\""
    "msgstr \"\"\n"
    "..."
    "#: code:addons/stock/models.py"
    "msgid \"\"\n"
    "\"When different than 0, inventory count date for products stored at this\""
    "\"location will be automatically set at the defined frequency.\"\n"
    "msgstr \"\"\n"
    "Donde el msgid y msgstr no coinciden, lo cual es un error de traducción. "
    "Asegúrate de que cada msgid tenga su correspondiente msgstr traducido "
    "correctamente."
    "El msgid terminó en otra posición y el msgstr quedó vacío, lo cual es un "
    "error. Asegúrate de que cada msgid tenga su correspondiente msgstr traducido "
    "correctamente."
)



class TranslateAgent:
    """Localizes ``.pot`` files by reading them via a tool and translating them.

    Reads the source from local storage through the injected ``file_read`` tool
    and produces a ``translation.artifact`` with the translated ``.po`` text.
    """

    name = "translate-agent"

    def __init__(
        self,
        llm: LLMProvider,
        tools: Sequence[Tool] | None = None,
        *,
        uploads_base_dir: Path | None = None,
    ) -> None:
        self.llm = llm
        self.tools = {t.name: t for t in tools} if tools else {}
        self.uploads_base_dir = uploads_base_dir or DEFAULT_UPLOADS_DIR

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    async def run(self, context: Context) -> list[Artifact]:
        params = context.params or {}
        workspace = params.get("workspace", context.workspace or "proyecto-g")
        proyecto = params.get("proyecto", "Translate")
        titulo = params.get("titulo", "stock_20260722.pot")

        filename = titulo if titulo.endswith((".pot", ".txt", ".po")) else f"{titulo}.pot"
        file_path = self.uploads_base_dir / workspace / proyecto / filename

        # Read the source file through the injected KAOS Tool (never touch the FS
        # directly, so the agent stays testable and storage-agnostic).
        file_read_tool = self.tools.get("file_read")
        if not file_read_tool:
            raise ValueError("El tool 'file_read' es obligatorio para este agente.")

        source_text = await file_read_tool.run({"path": str(file_path)})

        fecha_actual = datetime.now().strftime("%Y-%m-%d")

        messages = [
            Message(role="system", content=self.get_system_prompt()),
            Message(
                role="user",
                content=(
                    f"FECHA ACTUAL: {fecha_actual}\n"
                    f"ARCHIVO: {filename}\n\n"
                    f"MÓDULO DE ODOO A TRADUCCIÓN:\n{source_text}"
                ),
            ),
        ]

        response = await self.llm.complete(messages)

        return [
            Artifact(
                workspace=workspace,
                kind="translation.artifact",
                produced_by="translate-agent",
                content={
                    "summary": f"Traducción completa de {filename}",
                    "answer": response.strip(),
                    "generated_at": fecha_actual,
                    "meta": {"source_path": str(file_path), "project": proyecto},
                },
            )
        ]
