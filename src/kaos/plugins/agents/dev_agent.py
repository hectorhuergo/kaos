"""Dev Agent: an active teammate that uses tools to work on the codebase.

Unlike the Resume Agent (which only produces text), the Dev Agent runs a bounded
*tool-use loop*: given a task, it repeatedly asks the LLM what to do next, and the
model either calls a tool (read a file, search code, run a whitelisted command)
or returns a final answer. Every step is recorded, so the resulting artifact is a
fully traceable dev session (Everything is Traceable).

The loop uses a strict one-JSON-object-per-turn protocol rather than provider
function-calling, so it works with any LLMProvider — including small local models
served by Ollama. Tools are responsible for their own safety (see
``kaos.plugins.tools.dev_tools``); the agent adds a hard step limit.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from kaos.contracts.artifact import Artifact
from kaos.contracts.context import Context
from kaos.contracts.llm import LLMProvider, Message
from kaos.contracts.tool import Tool

ARTIFACT_KIND = "dev.session"
TASK_EVENT = "dev.task"

_PROTOCOL = (
    "Sos un desarrollador del equipo (Dev Agent) que trabaja sobre un repositorio.\n"
    "Trabajás por pasos usando herramientas. En CADA turno respondé con UN ÚNICO "
    "objeto JSON VÁLIDO en una sola línea, sin texto extra y sin comillas triples, "
    "con una de estas formas:\n"
    '  {"action":"tool","tool":"<nombre>","args":{...}}  para usar una herramienta\n'
    '  {"action":"final","answer":"<markdown>"}          cuando ya podés concluir\n'
    "Reglas IMPORTANTES:\n"
    "- Antes de concluir, USÁ al menos una herramienta para verificar; no inventes "
    "rutas ni contenido de archivos.\n"
    "- Empezá explorando (list_dir / search_code / read_file) según la tarea.\n"
    "- Usá la mínima cantidad de pasos y comillas dobles válidas en el JSON.\n"
    "- Cuando tengas la respuesta, devolvé action=final con un informe claro en "
    "Markdown (qué encontraste, conclusión y próximos pasos).\n"
    "Herramientas disponibles:\n"
)

# Public alias: the stable base prompt (tools are appended at run time). Exposed
# so the console can display the Dev Agent's base prompt in the Agents view.
BASE_PROMPT = _PROTOCOL


def _extract_json(text: str) -> dict[str, Any] | None:
    """Return the first balanced ``{...}`` object parsed from ``text``, or None."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    return parsed if isinstance(parsed, dict) else None
        start = text.find("{", start + 1)
    return None


class DevAgent:
    """Runs a bounded tool-use loop to accomplish a development task."""

    name = "dev-agent"

    def __init__(
        self,
        llm: LLMProvider,
        tools: Sequence[Tool],
        *,
        max_steps: int = 8,
        require_tool_before_final: bool = True,
    ) -> None:
        self._llm = llm
        self._tools = list(tools)
        self._by_name = {t.name: t for t in self._tools}
        self._max_steps = max_steps
        self._require_tool_before_final = require_tool_before_final

    def accepts(self, context: Context) -> bool:
        """Accept a context that carries a dev task."""
        if str(context.params.get("task", "")).strip():
            return True
        return any(e.type == TASK_EVENT for e in context.events)

    def _system_prompt(self) -> str:
        tools = "\n".join(f"- {t.name}: {t.description}" for t in self._tools)
        return _PROTOCOL + tools

    @staticmethod
    def _task_of(context: Context) -> str:
        task = str(context.params.get("task", "")).strip()
        if task:
            return task
        for event in context.events:
            if event.type == TASK_EVENT:
                return str(event.payload.get("task", "")).strip()
        return ""

    async def run(self, context: Context) -> Sequence[Artifact]:
        """Execute the tool-use loop and return one dev-session artifact."""
        task = self._task_of(context)
        if not task:
            return []

        messages = [
            Message(role="system", content=self._system_prompt()),
            Message(role="user", content=f"TAREA: {task}"),
        ]
        steps: list[dict[str, Any]] = []
        final_answer: str | None = None
        used_tool = False

        for step_i in range(self._max_steps):
            raw = await self._llm.complete(messages)
            data = _extract_json(raw)
            if data is None:
                steps.append({"error": "formato inválido", "raw": raw[:500]})
                messages.append(Message(role="assistant", content=raw))
                messages.append(
                    Message(
                        role="user",
                        content="Formato inválido. Respondé SOLO con el objeto JSON indicado.",
                    )
                )
                continue

            action = data.get("action")
            if action == "final":
                # Force at least one tool use before concluding, so small models
                # inspect the repo instead of hallucinating an answer.
                if (
                    self._require_tool_before_final
                    and not used_tool
                    and step_i < self._max_steps - 1
                ):
                    steps.append({"note": "final rechazado: aún no se usó una herramienta"})
                    messages.append(Message(role="assistant", content=raw))
                    messages.append(
                        Message(
                            role="user",
                            content=(
                                "Todavía no verificaste nada. Antes de concluir DEBÉS usar "
                                "al menos una herramienta (p. ej. read_file, list_dir o "
                                "search_code). No inventes: usá una herramienta ahora."
                            ),
                        )
                    )
                    continue
                final_answer = str(data.get("answer", "")).strip()
                steps.append({"action": "final"})
                break

            if action == "tool":
                tool_name = str(data.get("tool", ""))
                raw_args = data.get("args")
                args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
                tool = self._by_name.get(tool_name)
                if tool is None:
                    observation = (
                        f"error: herramienta desconocida '{tool_name}'. "
                        f"Disponibles: {', '.join(self._by_name)}"
                    )
                else:
                    observation = await tool.run(args)
                    used_tool = True
                steps.append(
                    {"tool": tool_name, "args": args, "observation": observation}
                )
                messages.append(Message(role="assistant", content=raw))
                messages.append(
                    Message(role="user", content=f"OBSERVACIÓN:\n{observation}")
                )
                continue

            # Unknown action shape — nudge the model back to the protocol.
            steps.append({"error": "acción desconocida", "raw": raw[:500]})
            messages.append(Message(role="assistant", content=raw))
            messages.append(
                Message(
                    role="user",
                    content='Usá "action":"tool" o "action":"final".',
                )
            )

        if final_answer is None:
            # Hit the step limit: force a final synthesis from what we gathered.
            messages.append(
                Message(
                    role="user",
                    content=(
                        "Alcanzaste el límite de pasos. Devolvé AHORA tu respuesta "
                        'final en JSON {"action":"final","answer":"..."} con un '
                        "informe en Markdown de lo hallado y próximos pasos."
                    ),
                )
            )
            raw = await self._llm.complete(messages)
            data = _extract_json(raw)
            final_answer = (
                str(data.get("answer", "")).strip()
                if data and data.get("answer")
                else raw.strip()
            )

        return [self._to_artifact(context, task, final_answer, steps)]

    def _to_artifact(
        self,
        context: Context,
        task: str,
        final_answer: str,
        steps: list[dict[str, Any]],
    ) -> Artifact:
        tool_steps = [s for s in steps if "tool" in s]
        return Artifact(
            kind=ARTIFACT_KIND,
            workspace=context.workspace,
            produced_by=self.name,
            content={
                "summary": self._compose_summary(task, final_answer, tool_steps),
                "format": "markdown",
                "task": task,
                "answer": final_answer or "(sin respuesta)",
                "steps": steps,
                "step_count": len(tool_steps),
            },
            source_events=tuple(event.id for event in context.events),
            metadata={
                "model": getattr(self._llm, "name", ""),
                "tools": [t.name for t in self._tools],
                "max_steps": self._max_steps,
            },
        )

    @staticmethod
    def _compose_summary(
        task: str, final_answer: str, tool_steps: list[dict[str, Any]]
    ) -> str:
        """Build a Markdown report so the dashboard renders the session nicely."""
        actions = "\n".join(
            f"- `{s.get('tool')}` {json.dumps(s.get('args', {}), ensure_ascii=False)}"
            for s in tool_steps
        )
        return (
            "# 🛠️ Dev Agent\n\n"
            f"## Tarea\n{task}\n\n"
            f"## Resultado\n{final_answer or '(sin respuesta)'}\n\n"
            f"## Acciones ({len(tool_steps)})\n{actions or '_sin herramientas usadas_'}\n"
        )

