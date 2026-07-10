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
ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-haiku-latest"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"
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
        timeout: float = 120.0,
    ) -> OpenAICompatibleLLMProvider:
        """Build a provider pointing at GitHub Models (auth via a GitHub token).

        The default timeout is generous because reasoning models (e.g. gpt-5)
        can take well over 30s to respond.
        """
        return cls(
            model=model,
            api_key=token,
            base_url=GITHUB_MODELS_BASE_URL,
            name="github-models",
            client=client,
            timeout=timeout,
        )

    @classmethod
    def anthropic(
        cls,
        api_key: str,
        model: str = DEFAULT_ANTHROPIC_MODEL,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> OpenAICompatibleLLMProvider:
        """Build a provider for Claude via Anthropic's OpenAI-compatible endpoint.

        Anthropic exposes an OpenAI-compatible ``/chat/completions`` API, so
        Claude models (e.g. ``claude-3-5-haiku-latest``) work through the same
        contract without a dedicated client.
        """
        return cls(
            model=model,
            api_key=api_key,
            base_url=ANTHROPIC_BASE_URL,
            name="anthropic",
            client=client,
            timeout=timeout,
        )

    @classmethod
    def ollama(
        cls,
        model: str = DEFAULT_OLLAMA_MODEL,
        *,
        base_url: str = OLLAMA_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> OpenAICompatibleLLMProvider:
        """Build a provider for a local Ollama server (OpenAI-compatible API).

        Ollama runs models locally and ignores the auth header, so **no secret is
        needed** — ideal for offline dogfooding and iterating on new agents at
        zero cost. Start it with ``docker compose up -d ollama`` and pull a model
        (``ollama pull llama3.2:3b``). The default endpoint assumes KAOS runs on
        the host; override ``base_url`` (``KAOS_LLM_BASE_URL``) if not.
        """
        return cls(
            model=model,
            api_key="ollama",  # ignored by Ollama; kept for the Bearer header
            base_url=base_url,
            name="ollama",
            client=client,
            timeout=timeout,
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

