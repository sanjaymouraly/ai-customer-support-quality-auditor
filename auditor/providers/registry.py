from __future__ import annotations

import inspect
import os
from typing import Any

from .anthropic_provider import AnthropicProvider
from .custom_provider import CustomProvider, OllamaProvider, OpenRouterProvider
from .manager import PROVIDERS, configured_provider_names, resolve_provider_config
from .offline import OfflineProvider
from .openai_provider import OpenAIProvider

PROVIDER_CLASSES = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "custom": CustomProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
    "offline": OfflineProvider,
}


def get_provider(name: str, config: dict[str, Any] | None = None):
    """Instantiate an adapter with saved/env configuration plus explicit overrides.

    Overrides are used by the connection-test endpoint (a temporary key) and the
    model-comparison generation endpoint. Saved API keys are decrypted only in this
    server-side process and are never returned to the browser.
    """

    name = name.lower().strip()
    cls = PROVIDER_CLASSES.get(name)
    if not cls:
        raise ValueError(f"Unknown provider {name}. Available: {list(PROVIDER_CLASSES)}")
    merged = resolve_provider_config(name, config or {})
    accepted = set(inspect.signature(cls.__init__).parameters) - {"self"}
    return cls(**{k: v for k, v in merged.items() if v is not None and k in accepted})


def list_providers():
    return list(PROVIDERS)


def provider_health_env() -> dict[str, bool]:
    # Availability check without a network call. Saved connections are included so the
    # UI can distinguish "ready on this server" from "adapter exists".
    configured = set(configured_provider_names())
    return {
        provider: provider == "offline"
        or provider in configured
        or bool(os.getenv(f"{provider.upper()}_API_KEY"))
        or (provider == "ollama" and bool(os.getenv("OLLAMA_BASE_URL")))
        for provider in PROVIDERS
    }
