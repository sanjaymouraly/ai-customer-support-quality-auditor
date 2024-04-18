"""Edge cases for policy, scenario, provider, settings, export, and hybrid routes."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import auditor.evaluation.config as evaluation_config
import backend.api.routes_audit as audit_routes
import backend.api.routes_providers as provider_routes
import backend.api.routes_scenarios as scenario_routes
from auditor.evaluation.engine import evaluate_deterministic
from auditor.evaluation.schemas import EvaluationRequest
from auditor.policies.models import PolicyDocument, PolicySection
from backend.app import create_app
from backend.database import init_db
from backend.services import usage as usage_service


def setup_module():
    init_db()


client = TestClient(create_app())


def audit_payload(case_id: str = "EDGE-AUDIT") -> dict:
    return {
        "case_id": case_id,
        "category": "order_status",
        "customer_message": "Where is order ORD-1?",
        "candidate_response": "It shipped with tracking TRK-001 and should arrive Friday.",
        "facts": {"order_id": "ORD-1", "tracking_number": "TRK-001"},
        "expected_actions": ["provide tracking"],
        "severity": "low",
        "evaluation_mode": "deterministic",
    }


def test_policy_detail_versions_and_missing_resources(monkeypatch):
    detail = client.get("/api/policies/shipping_policy")
    assert detail.status_code == 200
    body = detail.json()
    assert body["policy_id"] == "shipping_policy"
    assert body["sections"]

    versions = client.get("/api/policies/shipping_policy/versions")
    assert versions.status_code == 200
    assert versions.json()[0]["policy_id"] == "shipping_policy"

    assert client.get("/api/policies/not_a_policy").status_code == 404
    assert client.get("/api/policies/not_a_policy/versions").status_code == 404
    assert (
        client.get(
            "/api/policies/shipping_policy/compare",
            params={"left": "1.8", "right": "0.1"},
        ).status_code
        == 404
    )
    assert client.post("/api/policies/shipping_policy/activate/0.1").status_code == 404

    left = PolicyDocument(
        policy_id="compare_demo",
        title="Compare demo",
        version="1.0",
        effective_date="2024-01-01",
        category="test",
        sections=[
            PolicySection(
                section_id="compare_demo-s1",
                title="Window",
                content="Refunds within 14 days.",
                keywords=["refund"],
            )
        ],
    )
    right = PolicyDocument(
        policy_id="compare_demo",
        title="Compare demo",
        version="2.0",
        effective_date="2025-01-01",
        category="test",
        sections=[
            PolicySection(
                section_id="compare_demo-s1",
                title="Window",
                content="Refunds within 30 days.",
                keywords=["refund"],
            ),
            PolicySection(
                section_id="compare_demo-s2",
                title="Evidence",
                content="A receipt is required.",
                keywords=["receipt"],
            ),
        ],
    )
    monkeypatch.setattr(
        "backend.api.routes_policies.get_policy_versions",
        lambda policy_id: [right, left],
    )
    compared = client.get(
        "/api/policies/compare_demo/compare",
        params={"left": "1.0", "right": "2.0"},
    )
    assert compared.status_code == 200
    differences = compared.json()["differences"]
    assert {item["section_id"] for item in differences} == {
        "compare_demo-s1",
        "compare_demo-s2",
    }
    assert differences[0]["left"]["content"] == "Refunds within 14 days."


def test_policy_retrieval_requires_query():
    assert client.post("/api/policies/retrieve", json={"query": ""}).status_code == 400
    retrieved = client.post(
        "/api/policies/retrieve",
        json={"query": "refund window", "policy_ids": ["refund_policy"], "top_k": 2},
    )
    assert retrieved.status_code == 200
    assert len(retrieved.json()["results"]) <= 2


def test_scenario_update_duplicate_and_corrupt_store(monkeypatch, tmp_path):
    store = tmp_path / "custom_scenarios.json"
    monkeypatch.setattr(scenario_routes, "DATA_FILE", store)

    case = {
        "case_id": "EDGE-SCENARIO",
        "category": "insufficient_info",
        "customer_message": "I need help with an order.",
        "facts": {},
        "policy_ids": [],
        "candidate_response": "Please share the order ID.",
        "expected_actions": ["ask for order ID"],
        "expected_escalation": "ask_info",
        "severity": "medium",
        "label": "borderline",
        "notes": "edge test",
        "evaluation_metadata": {},
    }
    created = client.post("/api/scenarios", json=case)
    assert created.status_code == 200, created.text
    assert client.post("/api/scenarios", json=case).status_code == 409

    mismatch = client.put(
        "/api/scenarios/EDGE-SCENARIO",
        json={**case, "case_id": "OTHER-ID"},
    )
    assert mismatch.status_code == 422

    updated_case = {**case, "notes": "updated notes"}
    updated = client.put("/api/scenarios/EDGE-SCENARIO", json=updated_case)
    assert updated.status_code == 200
    assert updated.json()["scenario"]["notes"] == "updated notes"
    assert updated.json()["scenario"]["evaluation_metadata"]["dataset"] == "local_custom"

    assert client.delete("/api/scenarios/EDGE-SCENARIO").status_code == 200
    assert client.delete("/api/scenarios/EDGE-SCENARIO").status_code == 404
    assert client.delete("/api/scenarios/bad..id").status_code == 422

    store.write_text("{not json", encoding="utf-8")
    assert client.get("/api/scenarios").status_code == 500


def test_provider_health_and_model_discovery_success(monkeypatch):
    class FakeProvider:
        name = "openai"
        default_model = "fake-model"

        async def health_check(self, model=None):
            return True

        async def list_models(self):
            return ["fake-model", "fake-model-mini"]

    monkeypatch.setattr(provider_routes, "get_provider", lambda *a, **k: FakeProvider())
    monkeypatch.setattr(provider_routes, "mark_test_result", lambda *a, **k: None)

    tested = client.post(
        "/api/providers/test", json={"provider": "openai", "model": "fake-model"}
    )
    assert tested.status_code == 200
    assert tested.json()["ok"] is True
    assert tested.json()["model"] == "fake-model"

    models = client.get("/api/providers/models", params={"provider": "openai"})
    assert models.status_code == 200
    assert models.json()["models"] == ["fake-model", "fake-model-mini"]

    assert client.get("/api/providers/models", params={"provider": "nope"}).status_code == 422


def test_evaluation_settings_validation_and_corrupt_defaults(monkeypatch, tmp_path):
    settings_path = tmp_path / "settings.json"
    monkeypatch.setattr(evaluation_config, "SETTINGS_PATH", settings_path)

    current = client.get("/api/settings/evaluation")
    assert current.status_code == 200
    assert len(current.json()["weights"]) == 9

    invalid = client.put(
        "/api/settings/evaluation",
        json={"weights": {"only_one": 1.0}, "thresholds": {}},
    )
    assert invalid.status_code == 422

    valid = client.put(
        "/api/settings/evaluation",
        json={
            "weights": current.json()["weights"],
            "thresholds": current.json()["thresholds"],
        },
    )
    assert valid.status_code == 200
    assert settings_path.exists()

    settings_path.write_text("{corrupt", encoding="utf-8")
    defaults = client.get("/api/settings/evaluation")
    assert defaults.status_code == 200
    assert defaults.json()["thresholds"]["approve"] == 85


def test_export_validation_and_missing_audit_deletion():
    assert client.post("/api/export", json={"format": "xml"}).status_code == 422
    assert client.post("/api/export", json={"audit_ids": "1,2"}).status_code == 422
    assert client.post("/api/export", json={"audit_ids": list(range(10001))}).status_code == 422
    assert client.get("/api/audits/99999999").status_code == 404
    assert client.delete("/api/audits/99999999").status_code == 404


def test_hybrid_route_requires_provider_and_rejects_unknown(monkeypatch):
    hybrid = {**audit_payload("HYBRID-NO-PROVIDER"), "evaluation_mode": "hybrid"}
    response = client.post("/api/audit", json=hybrid)
    assert response.status_code == 422
    assert "requires a provider" in response.text

    hybrid["provider"] = "not_a_provider"
    response = client.post("/api/audit", json=hybrid)
    assert response.status_code == 400
    assert "invalid" in response.text.lower()


def test_hybrid_route_persists_bounded_result(monkeypatch):
    request = EvaluationRequest(
        case_id="HYBRID-PERSIST",
        category="order_status",
        customer_message="Where is order ORD-1?",
        candidate_response="It shipped with tracking TRK-001.",
        facts={"order_id": "ORD-1", "tracking_number": "TRK-001"},
        expected_actions=["provide tracking"],
        severity="low",
        evaluation_mode="hybrid",
    )
    base = evaluate_deterministic(request)
    base.evaluation_mode = "hybrid"
    base.evaluator_model = "fake-qwen"

    async def fake_hybrid(*args, **kwargs):
        return base

    class FakeProvider:
        name = "custom"
        api_key = "fake-key"
        default_model = "fake-qwen"

    monkeypatch.setattr(audit_routes, "get_provider", lambda *a, **k: FakeProvider())
    monkeypatch.setattr(audit_routes, "evaluate_hybrid", fake_hybrid)
    monkeypatch.setattr(usage_service, "reserve_provider_usage", lambda *a, **k: None)

    payload = {**audit_payload("HYBRID-PERSIST"), "evaluation_mode": "hybrid", "provider": "custom"}
    response = client.post("/api/audit", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["evaluation_mode"] == "hybrid"
    assert result["evaluator_model"] == "fake-qwen"

    stored = client.get(f"/api/audits/{response.json()['audit_id']}").json()
    assert stored["evaluation_mode"] == "hybrid"
    assert stored["evaluator_model"] == "fake-qwen"
    assert client.delete(f"/api/audits/{response.json()['audit_id']}").status_code == 200


def test_evaluate_hybrid_without_provider_returns_deterministic():
    from auditor.evaluation.engine import evaluate_hybrid

    request = EvaluationRequest(
        customer_message="Where is order ORD-1?",
        candidate_response="Tracking TRK-001 is active.",
        evaluation_mode="hybrid",
    )
    result = asyncio.run(evaluate_hybrid(request, provider=None))
    assert result.evaluation_mode == "deterministic"
