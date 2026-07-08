"""OpenAI-compatible LLM provider.

Implements the `LLMProvider` contract against any OpenAI-compatible
``/chat/completions`` endpoint: OpenAI, Azure OpenAI, GitHub Models, local
servers (Ollama, LM Studio), etc. This keeps KAOS AI Provider Agnostic — the
Core never depends on a specific provider, only on the contract.

Example (GitHub Models):

    provider = OpenAICompatibleLLMProvider.github_models(token=os.environ["GITHUB_TOKEN"])
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence

import httpx

from kaos.contracts.llm import Message

OPENAI_BASE_URL = "https://api.openai.com/v1"
GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"
_RATE_LIMITED = 429
_MAX_WAIT_SECONDS = 65.0


class OpenAICompatibleLLMProvider:
    """Provider backed by an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = OPENAI_BASE_URL,
        *,
        name: str = "openai-compatible",
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._name = name
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client
        self._owns_client = client is None

    @classmethod
    def github_models(
        cls,
        token: str,
        model: str = "gpt-4o-mini",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> OpenAICompatibleLLMProvider:
        """Build a provider pointing at GitHub Models (auth via a GitHub token)."""
        return cls(
            model=model,
            api_key=token,
            base_url=GITHUB_MODELS_BASE_URL,
            name="github-models",
            client=client,
        )

    @property
    def name(self) -> str:
        return self._name

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def complete(self, messages: Sequence[Message], **options: object) -> str:
        """Return the model completion, retrying on 429 rate limits."""
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            **options,
        }
        client = self._get_client()
        url = f"{self._base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(self._max_retries + 1):
            response = await client.post(url, json=payload, headers=headers)
            if response.status_code == _RATE_LIMITED and attempt < self._max_retries:
                await asyncio.sleep(self._retry_after(response))
                continue
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        response.raise_for_status()  # pragma: no cover - safety net
        return ""

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        """Seconds to wait before retrying, from headers or the error body."""
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(float(header), _MAX_WAIT_SECONDS)
            except ValueError:
                pass
        match = re.search(r"wait (\d+) second", response.text)
        if match:
            return min(float(match.group(1)) + 1.0, _MAX_WAIT_SECONDS)
        return 5.0

    async def aclose(self) -> None:
        """Close the underlying client if this provider created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

