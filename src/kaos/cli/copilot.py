"""`kaos copilot`: authenticate with GitHub Copilot and check status.

``kaos copilot login`` runs the OAuth *device flow* (autologin): it prints a
one-time code and a URL, waits for the user to authorize the device on GitHub,
and stores the resulting OAuth token. With a ``KAOS_DATABASE_URL`` the token is
persisted in the credential store (provider ``copilot``); otherwise the value to
put in ``.env`` (``KAOS_COPILOT_TOKEN``) is printed.
"""

from __future__ import annotations

from kaos.bootstrap.factory import build_credential_store
from kaos.core.config import Settings
from kaos.domain.provider_credential import ProviderCredential
from kaos.plugins.providers.copilot import CopilotLLMProvider, device_login


async def _close(obj: object) -> None:
    close = getattr(obj, "close", None)
    if close is not None:
        await close()


def _prompt(user_code: str, verification_uri: str) -> None:
    print("\n  1. Abrí:  " + verification_uri)
    print(f"  2. Ingresá el código:  {user_code}\n")
    print("Esperando autorización… (Ctrl+C para cancelar)")


async def run_copilot_login(*, settings: Settings | None = None) -> int:
    """Run the Copilot device flow and persist the resulting OAuth token."""
    settings = settings if settings is not None else Settings.from_env()
    print("Autenticando con GitHub Copilot (device flow)…")
    try:
        token = await device_login(on_prompt=_prompt)
    except Exception as exc:  # noqa: BLE001 - surface any auth failure to the user
        print(f"error: {exc}")
        return 1

    if settings.database_url:
        store = build_credential_store(settings)
        try:
            await store.set(ProviderCredential(provider="copilot", api_key=token))
        finally:
            await _close(store)
        print("\n✔ Token de Copilot guardado en el credential store.")
        print("Activá el proveedor con KAOS_LLM_PROVIDER=copilot.")
    else:
        print("\n✔ Autenticación exitosa. Agregá esto a tu .env:")
        print(f"\n  KAOS_LLM_PROVIDER=copilot\n  KAOS_COPILOT_TOKEN={token}\n")
    return 0


async def run_copilot_status(*, settings: Settings | None = None) -> int:
    """Report whether the stored Copilot token can mint a session token."""
    settings = settings if settings is not None else Settings.from_env()
    token = settings.copilot_oauth_token
    if not token and settings.database_url:
        store = build_credential_store(settings)
        try:
            cred = await store.get("copilot")
        finally:
            await _close(store)
        token = cred.api_key if cred else None
    if not token:
        print("Copilot: sin credencial. Ejecutá `kaos copilot login`.")
        return 1
    provider = CopilotLLMProvider(oauth_token=token, model=settings.llm_model)
    try:
        await provider._refresh_session_token()  # noqa: SLF001 - intentional check
    except Exception as exc:  # noqa: BLE001
        print(f"Copilot: token inválido — {exc}")
        return 1
    finally:
        await provider.aclose()
    print("Copilot: listo ✔ (el token pudo generar una sesión).")
    return 0
