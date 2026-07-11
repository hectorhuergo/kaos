"""RuntimeConfig: the persisted, non-secret runtime selections.

Secrets (API keys, tokens, DSNs) always live in the environment. But *which*
LLM provider and model KAOS should use is domain/config state: the operator can
change it at runtime (from the web console) and the choice must survive
restarts. This mirrors :class:`Subscription` — durable state, never a secret.

There is a single active configuration, keyed by :data:`SINGLETON` in the store.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from kaos.contracts.event import utcnow

# The store keeps a single row; this is its stable key.
SINGLETON = "default"


class RuntimeConfig(BaseModel):
    """The active, persisted runtime selection (provider + model)."""

    llm_provider: str = "echo"
    llm_model: str = "gpt-4o-mini"
    # Per-agent extra prompt instructions (by agent id). Non-secret, durable
    # runtime state: the operator augments an agent's prompt from the console and
    # the choice must survive restarts, just like the provider/model selection.
    agent_instructions: dict[str, str] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)

