import logging
from datetime import datetime

from kaos.contracts.context import Context
from kaos.contracts.llm import Message, LLMProvider
from kaos.contracts.artifact import Artifact

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (  # fmt: skip
    "Eres un Agente Experto en Gestión de Proyectos y Arquitectura de Datos de KAOS.\n"
    "Tu objetivo es consolidar múltiples hilos de conversación en un único artefacto de conocimiento.\n\n"

    "CRITERIOS DE TIEMPO REQUERIDOS (OBLIGATORIO):\n"
    "1. Identifica y menciona explícitamente las fechas exactas de las reuniones o hitos discutidos.\n"
    "2. Determina el rango de fechas entre las cuales se realizaron las tareas descritas.\n"
    "3. Para cada tarea futura o siguiente paso, estima las horas requeridas y calcula/establece una fecha estimada de finalización.\n\n"

    "REGLA DE CONSOLIDACIÓN CRÍTICA:\n"
    "Aunque recibas información de múltiples hilos, canales o sesiones de chat, DEBES generar un ÚNICO Resumen Ejecutivo unificado. "
    "No fragmentes el reporte por hilos individuales. Integra toda la información cronológicamente en un solo flujo lógico.\n\n"

    "Formatea tu respuesta utilizando ESTRICTAMENTE la siguiente estructura Markdown:\n\n"

    "# RESUMEN EJECUTIVO CONSOLIDADO\n"
    "*[Inserta aquí un único resumen ejecutivo global que enlace las conclusiones de todos los hilos, "
    "completando la cronología general del proyecto y explicando el contexto actual. NO crees subsecciones por hilo]*\n\n"

    "## 🗓️ CRONOLOGÍA Y MARCO TEMPORAL\n"
    "- **Rango de ejecución de tareas:** [Fecha Inicio] al [Fecha Fin]\n"
    "- **Fechas de reuniones clave:** [Mencionar reuniones identificadas con su fecha exacta]\n\n"

    "## 🔍 ANÁLISIS DE SITUACIÓN\n"
    "- **Estado Actual:** [Breve diagnóstico del sistema o arquitectura técnica según lo conversado]\n"
    "- **Necesidades del Equipo:** [Requerimientos de infraestructura, recursos, aprobaciones o bloqueos técnicos]\n\n"

    "## 📋 PLAN DE ACCIÓN Y ASIGNACIONES\n"
    "| Tarea / Siguiente Paso | Responsable | Horas Estimadas | Fecha Est. Finalización | Estado/Notas |\n"
    "| :--- | :--- | :--- | :--- | :--- |\n"
    "| [Descripción de la tarea] | [Nombre o Rol] | [X horas] | [AAAA-MM-DD] | [Pendiente / Bloqueado / etc.] |\n\n"

    "## ⏳ TEMAS EN REVISIÓN Y PRÓXIMOS PASOS (TODO)\n"
    "- [ ] **[Hito futuro]:** [Dudas no resueltas, validaciones de arquitectura pendientes o decisiones de diseño futuras]"
)


class TaskAgent:
    """
    Agente experto de KAOS que consolida hilos en un único reporte ejecutivo,
    estimando marcos temporales y horas de trabajo futuras.
    """
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    def get_system_prompt(self) -> str:
        return SYSTEM_PROMPT

    async def run(self, context: Context) -> list[Artifact]:
        hilos = context.params.get("hilos", "")
        if not hilos:
            logger.warning("No se proporcionaron hilos para analizar.")
            return []

        fecha_actual = datetime.now().strftime("%Y-%m-%d")

        messages = [
            Message(role="system", content=self.get_system_prompt()),
            Message(role="user", content=(
                f"FECHA ACTUAL DEL SISTEMA: {fecha_actual}\n\n"
                f"RECOPILACIÓN DE HILOS A ANALIZAR:\n{hilos}"
            ))
        ]

        response = await self.llm.complete(messages)

        return [
            Artifact(
                workspace=context.workspace,
                kind="task.report",
                produced_by="task-agent",
                content={
                    "summary": "Reporte de tareas unificado temporalmente",
                    "answer": response,
                    "generated_at": fecha_actual
                }
            )
        ]
