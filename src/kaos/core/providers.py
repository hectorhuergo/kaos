"""LLM provider catalog: descriptive metadata about the supported providers.

Pure data — no plugin imports — so the Core stays agnostic. This mirrors the
provider ids validated in :data:`kaos.core.config.LLM_PROVIDERS` and describes,
for each one, its default model, endpoint and which environment secret makes it
usable. The composition root (`kaos.bootstrap.factory`) is still the only place
that instantiates concrete providers; this catalog only *describes* them so the
CLI (`kaos providers`) can report what is available and ready.
"""

from __future__ import annotations

from dataclasses import dataclass

from kaos.core.config import LLM_PROVIDERS, Settings


@dataclass(frozen=True)
class ProviderInfo:
    """Descriptive metadata for one LLM provider option."""

    id: str
    label: str
    default_model: str
    base_url: str | None
    secret_env: tuple[str, ...]
    notes: str


# Base URLs are restated here as documentation so the Core does not import the
# provider plugin (which would couple the Core to a concrete implementation).
CATALOG: tuple[ProviderInfo, ...] = (
    ProviderInfo(
        id="echo",
        label="Echo (offline)",
        default_model="-",
        base_url=None,
        secret_env=(),
        notes="Doble de prueba; no llama a ningún LLM (útil sin credenciales).",
    ),
    ProviderInfo(
        id="openai",
        label="OpenAI",
        default_model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        secret_env=("KAOS_LLM_API_KEY",),
        notes="OpenAI o cualquier endpoint compatible (KAOS_LLM_BASE_URL).",
    ),
    ProviderInfo(
        id="github",
        label="GitHub Models",
        default_model="gpt-4o-mini",
        base_url="https://models.inference.ai.azure.com",
        secret_env=("KAOS_GITHUB_TOKEN", "GITHUB_TOKEN"),
        notes="Modelos vía GitHub Models (token con permiso 'Models').",
    ),
    ProviderInfo(
        id="anthropic",
        label="Anthropic (Claude)",
        default_model="claude-3-5-haiku-latest",
        base_url="https://api.anthropic.com/v1",
        secret_env=("KAOS_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        notes="Claude por el endpoint compatible de Anthropic.",
    ),
    ProviderInfo(
        id="ollama",
        label="Ollama (local)",
        default_model="llama3.2:3b",
        base_url="http://localhost:11434/v1",
        secret_env=(),
        notes="Modelos locales vía Ollama (Docker); sin credencial. Ideal para dogfooding.",
    ),
)

# Keep the catalog and the validated provider ids in sync.
assert {p.id for p in CATALOG} == set(LLM_PROVIDERS), (
    "providers.CATALOG must cover exactly config.LLM_PROVIDERS"
)


# Maps a provider to the Settings field that carries its secret, so a persisted
# credential can be overlaid onto Settings exactly where ``build_llm`` reads it.
_SECRET_FIELD: dict[str, str] = {
    "openai": "llm_api_key",
    "github": "github_token",
    "anthropic": "anthropic_api_key",
}


def secret_field(provider_id: str) -> str | None:
    """Return the Settings field holding ``provider_id``'s secret, if any.

    ``echo`` needs no secret and returns ``None``.
    """
    return _SECRET_FIELD.get(provider_id)


def is_ready(provider_id: str, settings: Settings) -> bool:
    """Whether ``provider_id`` has the credential it needs to run.

    Readiness is expressed against :class:`Settings` (already resolved from the
    environment) rather than raw env names, matching how ``build_llm`` selects
    the secret for each provider.
    """
    if provider_id == "echo":
        return True
    if provider_id == "ollama":
        # Local server; no credential required (it must be running to serve).
        return True
    if provider_id == "github":
        return bool(settings.github_token or settings.llm_api_key)
    if provider_id == "anthropic":
        return bool(settings.anthropic_api_key or settings.llm_api_key)
    if provider_id == "openai":
        return bool(settings.llm_api_key)
    return False


def provider_status(settings: Settings) -> list[tuple[ProviderInfo, bool, bool]]:
    """Return ``(info, ready, active)`` for every provider in the catalog.

    ``active`` is the provider selected by ``KAOS_LLM_PROVIDER``.
    """
    return [
        (info, is_ready(info.id, settings), settings.llm_provider == info.id)
        for info in CATALOG
    ]

