"""Tests for subscriptions (domain entity + in-memory store)."""

from __future__ import annotations

import asyncio

from kaos.contracts.subscription import SubscriptionStore
from kaos.domain.subscription import CHANNEL, FORUM, GITHUB, KINDS, Subscription
from kaos.runtime import InMemorySubscriptionStore


def test_workspace_for_channel() -> None:
    assert Subscription.workspace_for("123") == "discord:123"


def test_workspace_for_github_repo() -> None:
    assert Subscription.workspace_for_github("owner/name") == "github:owner/name"


def test_workspace_for_kind_dispatches_by_kind() -> None:
    assert Subscription.workspace_for_kind(FORUM, "123") == "discord:123"
    assert Subscription.workspace_for_kind(GITHUB, "owner/name") == "github:owner/name"


def test_github_is_a_valid_kind() -> None:
    assert GITHUB in KINDS


def test_subscription_defaults_to_forum_and_active() -> None:
    sub = Subscription(workspace="discord:1", channel_id="1")
    assert sub.kind == FORUM
    assert sub.active is True


def test_in_memory_store_satisfies_contract() -> None:
    assert isinstance(InMemorySubscriptionStore(), SubscriptionStore)


def _sub(channel_id: str, kind: str = FORUM) -> Subscription:
    return Subscription(
        workspace=Subscription.workspace_for(channel_id),
        kind=kind,
        channel_id=channel_id,
        guild_id="G",
        resume_thread_id="T",
    )


def test_add_get_and_list() -> None:
    store = InMemorySubscriptionStore()

    async def scenario() -> None:
        await store.add(_sub("1"))
        await store.add(_sub("2", kind=CHANNEL))
        got = await store.get("1")
        assert got is not None and got.kind == FORUM
        active = await store.list(active_only=True)
        assert {s.channel_id for s in active} == {"1", "2"}

    asyncio.run(scenario())


def test_add_is_upsert_by_channel() -> None:
    store = InMemorySubscriptionStore()

    async def scenario() -> None:
        await store.add(_sub("1"))
        updated = _sub("1")
        updated = updated.model_copy(update={"resume_thread_id": "NEW"})
        await store.add(updated)
        got = await store.get("1")
        assert got is not None and got.resume_thread_id == "NEW"
        assert len(await store.list()) == 1  # not duplicated

    asyncio.run(scenario())


def test_interval_seconds_defaults_to_none_and_roundtrips() -> None:
    store = InMemorySubscriptionStore()

    async def scenario() -> None:
        plain = _sub("1")
        assert plain.interval_seconds is None  # default: runs every scheduler pass
        planned = _sub("2").model_copy(update={"interval_seconds": 3600})
        await store.add(plain)
        await store.add(planned)
        got = await store.get("2")
        assert got is not None and got.interval_seconds == 3600

    asyncio.run(scenario())


def test_deactivate_hides_from_active_list() -> None:
    store = InMemorySubscriptionStore()

    async def scenario() -> None:
        await store.add(_sub("1"))
        assert await store.deactivate("1") is True
        assert await store.list(active_only=True) == []
        assert len(await store.list(active_only=False)) == 1  # kept, not deleted
        assert await store.deactivate("nope") is False

    asyncio.run(scenario())


def test_publish_default_true_and_related_empty_by_default() -> None:
    sub = Subscription(workspace="discord:1", channel_id="1")
    assert sub.publish_default is True  # automated runs publish unless turned off
    assert sub.related_to == []


def test_publish_default_and_related_roundtrip() -> None:
    store = InMemorySubscriptionStore()

    async def scenario() -> None:
        sub = _sub("1").model_copy(
            update={"publish_default": False, "related_to": ["github:acme/kaos"]}
        )
        await store.add(sub)
        got = await store.get("1")
        assert got is not None
        assert got.publish_default is False
        assert got.related_to == ["github:acme/kaos"]

    asyncio.run(scenario())


def test_run_subscriptions_publishes_only_when_publish_default() -> None:
    """The scheduler run posts to Discord only for publish_default subscriptions.

    A subscription with ``publish_default=False`` is still run (real storage), but
    a capture/console publisher is injected so nothing is posted — knowledge-only.
    """
    from kaos.cli import subscriptions as subs_mod
    from kaos.plugins.publishers import ConsolePublisher

    store = InMemorySubscriptionStore()
    seen: dict[str, object] = {}

    async def fake_runner(sub, *, dry_run, consolidated, force, settings, publisher=None):  # type: ignore[no-untyped-def]
        seen[sub.channel_id] = publisher
        return 0

    async def scenario() -> None:
        await store.add(_sub("posts").model_copy(update={"publish_default": True}))
        await store.add(_sub("quiet").model_copy(update={"publish_default": False}))

    asyncio.run(scenario())

    import kaos.bootstrap.factory as factory

    original = factory.build_subscription_store
    factory.build_subscription_store = lambda _s: store  # type: ignore[assignment]
    subs_mod.build_subscription_store = lambda _s: store  # type: ignore[assignment]
    runners = dict(subs_mod.SUBSCRIPTION_RUNNERS)
    subs_mod.SUBSCRIPTION_RUNNERS.update({FORUM: fake_runner})
    try:
        from kaos.core.config import Settings

        asyncio.run(subs_mod.run_subscriptions(settings=Settings(discord_token="t")))
    finally:
        factory.build_subscription_store = original  # type: ignore[assignment]
        subs_mod.build_subscription_store = original  # type: ignore[assignment]
        subs_mod.SUBSCRIPTION_RUNNERS.clear()
        subs_mod.SUBSCRIPTION_RUNNERS.update(runners)

    # publish_default → default publisher (None, backfill posts); else console.
    assert seen["posts"] is None
    assert isinstance(seen["quiet"], ConsolePublisher)


