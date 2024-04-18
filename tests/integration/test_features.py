from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database import init_db


def setup_module():
    init_db()


client = TestClient(create_app())


def audit_payload(case_id="FEATURE-1", candidate="Please check order ORD-1 tracking TRK-001."):
    return {
        "case_id": case_id,
        "category": "order_status",
        "customer_message": "Where is order ORD-1?",
        "candidate_response": candidate,
        "facts": {"order_id": "ORD-1", "tracking_number": "TRK-001"},
        "expected_actions": ["provide tracking"],
        "severity": "low",
        "evaluation_mode": "deterministic",
    }


def test_audit_persists_full_provenance():
    r = client.post("/api/audit", json=audit_payload())
    assert r.status_code == 200, r.text
    audit_id = r.json()["audit_id"]
    record = client.get(f"/api/audits/{audit_id}")
    assert record.status_code == 200
    body = record.json()
    assert body["config_snapshot"]["weights"]["policy_compliance"] > 0
    assert body["dimension_scores"]
    assert body["evidence_highlights"] is not None
    assert body["uncertainty_flags"] is not None


def test_batch_resume_and_hash_protection():
    payload = {
        "batch_id": "FEATURE-BATCH-RESUME",
        "cases": [
            audit_payload("BATCH-A"),
            audit_payload("BATCH-B", "Sure, your order is delivered tomorrow."),
        ],
        "evaluation_mode": "deterministic",
    }
    first = client.post("/api/audit/batch", json=payload)
    assert first.status_code == 200, first.text
    batch_id = first.json()["batch_id"]
    ids = [row["audit_id"] for row in first.json()["results"]]
    assert len(ids) == 2
    get = client.get(f"/api/batches/{batch_id}")
    assert get.status_code == 200 and get.json()["persisted_items"] == 2
    payload["resume"] = True
    second = client.post("/api/audit/batch", json=payload)
    assert second.status_code == 200
    assert second.json()["resumed_count"] == 2
    assert [row["audit_id"] for row in second.json()["results"]] == ids
    payload["cases"][0]["candidate_response"] = "Changed response"
    changed = client.post("/api/audit/batch", json=payload)
    assert changed.status_code == 200
    assert "hash mismatch" in changed.json()["results"][0]["error"].lower()


def test_batch_invalid_duplicate_ids_and_resume_without_id():
    duplicated = {
        "cases": [audit_payload("DUP"), audit_payload("DUP")],
        "evaluation_mode": "deterministic",
    }
    assert client.post("/api/audit/batch", json=duplicated).status_code == 422
    missing = {"cases": [audit_payload("ONE")], "resume": True}
    assert client.post("/api/audit/batch", json=missing).status_code == 422


def test_safe_export_formula_injection_and_html_escape():
    payload = audit_payload('=HYPERLINK("https://bad")')
    response = client.post("/api/audit", json=payload)
    assert response.status_code == 200
    audit_id = response.json()["audit_id"]
    csv_response = client.post("/api/export", json={"format": "csv", "audit_ids": [audit_id]})
    assert csv_response.status_code == 200
    assert "'=HYPERLINK" in csv_response.text
    json_response = client.post("/api/export", json={"format": "json", "audit_ids": [audit_id]})
    assert json_response.status_code == 200
    assert "Where is order ORD-1?" not in json_response.text
    assert "Please check order ORD-1 tracking TRK-001." not in json_response.text
    html_response = client.post("/api/export", json={"format": "html", "audit_ids": [audit_id]})
    assert html_response.status_code == 200
    assert "&lt;script&gt;" not in html_response.text
    assert "HYPERLINK" in html_response.text


def test_json_export_redacts_pii_from_evidence_and_omits_raw_text():
    payload = audit_payload(
        "EXPORT-PII", "Your refund has been processed; contact jane@example.com."
    )
    payload["facts"] = {"refund_eligible": False}
    response = client.post("/api/audit", json=payload)
    assert response.status_code == 200
    audit_id = response.json()["audit_id"]
    exported = client.post("/api/export", json={"format": "json", "audit_ids": [audit_id]})
    assert exported.status_code == 200
    assert "jane@example.com" not in exported.text
    assert "Your refund has been processed; contact" not in exported.text
    assert '"evidence"' not in exported.text
    assert '"excerpt"' not in exported.text


def test_custom_scenario_lifecycle_and_path_guard():
    case = {
        "case_id": "USR-TEST-API",
        "category": "insufficient_info",
        "customer_message": "I need help with an order.",
        "facts": {},
        "policy_ids": [],
        "candidate_response": "Please share the order ID.",
        "expected_actions": ["ask for order ID"],
        "expected_escalation": "ask_info",
        "severity": "medium",
        "label": "borderline",
        "notes": "api test",
        "evaluation_metadata": {},
    }
    created = client.post("/api/scenarios", json=case)
    assert created.status_code == 200, created.text
    listed = client.get("/api/cases/USR-TEST-API")
    assert listed.status_code == 200
    assert (
        listed.json()["evaluation_metadata"]["label_provenance"]
        == "user_authored_reference_not_human_reviewed"
    )
    assert client.delete("/api/scenarios/USR-TEST-API").status_code == 200
    bad = dict(case, case_id="../x")
    assert client.post("/api/scenarios", json=bad).status_code == 422


def test_settings_providers_escalations_and_agreement():
    assert client.get("/api/settings/evaluation").status_code == 200
    offline = client.post("/api/providers/test", json={"provider": "offline"})
    assert offline.status_code == 200 and offline.json()["ok"] is True
    assert client.get("/api/providers/usage").status_code == 200
    assert client.get("/api/escalations").status_code == 200
    assert client.get("/api/analytics/escalations-by-category").status_code == 200
    agreement = client.get("/api/analytics/annotation-agreement")
    assert agreement.status_code == 200 and agreement.json()["status"] in (
        "computed",
        "insufficient_data",
    )


def test_provider_model_discovery_missing_credentials_safe():
    from unittest.mock import AsyncMock, patch

    with patch(
        "auditor.providers.openai_provider.OpenAIProvider.list_models",
        new=AsyncMock(side_effect=RuntimeError("Provider credentials are not configured")),
    ) as list_models:
        response = client.get("/api/providers/models", params={"provider": "openai"})
    assert response.status_code == 200
    assert response.json()["models"] == []
    assert "failed" in response.json()["error"].lower()
    list_models.assert_awaited_once()


def test_optional_api_token_auth(monkeypatch):
    monkeypatch.setenv("API_ACCESS_TOKEN", "test-token-123")
    secure = TestClient(create_app())
    assert secure.get("/api/health").status_code == 200
    assert secure.get("/api/providers").status_code == 401
    assert (
        secure.get("/api/providers", headers={"Authorization": "Bearer test-token-123"}).status_code
        == 200
    )


def test_human_review_is_separate_and_validated():
    response = client.post("/api/audit", json=audit_payload("REVIEW-IMMUTABLE"))
    assert response.status_code == 200
    audit_id = response.json()["audit_id"]
    before = client.get(f"/api/audits/{audit_id}").json()
    dimensions = [
        {"dimension": item["dimension"], "score": 4, "reviewer_explanation": "checked"}
        for item in before["dimension_scores"]
    ]
    submitted = client.post(
        "/api/reviews",
        json={
            "audit_id": audit_id,
            "reviewer_id": " reviewer-blue ",
            "dimension_scores": dimensions,
            "overall_score": 96,
            "decision": "Approve",
            "comments": "Independent human review.",
        },
    )
    assert submitted.status_code == 200, submitted.text
    after = client.get(f"/api/audits/{audit_id}").json()
    assert after["decision"] == before["decision"]
    assert after["overall_score"] == before["overall_score"]
    assert after["dimension_scores"] == before["dimension_scores"]
    reviews = client.get("/api/reviews", params={"audit_id": audit_id}).json()["reviews"]
    assert reviews[0]["reviewer_id"] == "reviewer-blue"
    assert reviews[0]["decision"] == "Approve"
    assert (
        client.post(
            "/api/reviews",
            json={"audit_id": audit_id, "reviewer_id": "x", "decision": "Invented"},
        ).status_code
        == 422
    )


def test_hard_stop_cannot_be_human_approved():
    result = client.post(
        "/api/audit",
        json={
            "case_id": "HARDSTOP-REVIEW",
            "customer_message": "Please help with my card.",
            "candidate_response": "Your card number is 4111 1111 1111 1111.",
            "evaluation_mode": "deterministic",
        },
    )
    assert result.status_code == 200
    audit_id = result.json()["audit_id"]
    review = client.post(
        "/api/reviews",
        json={"audit_id": audit_id, "reviewer_id": "reviewer", "decision": "Approve"},
    )
    assert review.status_code == 409
    stored = client.get(f"/api/audits/{audit_id}").json()
    assert stored["hard_stop_triggered"] is True
    assert stored["decision"] == "Critical Failure"


def test_policy_upload_versions_and_unsupported_extension(monkeypatch, tmp_path):
    import backend.api.routes_policies as routes
    from auditor.policies.store import load_policies_from_dir

    real_policy_dir = routes.POLICY_DIR
    monkeypatch.setattr(routes, "POLICY_DIR", tmp_path)
    try:
        data = {"title": "Upload test", "policy_id": "upload_test", "category": "refund"}
        first = client.post(
            "/api/policies/ingest",
            data={**data, "version": "1.0", "effective_date": "2025-01-01"},
            files={"file": ("policy.md", b"## Window\nRefunds within 14 days.", "text/markdown")},
        )
        assert first.status_code == 200, first.text
        second = client.post(
            "/api/policies/ingest",
            data={**data, "version": "2.0", "effective_date": "2026-01-01"},
            files={"file": ("policy.txt", b"## Window\nRefunds within 30 days.", "text/plain")},
        )
        assert second.status_code == 200, second.text
        versions = client.get("/api/policies/upload_test/versions").json()
        assert {item["version"] for item in versions} == {"1.0", "2.0"}
        assert sum(item["status"] == "active" for item in versions) == 1
        invalid = client.post(
            "/api/policies/ingest",
            data=data,
            files={"file": ("policy.exe", b"bad", "application/octet-stream")},
        )
        assert invalid.status_code == 415
        import auditor.security.validators as validators

        monkeypatch.setattr(validators, "MAX_UPLOAD_MB", 1)
        oversized = client.post(
            "/api/policies/ingest",
            data=data,
            files={"file": ("policy.txt", b"x" * (1024 * 1024 + 1), "text/plain")},
        )
        assert oversized.status_code == 413
    finally:
        load_policies_from_dir(real_policy_dir)
