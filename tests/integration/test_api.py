from fastapi.testclient import TestClient

from backend.app import create_app
from backend.database import init_db


def setup_module():
    init_db()


client = TestClient(create_app())


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_audit_deterministic():
    payload = {
        "customer_message": "Where is my order ORD-78421?",
        "candidate_response": "Your tracking is TRK-APX-992381 via FedEx, ETA June 20.",
        "facts": {"tracking_number": "TRK-APX-992381"},
        "evaluation_mode": "deterministic",
    }
    r = client.post("/api/audit", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "result" in data
    assert data["result"]["overall_score"] >= 0
    assert "dimension_scores" in data["result"]


def test_audit_privacy_hard_stop():
    payload = {
        "customer_message": "Send me card",
        "candidate_response": "Your full card number is 4111 1111 1111 1111 CVV 123 thank you",
        "facts": {},
        "evaluation_mode": "deterministic",
    }
    r = client.post("/api/audit", json=payload)
    assert r.status_code == 200
    assert r.json()["result"]["hard_stop_triggered"]
    assert r.json()["result"]["decision"] == "Critical Failure"


def test_batch():
    payload = {
        "cases": [
            {
                "customer_message": "Hi tracking for ORD-1?",
                "candidate_response": "Tracking TRK-123 via FedEx",
                "facts": {"tracking_number": "TRK-123"},
                "evaluation_mode": "deterministic",
            },
            {
                "customer_message": "Refund 45-day order",
                "candidate_response": "Refunded $200 instantly!",
                "facts": {"order_age_days": 45, "refund_window_days": 30, "refund_eligible": False},
                "evaluation_mode": "deterministic",
            },
        ],
        "evaluation_mode": "deterministic",
    }
    r = client.post("/api/audit/batch", json=payload)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


def test_batch_cannot_forge_synthetic_demo_provenance():
    payload = {
        "batch_id": "synthetic_demo_seed_v1",
        "evaluation_mode": "deterministic",
        "cases": [
            {
                "case_id": "PROVENANCE-GUARD-1",
                "customer_message": "Where is my order?",
                "candidate_response": "Please share your order number so I can check.",
            }
        ],
    }
    response = client.post("/api/audit/batch", json=payload)
    assert response.status_code == 422
    assert "reserved" in response.json()["detail"]


def test_list_audits():

    r = client.get("/api/audits?limit=5")
    assert r.status_code == 200
    assert "audits" in r.json()


def test_policies_list():
    r = client.get("/api/policies/")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 5


def test_cases():
    r = client.get("/api/cases?limit=5")
    assert r.status_code == 200
    assert r.json()["total"] >= 100


def test_analytics():
    r = client.get("/api/analytics/summary")
    assert r.status_code == 200
    assert "total" in r.json()
