"""Testing doubles for building and testing KAOS plugins.

These helpers let plugin authors (and KAOS itself, via dogfooding) exercise
Agents without a real AI provider or external system.
"""

from __future__ import annotations

from collections.abc import Sequence

from kaos.contracts.llm import Message


class EchoLLMProvider:
    """A deterministic LLMProvider double.

    Returns a fixed ``response`` when provided; otherwise echoes back the
    content of the last non-system message. Useful for testing Agents that
    depend on the LLMProvider contract without calling a real provider.
    """

    name = "echo-llm"

    def __init__(self, response: str | None = None) -> None:
        self._response = response
        self.calls: list[list[Message]] = []

    async def complete(self, messages: Sequence[Message], **options: object) -> str:
        self.calls.append(list(messages))
        if self._response is not None:
            return self._response
        for message in reversed(messages):
            if message.role != "system":
                return message.content
        return ""

