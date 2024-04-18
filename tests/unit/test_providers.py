from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from auditor.providers.registry import get_provider


def test_registry_lists():
    from auditor.providers.registry import list_providers

    assert "openai" in list_providers()
    assert "offline" in list_providers()


def test_offline_provider():
    prov = get_provider("offline")
    assert prov.name == "offline"


def test_unknown_provider():
    with pytest.raises(ValueError):
        get_provider("unknown_xyz")


def test_mock_openai_provider_complete():
    import asyncio

    from auditor.providers.openai_provider import OpenAIProvider

    client = Mock()
    client.close = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="mocked response"))]
        )
    )
    with patch("openai.AsyncOpenAI", return_value=client) as constructor:
        provider = OpenAIProvider(api_key="test", base_url="https://provider.invalid/v1")
        result = asyncio.run(
            provider.complete([{"role": "user", "content": "hello"}], model="mock-model", timeout=3)
        )
    assert result == "mocked response"
    constructor.assert_called_once()
    client.chat.completions.create.assert_awaited_once()
    client.close.assert_awaited_once()
    assert client.chat.completions.create.await_args.kwargs["model"] == "mock-model"


def test_mock_anthropic_provider_complete():
    import asyncio

    from auditor.providers.anthropic_provider import AnthropicProvider

    client = Mock()
    client.close = AsyncMock()
    client.messages.create = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text="anthropic mock")])
    )
    with patch("anthropic.AsyncAnthropic", return_value=client):
        provider = AnthropicProvider(api_key="test", default_model="claude-test")
        result = asyncio.run(
            provider.complete(
                [
                    {"role": "system", "content": "system rule"},
                    {"role": "user", "content": "hello"},
                ],
                timeout=4,
            )
        )
    assert result == "anthropic mock"
    call = client.messages.create.await_args.kwargs
    assert call["system"] == "system rule"
    assert call["model"] == "claude-test"
    client.close.assert_awaited_once()
