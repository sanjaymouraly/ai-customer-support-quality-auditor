"""Workspace profiles and project-scoped audit provenance."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database import init_db


def setup_module():
    init_db()


client = TestClient(create_app())


def payload(project_id: str | None = None, case_id: str = "PROJECT-AUDIT") -> dict:
    data = {
        "case_id": case_id,
        "category": "order_status",
        "customer_message": "Where is order ORD-1?",
        "candidate_response": "It shipped with tracking TRK-001.",
        "facts": {"order_id": "ORD-1", "tracking_number": "TRK-001"},
        "expected_actions": ["provide tracking"],
        "severity": "low",
        "evaluation_mode": "deterministic",
    }
    if project_id:
        data["project_id"] = project_id
    return data


def test_default_project_is_available():
    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()["projects"]
    default = next(item for item in projects if item["is_default"])
    assert default["project_id"] == "default"
    assert "audit_count" in default


def test_project_lifecycle_policy_scope_and_audit_provenance():
    created = client.post(
        "/api/projects",
        json={
            "project_id": "test-project",
            "name": "Test project",
            "description": "integration test",
            "policy_ids": ["refund_policy", "shipping_policy"],
        },
    )
    assert created.status_code == 200, created.text
    assert set(created.json()["project"]["policy_ids"]) == {
        "refund_policy",
        "shipping_policy",
    }

    duplicate = client.post(
        "/api/projects",
        json={
            "project_id": "test-project",
            "name": "Duplicate",
            "description": "",
            "policy_ids": [],
        },
    )
    assert duplicate.status_code == 422

    unknown_policy = client.post(
        "/api/projects",
        json={
            "project_id": "unknown-policy-project",
            "name": "Bad",
            "description": "",
            "policy_ids": ["not_a_real_policy"],
        },
    )
    assert unknown_policy.status_code == 422

    audited = client.post("/api/audit", json=payload("test-project", "PROJECT-POLICY"))
    assert audited.status_code == 200, audited.text
    audit_id = audited.json()["audit_id"]
    stored = client.get(f"/api/audits/{audit_id}").json()
    assert stored["project_id"] == "test-project"
    assert set(stored["policy_ids"]) == {"refund_policy", "shipping_policy"}
    assert stored["config_snapshot"]["project_id"] == "test-project"
    assert stored["expected_actions"] == ["provide tracking"]

    filtered = client.get(
        "/api/audits", params={"project_id": "test-project", "limit": 500}
    )
    assert filtered.status_code == 200
    assert all(row["project_id"] == "test-project" for row in filtered.json()["audits"])

    summary = client.get(
        "/api/analytics/summary", params={"project_id": "test-project"}
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["total"] >= 1
    assert "dimension_averages" in body
    assert "hard_stop_rate" in body

    updated = client.put(
        "/api/projects/test-project",
        json={
            "name": "Renamed project",
            "description": "updated",
            "policy_ids": ["warranty_policy"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["project"]["name"] == "Renamed project"
    assert updated.json()["project"]["policy_ids"] == ["warranty_policy"]

    blocked = client.delete("/api/projects/test-project")
    assert blocked.status_code == 409
    assert "saved audits" in blocked.text.lower()

    # Clean up audit then project so the test database stays tidy.
    assert client.delete(f"/api/audits/{audit_id}").status_code == 200
    deleted = client.delete("/api/projects/test-project")
    assert deleted.status_code == 200

    default_delete = client.delete("/api/projects/default")
    assert default_delete.status_code == 409


def test_unknown_project_rejected():
    response = client.post("/api/audit", json=payload("does-not-exist", "MISSING-PROJECT"))
    assert response.status_code == 422
    assert "Unknown project_id" in response.text


def test_audit_filters_and_analytics_fields():
    response = client.post(
        "/api/audit",
        json={
            **payload(None, "FILTER-ANALYTICS"),
            "severity": "high",
            "candidate_response": "Your card number is 4111 1111 1111 1111.",
        },
    )
    assert response.status_code == 200
    audit_id = response.json()["audit_id"]
    stored = client.get(f"/api/audits/{audit_id}").json()
    assert stored["hard_stop_triggered"] is True

    hard_stops = client.get("/api/audits", params={"hard_stop": True, "limit": 1000})
    assert hard_stops.status_code == 200
    assert any(row["id"] == audit_id for row in hard_stops.json()["audits"])

    severities = client.get(
        "/api/audits", params={"severity": "high", "limit": 1000}
    )
    assert severities.status_code == 200
    assert all(row["severity"] == "high" for row in severities.json()["audits"])

    summary = client.get("/api/analytics/summary").json()
    assert summary["hard_stop_rate"] > 0
    assert summary["by_severity"].get("high", 0) >= 1
    assert summary["by_escalation"]
    assert client.delete(f"/api/audits/{audit_id}").status_code == 200
