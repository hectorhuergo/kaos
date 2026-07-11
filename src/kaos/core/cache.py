"""Summary cache: reuse conversation summaries instead of re-querying the LLM.

A conversation whose messages have not changed produces the same summary, so
there is no need to call the (rate-limited, costly) LLM again. This cache is a
thin *read-through* layer over the ``Storage`` contract: summaries already live
in Storage as artifacts, so the cache just looks one up by conversation identity
and a content fingerprint.

The Core stays agnostic of the concrete backend — with ``PostgresStorage`` the
cache survives across runs; with ``InMemoryStorage`` it lasts for the process.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from kaos.contracts.artifact import Artifact
from kaos.contracts.storage import Storage

# Metadata keys used to identify a cached summary.
THREAD_ID = "thread_id"
CONTENT_HASH = "content_hash"
MODEL = "model"

SUMMARY_KIND = "conversation.summary"


def content_fingerprint(
    message_ids: Sequence[str], *, prompt_signature: str = ""
) -> str:
    """Return a stable fingerprint for an ordered sequence of message ids.

    Two runs over the same messages yield the same fingerprint; a new or removed
    message changes it, which is exactly when the summary must be recomputed.

    ``prompt_signature`` folds the agent's prompt/render contract into the
    fingerprint: when the prompt (or its render logic) changes, previously cached
    summaries are treated as misses and recomputed. This prevents serving stale
    knowledge that was produced under an older prompt — e.g. summaries generated
    before the transcript carried per-message timestamps, which would otherwise
    keep being reused without the dates the current prompt asks for.
    """
    joined = "\n".join(str(mid) for mid in message_ids)
    if prompt_signature:
        joined = f"{joined}\n\x00prompt={prompt_signature}"
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


class SummaryCache:
    """Read-through cache of conversation summaries over a ``Storage`` backend."""

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    async def get(
        self,
        workspace: str,
        thread_id: str,
        fingerprint: str,
        model: str | None = None,
    ) -> Artifact | None:
        """Return a cached summary for a conversation, or ``None`` on a miss.

        A hit requires the same workspace, thread and content fingerprint, so a
        changed conversation is treated as a miss (and gets re-summarized). When
        ``model`` is given it must also match: knowledge produced by a different
        LLM is distinct, so switching models recomputes rather than reusing a
        summary written by another model.
        """
        for artifact in await self._storage.list_artifacts(workspace):
            if artifact.kind != SUMMARY_KIND:
                continue
            meta = artifact.metadata
            if meta.get(THREAD_ID) != thread_id or meta.get(CONTENT_HASH) != fingerprint:
                continue
            if model is not None and meta.get(MODEL) != model:
                continue
            return artifact
        return None

