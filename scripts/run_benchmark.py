"""Run deterministic checks over the synthetic development benchmark.

Outputs are exploratory comparisons against synthetic reference dispositions, not human labels
or validated model accuracy. This dataset is used in development and is not a holdout set.
"""
# ruff: noqa: E402

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from collections import Counter, defaultdict

from auditor.datasets.loader import load_cases
from auditor.evaluation.engine import evaluate_deterministic
from auditor.evaluation.schemas import EvaluationRequest


def main(limit=None):
    cases = load_cases()
    if limit:
        cases = cases[:limit]
    rows = []
    for c in cases:
        req = EvaluationRequest(
            case_id=c.case_id,
            category=c.category,
            customer_message=c.customer_message,
            candidate_response=c.candidate_response,
            facts=c.facts,
            expected_actions=c.expected_actions,
            expected_escalation=c.expected_escalation,
            severity=c.severity,
            policy_ids=c.policy_ids,
        )
        result = evaluate_deterministic(req)
        predicted = (
            "positive"
            if result.decision == "Approve"
            else "negative"
            if result.decision in ("Needs Revision", "Escalation Required", "Critical Failure")
            else "borderline"
        )
        rows.append(
            {
                "case_id": c.case_id,
                "reference_label": c.label,
                "predicted_disposition": predicted,
                "decision": result.decision,
                "overall_score": result.overall_score,
                "severity": c.severity,
                "hard_stop": result.hard_stop_triggered,
                "evaluation_mode": result.evaluation_mode,
                "evaluator": "rule-engine-v1",
                "provenance": "machine_generated_not_human_reviewed",
            }
        )

    scored = [row for row in rows if row["reference_label"] in ("positive", "negative")]
    agreement = (
        sum(row["predicted_disposition"] == row["reference_label"] for row in scored) / len(scored)
        if scored
        else None
    )
    matrix = {
        label: {pred: 0 for pred in ["positive", "negative", "borderline"]}
        for label in ["positive", "negative"]
    }
    for row in scored:
        matrix[row["reference_label"]][row["predicted_disposition"]] += 1
    by_severity = defaultdict(Counter)
    for row in rows:
        by_severity[row["severity"]][row["decision"]] += 1
    report = {
        "provenance": "Exploratory rule-engine output over a development benchmark; synthetic reference dispositions are not human-reviewed ground truth and do not establish accuracy.",
        "total_cases": len(rows),
        "reference_labelled_pos_neg_cases": len(scored),
        "illustrative_reference_agreement": round(agreement, 4) if agreement is not None else None,
        "confusion_matrix_reference_vs_predicted": matrix,
        "decision_distribution": dict(Counter(row["decision"] for row in rows)),
        "by_severity": {key: dict(value) for key, value in by_severity.items()},
        "cases": rows,
    }
    print(f"Cases: {len(rows)}; synthetic pos/neg reference cases: {len(scored)}")
    print(
        f"Illustrative reference agreement (not validated accuracy): {agreement:.1%}"
        if agreement is not None
        else "No binary reference cases"
    )
    print("Decision distribution:", report["decision_distribution"])
    print("Confusion matrix:", matrix)
    Path("data/annotations").mkdir(parents=True, exist_ok=True)
    Path("data/annotations/benchmark_results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("Saved machine-generated report to data/annotations/benchmark_results.json")
    return report


if __name__ == "__main__":
    main()
