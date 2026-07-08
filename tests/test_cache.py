"""Tests for the summary cache."""

from __future__ import annotations

import asyncio

from kaos.contracts.artifact import Artifact
from kaos.core.cache import (
    CONTENT_HASH,
    MODEL,
    THREAD_ID,
    SummaryCache,
    content_fingerprint,
)
from kaos.runtime import InMemoryStorage


def test_fingerprint_is_stable_and_order_sensitive() -> None:
    a = content_fingerprint(["1", "2", "3"])
    assert a == content_fingerprint(["1", "2", "3"])  # deterministic
    assert a != content_fingerprint(["1", "2"])  # a removed message changes it
    assert a != content_fingerprint(["1", "2", "4"])  # a new message changes it
    assert a != content_fingerprint(["3", "2", "1"])  # order matters


def _summary(workspace: str, thread_id: str, fp: str) -> Artifact:
    return Artifact(
        kind="conversation.summary",
        workspace=workspace,
        produced_by="resume-agent",
        content={"summary": "# ok"},
        metadata={THREAD_ID: thread_id, CONTENT_HASH: fp},
    )


def test_cache_hit_returns_matching_summary() -> None:
    storage = InMemoryStorage()
    fp = content_fingerprint(["1", "2"])
    asyncio.run(storage.save_artifact(_summary("w1", "t1", fp)))
    cache = SummaryCache(storage)

    hit = asyncio.run(cache.get("w1", "t1", fp))
    assert hit is not None
    assert hit.metadata[THREAD_ID] == "t1"


def test_cache_miss_on_changed_content() -> None:
    storage = InMemoryStorage()
    asyncio.run(storage.save_artifact(_summary("w1", "t1", content_fingerprint(["1"]))))
    cache = SummaryCache(storage)

    # Same thread, different fingerprint (a new message arrived) -> miss.
    miss = asyncio.run(cache.get("w1", "t1", content_fingerprint(["1", "2"])))
    assert miss is None


def test_cache_miss_on_other_thread_or_workspace() -> None:
    storage = InMemoryStorage()
    fp = content_fingerprint(["1"])
    asyncio.run(storage.save_artifact(_summary("w1", "t1", fp)))
    cache = SummaryCache(storage)

    assert asyncio.run(cache.get("w1", "t2", fp)) is None
    assert asyncio.run(cache.get("w2", "t1", fp)) is None


def test_cache_ignores_non_summary_artifacts() -> None:
    storage = InMemoryStorage()
    fp = content_fingerprint(["1"])
    other = Artifact(
        kind="project.status",
        workspace="w1",
        produced_by="resume-agent",
        metadata={THREAD_ID: "t1", CONTENT_HASH: fp},
    )
    asyncio.run(storage.save_artifact(other))
    cache = SummaryCache(storage)

    assert asyncio.run(cache.get("w1", "t1", fp)) is None


def _summary_with_model(workspace: str, thread_id: str, fp: str, model: str) -> Artifact:
    return Artifact(
        kind="conversation.summary",
        workspace=workspace,
        produced_by="resume-agent",
        content={"summary": "# ok"},
        metadata={THREAD_ID: thread_id, CONTENT_HASH: fp, MODEL: model},
    )


def test_cache_miss_when_model_differs() -> None:
    storage = InMemoryStorage()
    fp = content_fingerprint(["1", "2"])
    asyncio.run(storage.save_artifact(_summary_with_model("w1", "t1", fp, "gpt-4o-mini")))
    cache = SummaryCache(storage)

    # Same content, different model -> miss (knowledge is model-specific).
    assert asyncio.run(cache.get("w1", "t1", fp, "gpt-5")) is None
    # Same model -> hit.
    hit = asyncio.run(cache.get("w1", "t1", fp, "gpt-4o-mini"))
    assert hit is not None
    assert hit.metadata[MODEL] == "gpt-4o-mini"


def test_cache_model_none_matches_any() -> None:
    storage = InMemoryStorage()
    fp = content_fingerprint(["1"])
    asyncio.run(storage.save_artifact(_summary_with_model("w1", "t1", fp, "gpt-5")))
    cache = SummaryCache(storage)

    # Backward compatible: without a model filter, any stored summary matches.
    assert asyncio.run(cache.get("w1", "t1", fp)) is not None


