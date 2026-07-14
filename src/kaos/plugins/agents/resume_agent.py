"""Resume Agent: the first KAOS agent.

Consumes the message events of a conversation and produces an executive summary
in Markdown. It depends only on the `LLMProvider` contract, so it stays AI
Provider Agnostic, and every artifact traces back to the events it summarizes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from kaos.contracts.artifact import Artifact
from kaos.contracts.context import Context
from kaos.contracts.event import Event
from kaos.contracts.llm import LLMProvider, Message
from kaos.core.redaction import redact_secrets

ARTIFACT_KIND = "conversation.summary"
CONVERSATION_COMPLETED = "conversation.completed"

# Bump when the prompt OR the transcript render changes in a way that should
# invalidate cached summaries. Folded into ``prompt_signature`` so downstream
# caches recompute instead of serving knowledge produced by an older contract.
# v2: the transcript now prefixes each message with its ISO-8601 timestamp and
# the prompt asks the model to use those dates.
PROMPT_VERSION = "2"

SYSTEM_PROMPT = (
    "Eres un analista que produce resúmenes ejecutivos de conversaciones de "
    "trabajo. Devuelve SOLO Markdown con exactamente estas secciones:\n"
    "# Resumen Ejecutivo\n"
    "## Estado\n"
    "## Decisiones\n"
    "## Riesgos\n"
    "## Próximos pasos\n"
    "Sé conciso, usa viñetas y no inventes información que no esté en la "
    "conversación. Cada mensaje puede venir prefijado con su fecha y hora en "
    "formato ISO-8601 entre corchetes (p. ej. [2026-07-08T14:30:00+00:00]); "
    "usa esas marcas para calcular correctamente las fechas y horas de los "
    "eventos al incluirlas en el resumen, y no inventes fechas si no están."
)


class ResumeAgent:
    """Summarizes a conversation into an executive Markdown report.

    Triggers once the conversation is complete (a ``conversation.completed``
    event) and summarizes all the ``message.*`` events accumulated for the
    workspace, so a conversation produces a single summary.
    """

    name = "resume-agent"

    def __init__(self, llm: LLMProvider, *, extra_instructions: str = "") -> None:
        self._llm = llm
        self._extra_instructions = extra_instructions.strip()

    def _system_prompt(self) -> str:
        """The base prompt, optionally augmented with user instructions.

        Extra instructions are appended (never replace the base prompt) so the
        required Markdown structure is preserved while letting the user steer the
        focus/tone of the summary from the console or CLI.
        """
        if not self._extra_instructions:
            return SYSTEM_PROMPT
        return (
            f"{SYSTEM_PROMPT}\n\n"
            "Instrucciones adicionales del usuario (respétalas siempre que no "
            "contradigan el formato y las secciones pedidas):\n"
            f"{self._extra_instructions}"
        )

    def prompt_signature(self) -> str:
        """Short, stable hash identifying the prompt actually used.

        Captures the base prompt, any user ``extra_instructions`` and the
        ``PROMPT_VERSION`` (which tracks render-only changes such as adding
        timestamps to the transcript). Caches fold this into their fingerprint so
        a change here invalidates summaries produced under an older prompt.
        """
        material = f"{PROMPT_VERSION}\n{self._system_prompt()}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _is_message(event_type: str) -> bool:
        return event_type.startswith("message.")

    def accepts(self, context: Context) -> bool:
        """Accept a context that signals a completed conversation."""
        return any(event.type == CONVERSATION_COMPLETED for event in context.events)

    async def run(self, context: Context) -> Sequence[Artifact]:
        """Produce a single summary artifact for the conversation."""
        messages = [e for e in context.events if self._is_message(e.type)]
        if not messages:
            return []

        summary = await self._llm.complete(
            [
                Message(role="system", content=self._system_prompt()),
                Message(role="user", content=self._render(messages)),
            ]
        )

        # Belt-and-suspenders: scrub any secret the LLM may have echoed back
        # before the summary becomes a published, immutable artifact.
        summary = redact_secrets(summary)

        return [
            Artifact(
                kind=ARTIFACT_KIND,
                workspace=context.workspace,
                produced_by=self.name,
                content={
                    "summary": summary,
                    "format": "markdown",
                    "message_count": len(messages),
                    "messages": self._transcript(messages),
                },
                source_events=tuple(event.id for event in messages),
                metadata=self._origin_metadata(messages),
            )
        ]

    @staticmethod
    def _transcript(events: Sequence[Event]) -> list[dict[str, str]]:
        """Embed the originating messages so the thread travels with the summary.

        Keeping the transcript inside the artifact makes the knowledge
        self-contained: any surface (e.g. the chat history) can show the full
        thread that produced a summary without depending on the raw events still
        living in storage — which the forum path never persists. Text is redacted
        so a published artifact never leaks a secret (the raw event remains the
        immutable evidence elsewhere).
        """
        out: list[dict[str, str]] = []
        for event in events:
            out.append(
                {
                    "author": str(event.payload.get("author", "unknown")),
                    "text": redact_secrets(str(event.payload.get("text", ""))),
                    "timestamp": str(event.payload.get("timestamp") or ""),
                }
            )
        return out

    @staticmethod
    def _origin_metadata(events: Sequence[Event]) -> dict[str, str]:
        """Carry the originating channel forward when unambiguous."""
        channels = {
            str(e.payload["channel_id"]) for e in events if e.payload.get("channel_id")
        }
        return {"channel_id": next(iter(channels))} if len(channels) == 1 else {}

    @staticmethod
    def _render(events: Sequence[Event]) -> str:
        """Render the conversation as a plain transcript for the LLM.

        Each line is prefixed with the message timestamp (ISO-8601) when the
        event carries one, so the model can reference real dates instead of
        inventing them. Secrets are redacted here so they never leave KAOS
        towards the LLM provider (Immutable Evidence keeps the raw event; only
        the derived transcript is scrubbed).
        """
        lines = []
        for event in events:
            author = event.payload.get("author", "unknown")
            text = event.payload.get("text", "")
            timestamp = event.payload.get("timestamp")
            prefix = f"[{timestamp}] " if timestamp else ""
            lines.append(f"{prefix}{author}: {text}")
        return redact_secrets("\n".join(lines))

