"""Report export helpers: redaction, CSV safety, and HTML escaping."""

from __future__ import annotations

import csv
import json

from auditor.reports.export import (
    export_csv,
    export_html,
    export_json,
    safe_audit_summary,
)

AUDITS = [
    {
        "id": 1,
        "case_id": '=HYPERLINK("https://bad")',
        "category": "refund",
        "overall_score": 42,
        "decision": "Needs Revision",
        "evaluation_mode": "deterministic",
        "evaluator_model": "rule-engine-v1",
        "confidence": 0.5,
        "hard_stop_triggered": False,
        "config_snapshot": {"project_id": "default", "note": "jane@example.com"},
        "escalation": {
            "expected": "resolve",
            "actual": "resolve",
            "correct": True,
            "verdict": "appropriate",
            "urgency": "low",
            "destination": "none",
            "reason": "contact jane@example.com",
        },
        "dimension_scores": [
            {"dimension": "factual_accuracy", "score": 2, "confidence": 0.7, "explanation": "x"},
            {"dimension": "tone_clarity", "score": 3, "confidence": 0.6, "explanation": "y"},
        ],
        "policy_refs": [
            {"policy_id": "refund_policy", "version": "2.1", "section": "Window", "excerpt": "x"}
        ],
        "customer_message": "secret customer text",
    }
]


def test_safe_summary_omits_raw_and_freeform_text():
    summary = safe_audit_summary(AUDITS[0])
    dumped = json.dumps(summary)
    assert "secret customer text" not in dumped
    assert "jane@example.com" not in dumped
    assert "excerpt" not in dumped
    assert summary["dimension_scores"][0] == {
        "dimension": "factual_accuracy",
        "score": 2,
        "confidence": 0.7,
    }


def test_file_exports_are_safe(tmp_path):
    csv_path = tmp_path / "audits.csv"
    json_path = tmp_path / "audits.json"
    html_path = tmp_path / "audits.html"
    export_csv(AUDITS, csv_path)
    export_json(AUDITS, json_path)
    export_html(
        [{**AUDITS[0], "case_id": "<script>alert(1)</script>"}],
        html_path,
        title="<Report>",
    )

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert rows[0]["case_id"].startswith("'=")
    assert rows[0]["dim_factual_accuracy"] == "2"
    assert rows[0]["escalation.verdict"] == "appropriate"

    exported = json_path.read_text(encoding="utf-8")
    assert "secret customer text" not in exported
    assert "jane@example.com" not in exported

    document = html_path.read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in document
    assert "&lt;script&gt;" in document
    assert "&lt;Report&gt;" in document


def test_empty_export_csv_is_a_noop(tmp_path):
    path = tmp_path / "empty.csv"
    export_csv([], path)
    assert not path.exists()
