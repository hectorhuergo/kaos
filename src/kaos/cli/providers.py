"""`kaos providers`: list the LLM providers and their readiness.

Reports every provider in the catalog (`kaos.core.providers`), its default
model and endpoint, and whether the credential it needs is present. The active
provider (``KAOS_LLM_PROVIDER``) is marked so it is obvious which one a run will
use. Secrets themselves are never printed — only whether they are configured.
"""

from __future__ import annotations

from kaos.core.config import Settings
from kaos.core.providers import provider_status, secret_sources


def list_providers(*, settings: Settings | None = None) -> int:
    """Print the provider catalog with active/ready status."""
    settings = settings if settings is not None else Settings.from_env()
    print("Proveedores LLM:\n")
    for info, ready, active in provider_status(settings):
        mark = "→" if active else " "
        state = "listo" if ready else "sin credencial"
        model = settings.llm_model if active else info.default_model
        endpoint = info.base_url or "(local)"
        print(f" {mark} {info.id:10} [{state:14}] model={model}")
        print(f"     {info.label} · {endpoint}")
        print(f"     {info.notes}")
        if info.secret_env:
            sources = secret_sources(info.id, settings)
            if sources:
                print(f"     credencial en .env: {' | '.join(sources)}")
            else:
                print(f"     credencial requerida: {' | '.join(info.secret_env)}")
        print()
    print("→ = proveedor activo (KAOS_LLM_PROVIDER). Selecciona con "
          "KAOS_LLM_PROVIDER=<id> y KAOS_LLM_MODEL=<modelo>.")
    return 0

