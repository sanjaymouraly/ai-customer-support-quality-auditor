"""Provider connection profiles with encrypted server-side credentials.

The UI can configure OpenAI, Anthropic, OpenRouter, a custom OpenAI-compatible endpoint,
or a local Ollama server. Non-secret metadata lives in JSON; API keys are encrypted by
``auditor.security.secrets`` and are never returned by the API.

Environment variables remain supported and are the recommended path for shared
deployments. A saved connection overrides an environment value only for fields the user
explicitly saved.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..security.secrets import decrypt_secret, encrypt_secret, mask_secret

ROOT = Path(__file__).resolve().parents[2]
CONNECTIONS_PATH = ROOT / "data" / "provider_connections.json"
_lock = threading.Lock()

PROVIDERS = ("openai", "anthropic", "openrouter", "custom", "ollama", "offline")

PROVIDER_META = {
    "openai": {
        "label": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "model_placeholder": "gpt-4o-mini",
        "docs": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic Claude",
        "default_base_url": "https://api.anthropic.com",
        "model_placeholder": "claude-3-5-sonnet-20241022",
        "docs": "https://console.anthropic.com/settings/keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "default_base_url": "https://openrouter.ai/api/v1",
        "model_placeholder": "anthropic/claude-3.5-sonnet",
        "docs": "https://openrouter.ai/keys",
    },
    "custom": {
        "label": "Custom OpenAI-compatible endpoint",
        "default_base_url": "http://localhost:11434/v1",
        "model_placeholder": "your-model-name",
        "docs": "",
    },
    "ollama": {
        "label": "Local Ollama",
        "default_base_url": "http://localhost:11434/v1",
        "model_placeholder": "gemma:2b",
        "docs": "https://ollama.com",
    },
    "offline": {
        "label": "Offline rule engine",
        "default_base_url": "",
        "model_placeholder": "rule-engine-v1",
        "docs": "",
    },
}

_ENV = {
    "openai": {
        "api_key": "OPENAI_API_KEY",
        "base_url": "OPENAI_BASE_URL",
        "model": "OPENAI_MODEL",
        "headers": "OPENAI_HEADERS_JSON",
    },
    "anthropic": {
        "api_key": "ANTHROPIC_API_KEY",
        "base_url": "ANTHROPIC_BASE_URL",
        "model": "ANTHROPIC_MODEL",
        "headers": "ANTHROPIC_HEADERS_JSON",
    },
    "openrouter": {
        "api_key": "OPENROUTER_API_KEY",
        "base_url": "OPENROUTER_BASE_URL",
        "model": "OPENROUTER_MODEL",
        "headers": "OPENROUTER_HEADERS_JSON",
    },
    "custom": {
        "api_key": "CUSTOM_API_KEY",
        "base_url": "CUSTOM_BASE_URL",
        "model": "CUSTOM_MODEL",
        "headers": "CUSTOM_HEADERS_JSON",
    },
    "ollama": {
        "api_key": "OLLAMA_API_KEY",
        "base_url": "OLLAMA_BASE_URL",
        "model": "OLLAMA_MODEL",
        "headers": "OLLAMA_HEADERS_JSON",
    },
    "offline": {},
}


def _read() -> dict[str, dict[str, Any]]:
    if not CONNECTIONS_PATH.exists():
        return {}
    try:
        data = json.loads(CONNECTIONS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict[str, dict[str, Any]]) -> None:
    CONNECTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONNECTIONS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(CONNECTIONS_PATH)
    try:
        os.chmod(CONNECTIONS_PATH, 0o600)
    except OSError:
        pass


def _clean_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    safe: dict[str, str] = {}
    for key, value in headers.items():
        key, value = str(key).strip(), str(value).strip()
        if not key or any(ch in key + value for ch in "\r\n"):
            continue
        safe[key[:100]] = value[:1000]
    return safe


def _env_headers(name: str) -> dict[str, str]:
    raw = os.getenv(_ENV.get(name, {}).get("headers", ""), "").strip()
    if not raw:
        return {}
    try:
        return _clean_headers(json.loads(raw))
    except json.JSONDecodeError:
        return {}


def _valid_base_url(url: str) -> bool:
    if not url:
        return True
    if len(url) > 500:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and "@" not in parsed.netloc


def save_connection(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    if provider == "offline":
        raise ValueError("Offline mode has no connection settings")

    with _lock:
        data = _read()
        current = data.get(provider, {})
        base_url = str(payload.get("base_url") or current.get("base_url") or "").strip()
        if not _valid_base_url(base_url):
            raise ValueError("Base URL must be an http(s) URL without embedded credentials")
        model = str(payload.get("model") or current.get("model") or "").strip()[:200]
        temperature = float(payload.get("temperature", current.get("temperature", 0.2)))
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        timeout = int(payload.get("timeout", current.get("timeout", 30)))
        if not 5 <= timeout <= 300:
            raise ValueError("timeout must be between 5 and 300 seconds")
        max_tokens = int(payload.get("max_tokens", current.get("max_tokens", 1500)))
        if not 100 <= max_tokens <= 16_000:
            raise ValueError("max_tokens must be between 100 and 16000")
        headers = _clean_headers(payload.get("headers") or current.get("headers") or {})
        pricing_raw = payload.get("pricing", current.get("pricing") or {})
        pricing: dict[str, float] = {}
        if isinstance(pricing_raw, dict):
            for key in ("input_usd_per_1m", "output_usd_per_1m"):
                if pricing_raw.get(key) not in (None, ""):
                    value = float(pricing_raw[key])
                    if value < 0:
                        raise ValueError("Pricing values cannot be negative")
                    pricing[key] = value

        api_key_enc = current.get("api_key_enc", "")
        if payload.get("clear_api_key"):
            api_key_enc = ""
        elif payload.get("api_key"):
            raw_key = str(payload["api_key"]).strip()
            if len(raw_key) > 500 or "\n" in raw_key or "\r" in raw_key:
                raise ValueError("Invalid API key value")
            api_key_enc = encrypt_secret(raw_key)

        record = {
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
            "timeout": timeout,
            "max_tokens": max_tokens,
            "headers": headers,
            "pricing": pricing,
            "api_key_enc": api_key_enc,
            "updated_at": datetime.now(UTC).isoformat(),
            "last_test_at": current.get("last_test_at"),
            "last_test_ok": current.get("last_test_ok"),
        }
        data[provider] = record
        _write(data)
        return public_connection(provider, record)


def delete_connection(provider: str) -> bool:
    with _lock:
        data = _read()
        if provider not in data:
            return False
        del data[provider]
        _write(data)
        return True


def mark_test_result(provider: str, ok: bool) -> None:
    with _lock:
        data = _read()
        if provider in data:
            data[provider]["last_test_at"] = datetime.now(UTC).isoformat()
            data[provider]["last_test_ok"] = bool(ok)
            _write(data)


def public_connection(provider: str, record: dict[str, Any] | None = None) -> dict[str, Any]:
    record = record if record is not None else _read().get(provider, {})
    meta = PROVIDER_META.get(provider, {})
    api_key = ""
    if record.get("api_key_enc"):
        try:
            api_key = decrypt_secret(record["api_key_enc"])
        except RuntimeError:
            api_key = ""
    return {
        "provider": provider,
        "label": meta.get("label", provider),
        "configured": bool(record),
        "api_key_set": bool(api_key),
        "api_key_hint": mask_secret(api_key),
        "base_url": record.get("base_url", ""),
        "model": record.get("model", ""),
        "temperature": record.get("temperature", 0.2),
        "timeout": record.get("timeout", 30),
        "max_tokens": record.get("max_tokens", 1500),
        "headers": record.get("headers", {}),
        "pricing": record.get("pricing", {}),
        "updated_at": record.get("updated_at"),
        "last_test_at": record.get("last_test_at"),
        "last_test_ok": record.get("last_test_ok"),
        "env_configured": bool(os.getenv(_ENV.get(provider, {}).get("api_key", ""), "").strip()),
        "default_base_url": meta.get("default_base_url", ""),
        "model_placeholder": meta.get("model_placeholder", ""),
    }


def list_connections() -> list[dict[str, Any]]:
    data = _read()
    rows = []
    for provider in PROVIDERS:
        if provider == "offline":
            continue
        rows.append(public_connection(provider, data.get(provider)))
    return rows


def resolve_provider_config(
    provider: str, overrides: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Merge environment, saved connection, and one-off overrides (in that order)."""

    provider = provider.lower().strip()
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}")
    if provider == "offline":
        return {"api_key": None, "default_model": "rule-engine-v1"}

    env_names = _ENV.get(provider, {})
    config: dict[str, Any] = {
        "api_key": os.getenv(env_names.get("api_key", ""), "") or None,
        "base_url": os.getenv(env_names.get("base_url", ""), "") or None,
        "default_model": os.getenv(env_names.get("model", ""), "") or None,
        "headers": _env_headers(provider),
    }
    record = _read().get(provider)
    if record:
        try:
            saved_key = decrypt_secret(record.get("api_key_enc"))
        except RuntimeError:
            saved_key = ""
        if saved_key:
            config["api_key"] = saved_key
        for source, target in (("base_url", "base_url"), ("model", "default_model")):
            if record.get(source):
                config[target] = record[source]
        if record.get("headers"):
            config["headers"] = _clean_headers(record["headers"])
        if record.get("temperature") is not None:
            config["temperature"] = record["temperature"]
        if record.get("timeout") is not None:
            config["timeout"] = record["timeout"]
        if record.get("max_tokens") is not None:
            config["max_tokens"] = record["max_tokens"]
    for key, value in (overrides or {}).items():
        if value is not None and value != "":
            config[key] = value
    # Local providers do not require a real API key; the OpenAI-compatible SDK does.
    if provider in ("ollama", "custom") and not config.get("api_key"):
        config["api_key"] = "ollama"
    return config


def saved_pricing() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for provider, record in _read().items():
        pricing = record.get("pricing") or {}
        inp = pricing.get("input_usd_per_1m")
        outp = pricing.get("output_usd_per_1m")
        if inp is not None and outp is not None:
            out[provider] = {
                "input_usd_per_1m": float(inp),
                "output_usd_per_1m": float(outp),
            }
    return out


def configured_provider_names() -> list[str]:
    names = []
    data = _read()
    for provider in PROVIDERS:
        if provider == "offline":
            continue
        if data.get(provider) or os.getenv(_ENV.get(provider, {}).get("api_key", ""), ""):
            names.append(provider)
    return names


def looks_like_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value or ""))


__all__ = [
    "PROVIDER_META",
    "PROVIDERS",
    "configured_provider_names",
    "delete_connection",
    "list_connections",
    "mark_test_result",
    "public_connection",
    "resolve_provider_config",
    "save_connection",
    "saved_pricing",
]
