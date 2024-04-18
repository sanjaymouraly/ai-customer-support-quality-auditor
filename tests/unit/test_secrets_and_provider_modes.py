"""Secret storage and JSON-mode provider behavior."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

import auditor.security.secrets as secrets


def test_secret_roundtrip_uses_private_key_file(monkeypatch, tmp_path):
    key_path = tmp_path / ".provider_key"
    monkeypatch.setattr(secrets, "KEY_PATH", key_path)
    monkeypatch.delenv("AUDITOR_SECRET_KEY", raising=False)

    token = secrets.encrypt_secret("sk-test-123456789")
    assert token and token != "sk-test-123456789"
    assert secrets.decrypt_secret(token) == "sk-test-123456789"
    assert key_path.exists()
    assert (key_path.stat().st_mode & 0o077) == 0
    assert secrets.mask_secret("sk-test-123456789").endswith("6789")
    assert secrets.mask_secret("short") == "••••"
    assert secrets.encrypt_secret("") == ""
    assert secrets.decrypt_secret("") == ""


def test_secret_env_key_and_invalid_tokens(monkeypatch, tmp_path):
    monkeypatch.setattr(secrets, "KEY_PATH", tmp_path / ".provider_key")
    monkeypatch.setenv("AUDITOR_SECRET_KEY", "deployment-secret")
    token = secrets.encrypt_secret("value")
    assert secrets.decrypt_secret(token) == "value"

    monkeypatch.setenv("AUDITOR_SECRET_KEY", "different-secret")
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        secrets.decrypt_secret(token)

    monkeypatch.setenv("AUDITOR_SECRET_KEY", "deployment-secret")
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        secrets.decrypt_secret("not-a-token")


def test_corrupt_key_file_fails_loudly(monkeypatch, tmp_path):
    key_path = tmp_path / ".provider_key"
    key_path.write_bytes(b"corrupt")
    monkeypatch.setattr(secrets, "KEY_PATH", key_path)
    monkeypatch.delenv("AUDITOR_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="corrupt"):
        secrets.encrypt_secret("x")


def test_openai_response_format_is_forwarded():
    from auditor.providers.openai_provider import OpenAIProvider

    client = Mock()
    client.close = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
        )
    )
    with patch("openai.AsyncOpenAI", return_value=client):
        provider = OpenAIProvider(api_key="test")
        result = asyncio.run(
            provider.complete(
                [{"role": "user", "content": "json"}],
                response_format={"type": "json_object"},
            )
        )
    assert result == "{}"
    assert client.chat.completions.create.await_args.kwargs["response_format"] == {
        "type": "json_object"
    }


def test_custom_provider_response_format_and_model_discovery():
    from auditor.providers.custom_provider import CustomProvider

    client = Mock()
    client.close = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))]
        )
    )
    client.models.list = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(id="model-b"), SimpleNamespace(id="model-a")]
        )
    )
    with patch("openai.AsyncOpenAI", return_value=client):
        provider = CustomProvider(
            base_url="http://localhost:11434/v1", default_model="local-test"
        )
        raw = asyncio.run(
            provider.complete(
                [{"role": "user", "content": "json"}],
                response_format={"type": "json_object"},
            )
        )
        models = asyncio.run(provider.list_models())
    assert json.loads(raw) == {"ok": True}
    assert client.chat.completions.create.await_args.kwargs["response_format"] == {
        "type": "json_object"
    }
    assert models == ["model-a", "model-b"]

    class Healthy(CustomProvider):
        async def complete(self, *args, **kwargs):
            return "OK"

    assert asyncio.run(Healthy().health_check()) is True


def test_llm_judge_requests_json_mode_and_repairs():
    from auditor.evaluation.llm_judge import llm_evaluate
    from auditor.evaluation.schemas import DIMENSION_LIST

    valid = json.dumps(
        {
            "dimension_scores": [
                {
                    "dimension": name,
                    "score": 3,
                    "explanation": "Adequate.",
                    "evidence": ["exact response quote"],
                }
                for name in DIMENSION_LIST
            ],
            "missing_info": [],
            "improvement_suggestions": [],
            "hallucination_flags": [],
            "confidence": 0.8,
        }
    )

    class RepairingProvider:
        name = "ollama"
        default_model = "local"

        def __init__(self):
            self.calls = []

        async def complete(self, messages, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return "this is not json"
            return valid

    provider = RepairingProvider()
    result = asyncio.run(
        llm_evaluate(
            "customer",
            "exact response quote",
            {},
            [],
            None,
            "order_status",
            "low",
            None,
            provider,
        )
    )
    assert len(result["dimension_scores"]) == 9
    assert len(provider.calls) == 2
    assert provider.calls[0]["response_format"] == {"type": "json_object"}
    assert provider.calls[1]["response_format"] == {"type": "json_object"}
    assert provider.calls[1]["temperature"] == 0.0


def test_judge_rejects_unknown_or_duplicate_dimensions():
    from auditor.evaluation.llm_judge import JudgeOutput
    from auditor.evaluation.schemas import DIMENSION_LIST

    base = {
        "dimension_scores": [
            {"dimension": name, "score": 3, "explanation": "ok", "evidence": []}
            for name in DIMENSION_LIST
        ],
        "confidence": 0.8,
    }
    duplicated = {
        **base,
        "dimension_scores": base["dimension_scores"][:-1] + [base["dimension_scores"][0]],
    }
    with pytest.raises(ValueError):
        JudgeOutput.model_validate(duplicated)

    bad_score = {
        **base,
        "dimension_scores": [
            {**base["dimension_scores"][0], "score": 5},
            *base["dimension_scores"][1:],
        ],
    }
    with pytest.raises(ValueError):
        JudgeOutput.model_validate(bad_score)


def test_parse_judge_output_strips_fences_and_preamble():
    from auditor.evaluation.llm_judge import parse_judge_output

    assert parse_judge_output('```json\n{"confidence": 0.5}\n```') == {"confidence": 0.5}
    assert parse_judge_output('Here is the result: {"confidence": 0.6}') == {
        "confidence": 0.6
    }
    with pytest.raises(ValueError):
        parse_judge_output("[]")
