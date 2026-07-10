"""Tool contract: a capability an agent can invoke during a run.

Tools are how an *active* agent (a teammate) goes beyond producing text: it can
read files, search code, run whitelisted commands, etc. Each tool exposes a
stable ``name`` and a human-readable ``description`` (shown to the model so it
can decide when to use it) and returns a string *observation*.

The Core stays agnostic: agents depend only on this contract, and concrete tools
live in plugins. Tools are responsible for their own safety (path confinement,
command allowlists, timeouts).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """A named capability that returns a textual observation."""

    name: str
    description: str

    async def run(self, args: dict[str, Any]) -> str:
        """Execute the tool with ``args`` and return an observation string."""
        ...

