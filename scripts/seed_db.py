# ruff: noqa: E402
"""Seed the local database with clearly labelled synthetic demo audits.

These are machine evaluations of bundled synthetic cases. They are **not** human
annotations and must not be reported as operational quality results. The script only runs
against an empty audit table unless ``--force`` is supplied, and it never deletes data
itself.
"""

import sys
from pathlib import Path as _Path

ROOT = _Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auditor.datasets.loader import load_cases
from auditor.evaluation.config import get_evaluation_config
from auditor.evaluation.engine import evaluate_deterministic
from auditor.evaluation.schemas import EvaluationRequest
from backend.database import SessionLocal, init_db
from backend.models import AuditRecord
from backend.services.projects import create_project, ensure_default_project

DEMO_BATCH_ID = "synthetic_demo_seed_v1"


def _seed_project(db, project, cases, weights, thresholds):
    seeded = 0
    for case in cases:
        req = EvaluationRequest(
            case_id=case.case_id,
            category=case.category,
            customer_message=case.customer_message,
            candidate_response=case.candidate_response,
            facts=case.facts,
            expected_actions=case.expected_actions,
            expected_escalation=case.expected_escalation,
            severity=case.severity,
            policy_ids=case.policy_ids,
        )
        result = evaluate_deterministic(req, weights=weights, thresholds=thresholds)
        result.evaluation_config = {
            "weights": weights,
            "thresholds": thresholds,
            "rubric_version": "1.1",
            "project_id": project.project_id,
        }
        db.add(
            AuditRecord(
                batch_id=DEMO_BATCH_ID,
                project_id=project.project_id,
                case_id=result.case_id,
                category=case.category,
                customer_message=case.customer_message,
                candidate_response=case.candidate_response,
                facts=case.facts,
                policy_ids=case.policy_ids,
                expected_actions=case.expected_actions,
                expected_escalation=case.expected_escalation,
                severity=case.severity,
                evaluation_mode=result.evaluation_mode,
                evaluator_model=result.evaluator_model,
                overall_score=result.overall_score,
                decision=result.decision,
                decision_reason=result.decision_reason,
                dimension_scores=[d.model_dump() for d in result.dimension_scores],
                escalation=result.escalation.model_dump() if result.escalation else None,
                policy_refs=[p.model_dump() for p in result.policy_refs],
                config_snapshot=result.evaluation_config,
                hard_stop_triggered=result.hard_stop_triggered,
                hard_stop_reasons=result.hard_stop_reasons,
                missing_info=result.missing_info,
                improvement_suggestions=result.improvement_suggestions,
                evidence_highlights=result.evidence_highlights,
                hallucination_flags=result.hallucination_flags,
                uncertainty_flags=result.uncertainty_flags,
                strengths=result.strengths,
                confidence=result.confidence,
                confidence_basis=result.confidence_basis,
            )
        )
        seeded += 1
    return seeded


def main(n=60, force=False):
    init_db()
    db = SessionLocal()
    try:
        default = ensure_default_project(db)
        if db.query(AuditRecord).count() and not force:
            print("DB already contains audits; skipping synthetic demo seed (use --force to add).")
            return
        config = get_evaluation_config()
        weights = config.normalized_weights()
        thresholds = config.thresholds
        cases = load_cases()
        default_count = max(1, min(n, len(cases)))
        seeded = _seed_project(
            db, default, cases[:default_count], weights, thresholds
        )

        # A second, policy-scoped workspace demonstrates workspace filtering without
        # pretending to be a tenant security boundary.
        try:
            eu_project = create_project(
                db,
                "eu-support",
                "EU Support (demo)",
                "Demonstration workspace scoped to refund, shipping, and privacy policies.",
                ["refund_policy", "shipping_policy", "privacy_policy"],
            )
        except ValueError:
            from backend.models import Project

            eu_project = db.query(Project).filter(Project.project_id == "eu-support").first()
        remaining = cases[default_count : default_count + 30]
        if eu_project and remaining:
            seeded += _seed_project(
                db, eu_project, remaining, weights, thresholds
            )
        db.commit()
        print(
            f"Seeded {seeded} synthetic demo audits across "
            f"{2 if eu_project else 1} workspace(s). Batch ID: {DEMO_BATCH_ID}."
        )
        print("These are machine evaluations of synthetic cases, not human labels.")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=60, help="number of synthetic cases in the default workspace"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="add demo audits even if the table already contains audits (never deletes)",
    )
    args = parser.parse_args()
    main(n=max(1, min(args.n, 140)), force=args.force)
