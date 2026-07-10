"""A Publisher that captures artifacts instead of sending them anywhere.

Used for **dry-run previews** (show the summary in the web console without
publishing to Discord) and in tests. It performs no I/O, so a real Discord token
in the environment is never used to post.
"""

from __future__ import annotations

from kaos.contracts.artifact import Artifact


class CapturingPublisher:
    """Collects published artifacts in memory; sends nothing."""

    name = "capturing-publisher"

    def __init__(self) -> None:
        self.published: list[Artifact] = []

    async def publish(self, artifact: Artifact) -> None:
        self.published.append(artifact)

