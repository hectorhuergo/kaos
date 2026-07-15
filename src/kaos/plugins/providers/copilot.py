"""GitHub Copilot LLM provider.

Talks to the GitHub Copilot chat completions API
(``https://api.githubcopilot.com/chat/completions``), which is OpenAI-compatible
but authenticates differently from the other providers:

1. A long-lived **GitHub OAuth token** (``gho_…``) is obtained once via the
   OAuth *device flow* (``kaos copilot login``) and persisted like any other
   credential.
2. At request time that token is exchanged for a **short-lived Copilot session
   token** (``GET api.github.com/copilot_internal/v2/token``); the session token
   is cached until shortly before it expires and sent as the ``Bearer`` header,
   together with the editor headers the Copilot backend requires.

This keeps KAOS AI Provider Agnostic — the Core still only depends on the
``LLMProvider`` contract; the token dance lives entirely inside this plugin.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

import httpx

from kaos.plugins.providers.openai_compatible import OpenAICompatibleLLMProvider

# Public client id used by the official Copilot editor integrations for the
# OAuth device flow. It is not a secret (it ships in the editor clients).
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"

COPILOT_BASE_URL = "https://api.githubcopilot.com"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

DEFAULT_COPILOT_MODEL = "gpt-4o"

# Editor identity headers the Copilot backend expects on chat requests.
_EDITOR_VERSION = "vscode/1.95.0"
_PLUGIN_VERSION = "copilot-chat/0.22.0"
_USER_AGENT = "GitHubCopilotChat/0.22.0"

# Refresh the session token this many seconds before it actually expires.
_EXPIRY_SKEW = 120.0


def _copilot_headers() -> dict[str, str]:
    return {
        "Editor-Version": _EDITOR_VERSION,
        "Editor-Plugin-Version": _PLUGIN_VERSION,
        "Copilot-Integration-Id": "vscode-chat",
        "Openai-Intent": "conversation-panel",
        "User-Agent": _USER_AGENT,
    }


class CopilotLLMProvider(OpenAICompatibleLLMProvider):
    """Provider backed by the GitHub Copilot chat completions API."""

    def __init__(
        self,
        oauth_token: str,
        model: str = DEFAULT_COPILOT_MODEL,
        *,
        base_url: str = COPILOT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 120.0,
    ) -> None:
        super().__init__(
            model=model,
            api_key=oauth_token,
            base_url=base_url,
            name="copilot",
            client=client,
            timeout=timeout,
            extra_headers=_copilot_headers(),
        )
        self._oauth_token = oauth_token
        self._session_token: str | None = None
        self._session_expiry: float = 0.0

    async def _auth_token(self) -> str:
        """Return a valid Copilot session token, refreshing it when stale."""
        now = time.time()
        if self._session_token is None or now >= self._session_expiry - _EXPIRY_SKEW:
            await self._refresh_session_token()
        assert self._session_token is not None
        return self._session_token

    async def _refresh_session_token(self) -> None:
        client = self._get_client()
        response = await client.get(
            COPILOT_TOKEN_URL,
            headers={
                "Authorization": f"token {self._oauth_token}",
                "Accept": "application/json",
                "User-Agent": _USER_AGENT,
                "Editor-Version": _EDITOR_VERSION,
            },
        )
        if response.status_code in (401, 403):
            raise ValueError(
                "GitHub Copilot rechazó el token. ¿Tenés una suscripción activa? "
                "Volvé a autenticar con `kaos copilot login`."
            )
        response.raise_for_status()
        data = response.json()
        token = data.get("token")
        if not token:
            raise ValueError("La respuesta de Copilot no incluyó un token de sesión.")
        self._session_token = str(token)
        expires_at = data.get("expires_at")
        try:
            self._session_expiry = float(expires_at)
        except (TypeError, ValueError):
            # Fall back to a conservative 25-minute lifetime.
            self._session_expiry = time.time() + 1500.0


# ---- OAuth device flow (autologin) -------------------------------------------


class DeviceCodeError(RuntimeError):
    """Raised when the OAuth device flow cannot complete."""


async def request_device_code(
    *, client: httpx.AsyncClient | None = None
) -> dict[str, object]:
    """Start the device flow; return the user code and verification details."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.post(
            DEVICE_CODE_URL,
            headers={"Accept": "application/json"},
            data={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
        )
        response.raise_for_status()
        return dict(response.json())
    finally:
        if owns:
            await client.aclose()


async def poll_for_access_token(
    device_code: str,
    *,
    interval: float = 5.0,
    timeout: float = 900.0,
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Poll GitHub until the user authorizes the device; return the OAuth token."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    deadline = time.time() + timeout
    wait = interval
    try:
        while True:
            response = await client.post(
                ACCESS_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": COPILOT_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": DEVICE_GRANT,
                },
            )
            response.raise_for_status()
            data = response.json()
            token = data.get("access_token")
            if token:
                return str(token)
            error = data.get("error")
            if error == "authorization_pending":
                pass
            elif error == "slow_down":
                wait += 5.0
            elif error == "expired_token":
                raise DeviceCodeError("El código expiró. Ejecutá `kaos copilot login` de nuevo.")
            elif error == "access_denied":
                raise DeviceCodeError("Autorización cancelada por el usuario.")
            else:
                raise DeviceCodeError(f"Error de OAuth: {error or 'desconocido'}")
            if time.time() >= deadline:
                raise DeviceCodeError("Se agotó el tiempo de espera de autorización.")
            await sleep(wait)
    finally:
        if owns:
            await client.aclose()


async def device_login(
    *,
    on_prompt: Callable[[str, str], None],
    client: httpx.AsyncClient | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Run the full device flow and return the GitHub OAuth token.

    ``on_prompt(user_code, verification_uri)`` is called once so the caller can
    tell the user where to go and what code to enter.
    """
    owns = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        start = await request_device_code(client=client)
        user_code = str(start.get("user_code") or "")
        verification_uri = str(start.get("verification_uri") or "https://github.com/login/device")
        device_code = str(start.get("device_code") or "")
        if not device_code or not user_code:
            raise DeviceCodeError("GitHub no devolvió un device code válido.")
        try:
            interval = float(start.get("interval") or 5.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            interval = 5.0
        on_prompt(user_code, verification_uri)
        return await poll_for_access_token(
            device_code, interval=interval, client=client, sleep=sleep
        )
    finally:
        if owns:
            await client.aclose()
