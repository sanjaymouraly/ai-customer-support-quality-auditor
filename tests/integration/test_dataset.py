import json
from pathlib import Path

from auditor.datasets.loader import load_cases


def test_synthetic_loads():
    cases = load_cases()
    assert len(cases) >= 150
    assert any(c.label == "borderline" for c in cases)


def test_fields_present():
    cases = load_cases()
    for c in cases[:10]:
        assert c.case_id
        assert c.customer_message
        assert c.candidate_response
        assert c.expected_escalation
        assert (
            c.evaluation_metadata.get("label_provenance")
            == "synthetic_reference_design_not_human_reviewed"
        )


def test_categories_cover_all():
    cases = load_cases()
    needed = {"order_status", "refund_request", "privacy_fraud", "adversarial", "billing_dispute"}
    cats = set(c.category for c in cases)
    for n in needed:
        assert n in cats, f"Missing category {n}"


def test_annotations_exists():
    p = Path("data/annotations/illustrative_reference_labels.json")
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data) >= 1
    assert all("not_human_reviewed" in item["provenance"] for item in data)
