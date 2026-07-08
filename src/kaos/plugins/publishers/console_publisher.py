"""Console Publisher: exposes artifacts by printing them to a stream.

The simplest possible Publisher, useful for `kaos up`, demos and dogfooding.
"""

from __future__ import annotations

import sys
from typing import TextIO

from kaos.contracts.artifact import Artifact


class ConsolePublisher:
    """Prints artifacts to a text stream (stdout by default)."""

    name = "console-publisher"

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout

    async def publish(self, artifact: Artifact) -> None:
        """Render the artifact to the stream."""
        header = (
            f"[{artifact.kind}] workspace={artifact.workspace} "
            f"by={artifact.produced_by}"
        )
        print(header, file=self._stream)
        count = artifact.content.get("message_count")
        if count is not None:
            print(f"({count} mensajes)", file=self._stream)
        summary = artifact.content.get("summary")
        if summary:
            print(summary, file=self._stream)
        print("-" * 48, file=self._stream)

