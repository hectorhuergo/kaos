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
from kaos.core.chunking import estimate_tokens, group_by_token_budget
from kaos.core.redaction import redact_secrets

ARTIFACT_KIND = "conversation.summary"
CONVERSATION_COMPLETED = "conversation.completed"

# Bump when the prompt OR the transcript render changes in a way that should
# invalidate cached summaries. Folded into ``prompt_signature`` so downstream
# caches recompute instead of serving knowledge produced by an older contract.
# v2: the transcript now prefixes each message with its ISO-8601 timestamp and
# the prompt asks the model to use those dates.
# v3: oversized conversations are summarized via map-reduce (ADR-0024); the
# result for a large thread can differ from a single-shot summary.
PROMPT_VERSION = "3"

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

# Map step: turn one chunk of the conversation into concise notes (not the final
# structured report). Kept short so partial notes stay small and recombine well.
MAP_PROMPT = (
    "Eres un analista. Resume el siguiente fragmento de una conversación de "
    "trabajo en notas concisas en viñetas, preservando estado, decisiones, "
    "riesgos y próximos pasos que aparezcan. No inventes nada que no esté en el "
    "texto. Devuelve solo las viñetas, sin encabezados."
)

# Reduce step: the user content that precedes the concatenated partial notes so
# the model synthesizes a single report (using the structured SYSTEM_PROMPT).
REDUCE_USER_PREFIX = (
    "A continuación hay notas parciales, en orden, de distintos tramos de la "
    "MISMA conversación (fue dividida por tamaño). Sintetiza UN único informe "
    "ejecutivo coherente que integre todos los tramos sin repetir secciones:\n\n"
)

# Consolidation: the user content that precedes several per-thread summaries so
# the model fuses them into ONE unified executive report (not N stacked reports).
CONSOLIDATE_USER_PREFIX = (
    "A continuación hay resúmenes ejecutivos, uno por hilo/canal del MISMO "
    "proyecto. Sintetiza UN único informe ejecutivo consolidado que unifique el "
    "estado, las decisiones, los riesgos y los próximos pasos de todos los hilos "
    "en un solo flujo coherente. NO crees una sección por hilo ni repitas los "
    "encabezados: integra y deduplica la información:\n\n"
)

# Guards for the per-request input budget derived from the context window.
_OUTPUT_RESERVE_RATIO = 0.35  # leave room for the model's own answer
_SAFETY_MARGIN_TOKENS = 128
_MIN_CHUNK_TOKENS = 256
# Budget used when consolidating without a known context window: effectively
# unbounded, so per-thread summaries are fused in a single reduce call.
_UNBOUNDED_BUDGET = 1_000_000



class ResumeAgent:
    """Summarizes a conversation into an executive Markdown report.

    Triggers once the conversation is complete (a ``conversation.completed``
    event) and summarizes all the ``message.*`` events accumulated for the
    workspace, so a conversation produces a single summary.
    """

    name = "resume-agent"

    def __init__(
        self,
        llm: LLMProvider,
        *,
        extra_instructions: str = "",
        agent_id: str | None = None,
        context_tokens: int | None = None,
    ) -> None:
        self._llm = llm
        self._extra_instructions = extra_instructions.strip()
        # The agent this run is attributed to. Defaults to the resume-agent
        # identity; a subscription/console run may select another agent, which is
        # stamped on the artifact so surfaces (dashboards, metrics) attribute the
        # knowledge to the chosen agent.
        self._agent_id = (agent_id or "").strip() or None
        # The model's context window (tokens), if known. When set and a
        # conversation would overflow it, the agent summarizes via map-reduce
        # (ADR-0024) instead of sending an oversized prompt. ``None`` keeps the
        # single-shot behaviour (backward compatible).
        self._context_tokens = context_tokens if context_tokens and context_tokens > 0 else None

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
        material = f"{PROMPT_VERSION}\n{self._system_prompt()}\n{self._context_tokens or 0}"
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

        summary = await self._summarize(messages)

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

    async def _summarize(self, events: Sequence[Event]) -> str:
        """Summarize a conversation, chunking via map-reduce when it overflows.

        With a known ``context_tokens`` budget, a conversation whose transcript
        would exceed the model's usable input is split into ordered chunks: each
        chunk is condensed into notes (*map*) and the notes are synthesized into
        one coherent executive report (*reduce*). This keeps the required Markdown
        structure intact — unlike concatenating partial summaries — and works on
        servers with a small, fixed context window (e.g. llama.cpp/Lemonade).
        """
        budget = self._input_budget()
        transcript = self._render(events)
        if budget is None or estimate_tokens(transcript) <= budget:
            return await self._llm.complete(
                [
                    Message(role="system", content=self._system_prompt()),
                    Message(role="user", content=transcript),
                ]
            )
        return await self._summarize_chunked(events, budget)

    def _input_budget(self) -> int | None:
        """Tokens available for the user content of one request, or ``None``.

        Derived from the context window minus the system prompt, a reserve for
        the model's own answer and a safety margin. ``None`` disables chunking.
        """
        if self._context_tokens is None:
            return None
        system_tokens = estimate_tokens(self._system_prompt())
        reserve_output = max(_MIN_CHUNK_TOKENS, int(self._context_tokens * _OUTPUT_RESERVE_RATIO))
        budget = self._context_tokens - system_tokens - reserve_output - _SAFETY_MARGIN_TOKENS
        return max(_MIN_CHUNK_TOKENS, budget)

    async def _summarize_chunked(self, events: Sequence[Event], budget: int) -> str:
        """Map each chunk of events to notes, then reduce notes to one report."""
        chunks = group_by_token_budget(
            events, lambda e: estimate_tokens(self._render_one(e)), budget
        )
        notes: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            note = await self._llm.complete(
                [
                    Message(role="system", content=MAP_PROMPT),
                    Message(
                        role="user",
                        content=f"Fragmento {index}/{len(chunks)}:\n\n{self._render(chunk)}",
                    ),
                ]
            )
            notes.append(redact_secrets(note.strip()))
        return await self._reduce_notes(notes, budget)

    async def consolidate(self, summaries: Sequence[str]) -> str:
        """Fuse several per-thread summaries into ONE unified executive report.

        Unlike concatenating the per-thread summaries (which yields N stacked
        reports), this runs a *reduce* pass so the model synthesizes a single
        coherent report that unifies state, decisions, risks and next steps
        across every thread — respecting the agent's own structured prompt and
        any user ``extra_instructions``. When a small ``context_tokens`` window
        is known, the reduce is hierarchical so it fits (ADR-0024); otherwise it
        is a single call (backward compatible). The result is redacted before it
        becomes a published artifact.
        """
        notes = [s.strip() for s in summaries if s and s.strip()]
        if not notes:
            return ""
        if len(notes) == 1:
            return redact_secrets(notes[0])
        budget = self._input_budget()
        fused = await self._reduce_notes(
            notes,
            budget if budget is not None else _UNBOUNDED_BUDGET,
            prefix=CONSOLIDATE_USER_PREFIX,
        )
        return redact_secrets(fused)

    async def _reduce_notes(
        self, notes: list[str], budget: int, *, prefix: str = REDUCE_USER_PREFIX
    ) -> str:
        """Synthesize partial notes into the final structured report.

        If the concatenated notes still overflow the budget, they are first
        condensed in groups (a hierarchical reduce) until they fit, so very long
        conversations converge instead of overflowing the context again.

        ``prefix`` is the user-content lead-in that frames the reduce for the
        model (map-reduce of one conversation vs. consolidation across threads).
        """
        combined = self._join_notes(notes)
        if len(notes) > 1 and estimate_tokens(combined) > budget:
            groups = group_by_token_budget(notes, estimate_tokens, budget)
            merged: list[str] = []
            for group in groups:
                condensed = await self._llm.complete(
                    [
                        Message(role="system", content=MAP_PROMPT),
                        Message(role="user", content=self._join_notes(group)),
                    ]
                )
                merged.append(redact_secrets(condensed.strip()))
            return await self._reduce_notes(merged, budget, prefix=prefix)
        return await self._llm.complete(
            [
                Message(role="system", content=self._system_prompt()),
                Message(role="user", content=f"{prefix}{combined}"),
            ]
        )

    @staticmethod
    def _join_notes(notes: Sequence[str]) -> str:
        """Concatenate partial notes, labelling each tramo to keep order clear."""
        return "\n\n".join(f"— Tramo {i}:\n{note}" for i, note in enumerate(notes, start=1))


    def _origin_metadata(self, events: Sequence[Event]) -> dict[str, str]:
        """Metadata carried on the summary: origin channel + attributed agent."""
        meta = dict(self._channel_metadata(events))
        if self._agent_id:
            meta["agent_id"] = self._agent_id
        return meta

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
    def _channel_metadata(events: Sequence[Event]) -> dict[str, str]:
        """Carry the originating channel forward when unambiguous."""
        channels = {
            str(e.payload["channel_id"]) for e in events if e.payload.get("channel_id")
        }
        return {"channel_id": next(iter(channels))} if len(channels) == 1 else {}

    @staticmethod
    def _render_one(event: Event) -> str:
        """Render a single message event as one transcript line (unredacted).

        Used to estimate a message's token size when chunking; the full
        :meth:`_render` applies redaction to the joined transcript.
        """
        author = event.payload.get("author", "unknown")
        text = event.payload.get("text", "")
        timestamp = event.payload.get("timestamp")
        prefix = f"[{timestamp}] " if timestamp else ""
        return f"{prefix}{author}: {text}"

    @staticmethod
    def _render(events: Sequence[Event]) -> str:
        """Render the conversation as a plain transcript for the LLM.

        Each line is prefixed with the message timestamp (ISO-8601) when the
        event carries one, so the model can reference real dates instead of
        inventing them. Secrets are redacted here so they never leave KAOS
        towards the LLM provider (Immutable Evidence keeps the raw event; only
        the derived transcript is scrubbed).
        """
        lines = [ResumeAgent._render_one(event) for event in events]
        return redact_secrets("\n".join(lines))

