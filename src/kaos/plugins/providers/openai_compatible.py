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
import contextlib
import re
from collections.abc import Callable, Sequence

import httpx

from kaos.contracts.llm import LLMError, Message

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
        extra_headers: dict[str, str] | None = None,
        num_ctx: int | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._name = name
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client
        self._owns_client = client is None
        self._extra_headers = extra_headers or {}
        # Context window override (tokens). Only meaningful for servers that
        # honour it (Ollama/llama.cpp): raises the default context so large
        # prompts (e.g. long conversations) are not rejected. Left ``None`` for
        # hosted providers, whose context size is fixed server-side.
        self._num_ctx = num_ctx
        self._current_task: asyncio.Task[str] | None = None

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
        num_ctx: int | None = None,
    ) -> OpenAICompatibleLLMProvider:
        """Build a provider for a local Ollama server (OpenAI-compatible API).

        Ollama runs models locally and ignores the auth header, so **no secret is
        needed** — ideal for offline dogfooding and iterating on new agents at
        zero cost. Start it with ``docker compose up -d ollama`` and pull a model
        (``ollama pull llama3.2:3b``). The default endpoint assumes KAOS runs on
        the host; override ``base_url`` (``KAOS_LLM_BASE_URL``) if not.

        ``num_ctx`` raises the context window (in tokens) beyond Ollama's small
        default (2k–4k). Local models such as Gemma 3 support far larger
        contexts, so setting this avoids ``exceeds available context size``
        rejections on long conversations without any prompt chunking.
        """
        return cls(
            model=model,
            api_key="ollama",  # ignored by Ollama; kept for the Bearer header
            base_url=base_url,
            name="ollama",
            client=client,
            timeout=timeout,
            num_ctx=num_ctx,
        )

    @property
    def name(self) -> str:
        return self._name

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _auth_token(self) -> str:
        """Return the Bearer token for the request.

        A hook so providers with short-lived tokens (e.g. GitHub Copilot) can
        mint/refresh one per call while reusing the request + retry logic.
        """
        return self._api_key

    async def complete(self, messages: Sequence[Message], **options: object) -> str:
        """Return the model completion, retrying on 429 rate limits.

        This task can be cancelled via the cancel() method for user-initiated
        interruption of long-running completions.
        """
        # Create and track the completion task so it can be cancelled externally
        task = asyncio.current_task()
        old_task = self._current_task
        if task:
            self._current_task = task

        try:
            rendered = [{"role": m.role, "content": m.content} for m in messages]
            # Ollama ignores a top-level ``num_ctx`` on its OpenAI-compatible
            # ``/v1/chat/completions`` endpoint; the context window can only be
            # raised per request via the *native* ``/api/chat`` API (inside an
            # ``options`` object). So when a context override is configured for
            # Ollama we talk to the native endpoint; every other provider keeps
            # using the OpenAI-compatible path unchanged.
            if self._num_ctx is not None and self._name == "ollama":
                return await self._complete_ollama_native(rendered, options)
            payload = {
                "model": self._model,
                "messages": rendered,
                **options,
            }
            url = f"{self._base_url}/chat/completions"
            token = await self._auth_token()
            headers = {"Authorization": f"Bearer {token}", **self._extra_headers}
            return await self._post_with_retry(
                url, payload, headers, self._extract_openai
            )
        finally:
            if task and self._current_task == task:
                self._current_task = old_task

    async def _post_with_retry(
        self,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        extract: Callable[[dict[str, object]], str],
    ) -> str:
        """POST ``payload`` and return the extracted completion, retrying on 429.

        Shared by the OpenAI-compatible path and Ollama's native ``/api/chat``
        path; each supplies its own ``extract`` for the response shape.
        """
        client = self._get_client()
        try:
            for attempt in range(self._max_retries + 1):
                response = await client.post(url, json=payload, headers=headers)
                if (
                    response.status_code == _RATE_LIMITED
                    and attempt < self._max_retries
                ):
                    await asyncio.sleep(self._retry_after(response))
                    continue
                if response.is_success:
                    return extract(response.json())
                raise self._error_from(response)  # 4xx/5xx: surface the reason
            raise self._error_from(response)  # retries exhausted (still 429)
        except httpx.RequestError as exc:  # transport: DNS, connect, timeout…
            raise LLMError(
                f"No se pudo contactar a {self._name}: {self._transport_detail(exc)}",
                provider=self._name,
                model=self._model,
            ) from exc

    def _transport_detail(self, exc: httpx.RequestError) -> str:
        """A clear, non-empty reason for a transport failure.

        ``httpx`` timeout exceptions often stringify to an empty message, which
        surfaced as a bare ``No se pudo contactar a ollama:``. Name the timeout
        explicitly (with the configured limit) and hint at ``KAOS_LLM_TIMEOUT``,
        since slow local models (CPU inference) are the common cause.
        """
        if isinstance(exc, httpx.TimeoutException):
            return (
                f"timeout tras {self._timeout:.0f}s — el modelo tardó demasiado "
                "en responder; subí KAOS_LLM_TIMEOUT si usás un modelo local lento"
            )
        return str(exc) or type(exc).__name__

    @staticmethod
    def _extract_openai(data: dict[str, object]) -> str:
        """Pull the message content from an OpenAI-style chat completion body."""
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    return str(message.get("content", ""))
        if "error" in data:
            error = data["error"]
            message = error.get("message") if isinstance(error, dict) else error
            raise LLMError(f"Error del proveedor: {message}")
        raise LLMError(f"Respuesta inesperada del proveedor: {data}")

    async def _complete_ollama_native(
        self, rendered: list[dict[str, str]], options: dict[str, object]
    ) -> str:
        """Complete via Ollama's native ``/api/chat`` so ``num_ctx`` is honoured.

        Ollama's OpenAI-compatible endpoint has no way to set the context window
        per request; the native API does, via ``options.num_ctx``. Any known
        generation options passed per call are forwarded into the same object.
        """
        native_base = (
            self._base_url[: -len("/v1")]
            if self._base_url.endswith("/v1")
            else self._base_url
        )
        url = f"{native_base}/api/chat"
        ollama_options: dict[str, object] = {"num_ctx": self._num_ctx}
        for key in ("temperature", "top_p", "top_k", "seed", "num_predict"):
            if key in options:
                ollama_options[key] = options[key]
        payload: dict[str, object] = {
            "model": self._model,
            "messages": rendered,
            "stream": False,
            "options": ollama_options,
        }
        token = await self._auth_token()
        headers = {"Authorization": f"Bearer {token}", **self._extra_headers}
        return await self._post_with_retry(
            url, payload, headers, self._extract_ollama_native
        )

    @staticmethod
    def _extract_ollama_native(data: dict[str, object]) -> str:
        """Pull the message content from Ollama's native ``/api/chat`` body."""
        message = data.get("message")
        if isinstance(message, dict) and "content" in message:
            return str(message["content"])
        if "error" in data:
            raise LLMError(f"Ollama error: {data['error']}")
        raise LLMError(f"Respuesta inesperada de Ollama: {data}")

    def _error_from(self, response: httpx.Response) -> LLMError:
        """Build a clear :class:`LLMError` from a failed provider response.

        Extracts the provider's own error message/code from the JSON body (the
        OpenAI-style ``{"error": {"code", "message"}}`` shape and a couple of
        fallbacks) so the UI shows *why* the request failed — e.g. an
        ``unknown_model`` or a ``tokens_limit_reached`` — instead of a bare
        ``400``.
        """
        return LLMError(
            f"{self._name} rechazó el pedido ({response.status_code}) para el "
            f"modelo '{self._model}': {self._error_detail(response)}",
            provider=self._name,
            model=self._model,
            status_code=response.status_code,
        )

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """The most specific human-readable message from an error response body."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:300].strip() or response.reason_phrase
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err.get("code") or err)
            if isinstance(err, str):
                return err
            message = body.get("message")
            if message:
                return str(message)
        return str(body)[:300]

    async def list_models(self) -> list[str]:
        """Return the chat model ids the endpoint advertises via ``GET /models``.

        Handles the shapes seen in the wild:

        - OpenAI / Ollama: ``{"data": [{"id": "gpt-4o"}]}`` — ``id`` *is* the model.
        - GitHub Models (Azure inference host): a top-level list where each ``id``
          is an ``azureml://…/models/<name>/versions/<n>`` **resource URI**, so the
          usable model is the ``name`` field (e.g. ``gpt-4o``), not the URI (whose
          last path segment is just the version number). Non-chat entries (e.g.
          embeddings) are filtered out via ``task`` so the selector only offers
          chat models.

        Best-effort discovery for the console's model selector. Raises on
        transport/HTTP errors so the caller can fall back to a free-text field.
        """
        client = self._get_client()
        url = f"{self._base_url}/models"
        token = await self._auth_token()
        headers = {"Authorization": f"Bearer {token}", **self._extra_headers}
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return []
        models: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                if row:
                    models.append(str(row).strip())
                continue
            task = str(row.get("task") or "").lower()
            if task and "chat" not in task and "completion" not in task:
                continue  # skip embeddings and other non-chat models
            ident = self._model_ident(row)
            if ident:
                models.append(ident)
        return sorted(dict.fromkeys(models))

    @staticmethod
    def _model_ident(row: dict[str, object]) -> str:
        """The inference model id from a catalog row.

        Prefer a plain ``id`` (OpenAI/Ollama ids, and the GitHub-native catalog's
        ``publisher/model``); when ``id`` is a resource URI — e.g. Azure's
        ``azureml://…/versions/3`` — fall back to the model ``name`` so we never
        surface a bare version number.
        """
        ident = str(row.get("id") or "").strip()
        if ident and "://" not in ident:
            return ident
        return str(row.get("name") or row.get("friendly_name") or "").strip()

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
        # Cancel any pending completion request
        await self.cancel()
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def cancel(self) -> None:
        """Cancel the currently running completion request, if any."""
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._current_task


