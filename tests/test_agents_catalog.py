"""Tests for the agent catalog and the subscription runner registry."""

from __future__ import annotations

from kaos.cli.subscriptions import SUBSCRIPTION_RUNNERS
from kaos.core.agents import AGENT_CATALOG, agent_catalog
from kaos.domain.subscription import CHANNEL, FORUM, GITHUB, KINDS


def test_agent_catalog_lists_shipped_agents() -> None:
    ids = {a.id for a in agent_catalog()}
    assert {"resume-agent", "dev-agent"} <= ids
    assert agent_catalog() is AGENT_CATALOG


def test_agent_catalog_entries_are_well_formed() -> None:
    for agent in agent_catalog():
        assert agent.id and agent.label and agent.description
        assert agent.produces  # every agent declares the artifact it emits
        assert isinstance(agent.augmentable, bool)


def test_subscription_runners_cover_every_kind() -> None:
    # The dispatch registry must have a runner for every supported kind, so a
    # new kind fails loudly here instead of silently falling through.
    assert set(SUBSCRIPTION_RUNNERS) == {FORUM, CHANNEL, GITHUB}
    assert set(SUBSCRIPTION_RUNNERS) <= set(KINDS)

