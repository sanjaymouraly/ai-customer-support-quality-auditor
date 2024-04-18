"""Provider connection API and responder generation route."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

import auditor.providers.manager as manager
import auditor.security.secrets as secrets
from backend.app import create_app
from backend.database import init_db


def setup_module():
    init_db()


client = TestClient(create_app())


def test_connection_crud_masks_key_and_validates(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "CONNECTIONS_PATH", tmp_path / "connections.json")
    monkeypatch.setattr(secrets, "KEY_PATH", tmp_path / ".provider_key")
    monkeypatch.delenv("AUDITOR_SECRET_KEY", raising=False)

    saved = client.put(
        "/api/providers/connections/openai",
        json={
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "api_key": "sk-route-test-7788",
            "timeout": 40,
            "pricing": {"input_usd_per_1m": 0.5, "output_usd_per_1m": 1.5},
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()["connection"]
    assert body["api_key_set"] is True
    assert body["api_key_hint"].endswith("7788")
    assert "sk-route-test-7788" not in saved.text
    assert "api_key_enc" not in saved.text

    listed = client.get("/api/providers")
    assert listed.status_code == 200
    assert "sk-route-test-7788" not in listed.text
    profile = next(
        row
        for row in listed.json()["connection_profiles"]
        if row["provider"] == "openai"
    )
    assert profile["configured"] is True
    assert profile["model"] == "gpt-4o-mini"

    invalid = client.put(
        "/api/providers/connections/openai", json={"base_url": "javascript:alert(1)"}
    )
    assert invalid.status_code == 422

    unknown = client.put("/api/providers/connections/nope", json={})
    assert unknown.status_code == 422

    offline = client.put("/api/providers/connections/offline", json={})
    assert offline.status_code == 422

    deleted = client.delete("/api/providers/connections/openai")
    assert deleted.status_code == 200
    assert deleted.json()["connection"]["configured"] is False
    assert client.delete("/api/providers/connections/openai").status_code == 404


def test_provider_test_endpoint_and_offline():
    offline = client.post("/api/providers/test", json={"provider": "offline"})
    assert offline.status_code == 200
    assert offline.json()["ok"] is True
    assert client.post("/api/providers/test", json={"provider": "nope"}).status_code == 422


def test_generation_route_uses_provider(monkeypatch):
    class FakeProvider:
        name = "custom"
        default_model = "fake-model"
        api_key = "fake"

        async def complete(self, messages, **kwargs):
            assert messages[0]["role"] == "system"
            return "Generated support draft."

    monkeypatch.setattr(
        "backend.api.routes_providers.get_provider", lambda *args, **kwargs: FakeProvider()
    )
    response = client.post(
        "/api/providers/generate",
        json={
            "provider": "custom",
            "model": "fake-model",
            "customer_message": "Where is my order ORD-1?",
            "facts": {"order_id": "ORD-1"},
            "category": "order_status",
            "max_tokens": 200,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response"] == "Generated support draft."
    assert body["model"] == "fake-model"
    assert "audited" in body["note"].lower()

    offline = client.post(
        "/api/providers/generate",
        json={
            "provider": "offline",
            "customer_message": "Where is my order ORD-1?",
        },
    )
    assert offline.status_code == 422


def test_prompt_preview_does_not_call_provider():
    response = client.post(
        "/api/providers/prompt-preview",
        json={
            "provider": "custom",
            "customer_message": "Where is ORD-1?",
            "facts": {"order_id": "ORD-1"},
            "category": "order_status",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["messages"][0]["role"] == "system"
    assert "policy excerpts" in json.dumps(body).lower()
