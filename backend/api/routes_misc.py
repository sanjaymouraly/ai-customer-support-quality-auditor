from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from auditor.datasets.loader import load_cases

from ..database import get_db
from ..models import AuditRecord, HumanReview
from .schemas import ReviewCreate

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


@router.get("/cases")
def list_cases(
    category: str | None = None,
    severity: str | None = None,
    label: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    cases = load_cases()
    try:
        from backend.api.routes_scenarios import _load

        custom = [
            __import__("auditor.datasets.models", fromlist=["Case"]).Case(**row) for row in _load()
        ]
        cases.extend(custom)
    except Exception:
        pass
    from auditor.datasets.loader import filter_cases

    filtered = filter_cases(cases, category, severity, label, search)
    total = len(filtered)
    slice_ = filtered[offset : offset + limit]
    return {"total": total, "cases": [c.model_dump() for c in slice_]}


@router.get("/cases/{case_id}")
def get_case(case_id: str):
    cases = load_cases()
    try:
        from auditor.datasets.models import Case
        from backend.api.routes_scenarios import _load

        cases.extend([Case(**row) for row in _load()])
    except Exception:
        pass
    for c in cases:
        if c.case_id == case_id:
            return c.model_dump()
    from fastapi import HTTPException

    raise HTTPException(404, "Case not found")


@router.post("/reviews")
def create_review(payload: ReviewCreate, db: Session = Depends(get_db)):
    rec = db.query(AuditRecord).filter(AuditRecord.id == payload.audit_id).first()
    from fastapi import HTTPException

    if not rec:
        raise HTTPException(404, "Audit not found")
    if rec.hard_stop_triggered and payload.decision == "Approve":
        raise HTTPException(
            409,
            "Hard-stop audits cannot be approved through the review API; record a non-approval disposition.",
        )
    r = HumanReview(
        audit_id=payload.audit_id,
        reviewer_id=payload.reviewer_id,
        dimension_scores=(
            [item.model_dump() for item in payload.dimension_scores]
            if payload.dimension_scores is not None
            else None
        ),
        overall_score=payload.overall_score,
        decision=payload.decision,
        comments=payload.comments,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"review_id": r.id, "audit_id": r.audit_id}


@router.get("/reviews")
def list_reviews(audit_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(HumanReview).order_by(HumanReview.created_at.desc())
    if audit_id:
        q = q.filter(HumanReview.audit_id == audit_id)
    rows = q.limit(100).all()
    return {
        "reviews": [
            {
                "id": r.id,
                "audit_id": r.audit_id,
                "reviewer_id": r.reviewer_id,
                "decision": r.decision,
                "overall_score": r.overall_score,
                "comments": r.comments,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.get("/settings/evaluation")
def read_evaluation_settings():
    from auditor.evaluation.config import get_evaluation_config

    cfg = get_evaluation_config()
    return {
        "weights": cfg.normalized_weights(),
        "thresholds": cfg.thresholds,
        "dimensions": __import__(
            "auditor.evaluation.schemas", fromlist=["DIMENSION_LABELS"]
        ).DIMENSION_LABELS,
    }


@router.put("/settings/evaluation")
def update_evaluation_settings(payload: dict):
    from auditor.evaluation.config import save_evaluation_config

    try:
        cfg = save_evaluation_config(payload)
    except Exception as e:
        from fastapi import HTTPException

        raise HTTPException(
            422, "Invalid evaluation settings; check all nine weights and ordered thresholds"
        ) from e
    return {"weights": cfg.normalized_weights(), "thresholds": cfg.thresholds}


@router.get("/analytics/annotation-agreement")
def annotation_agreement(db: Session = Depends(get_db)):
    """Compute Cohen's kappa only where two independent reviewers label the same audit.
    Human reviews are distinct from synthetic reference labels; insufficient pairs are reported honestly.
    """
    from collections import defaultdict

    reviews = db.query(HumanReview).order_by(HumanReview.created_at).all()
    by_audit = defaultdict(list)
    for rev in reviews:
        if rev.decision:
            by_audit[rev.audit_id].append((rev.reviewer_id, rev.decision))
    paired = []
    for _audit_id, rows in by_audit.items():
        unique = {reviewer: decision for reviewer, decision in rows}
        reviewers = list(unique)
        if len(reviewers) >= 2:
            paired.append((unique[reviewers[0]], unique[reviewers[1]]))
    if len(paired) < 2:
        return {
            "status": "insufficient_data",
            "independent_pairs": len(paired),
            "cohen_kappa": None,
            "note": "At least two audits reviewed independently by two distinct reviewers are needed; AI/synthetic labels are not counted.",
        }
    a_labels = [a for a, b in paired]
    b_labels = [b for a, b in paired]
    n = len(paired)
    observed = sum(1 for a, b in paired if a == b) / n
    labels = set(a_labels) | set(b_labels)
    expected = sum((a_labels.count(label) / n) * (b_labels.count(label) / n) for label in labels)
    kappa = (
        1.0
        if expected == 1 and observed == 1
        else ((observed - expected) / (1 - expected) if expected < 1 else 0.0)
    )
    return {
        "status": "computed",
        "independent_pairs": len(paired),
        "cohen_kappa": float(kappa),
        "note": "Cohen's kappa on review decisions only; use a larger, stratified sample before drawing conclusions.",
    }


@router.get("/escalations")
def list_escalation_cases(
    urgency: str | None = None,
    verdict: str | None = None,
    category: str | None = None,
    project_id: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    query = db.query(AuditRecord)
    if project_id:
        query = query.filter(AuditRecord.project_id == project_id)
    rows = (
        query.order_by(AuditRecord.created_at.desc())
        .limit(min(max(limit, 1), 1000))
        .all()
    )
    items = []
    for row in rows:
        esc = row.escalation or {}
        if not esc:
            continue
        if urgency and esc.get("urgency") != urgency:
            continue
        if verdict and esc.get("verdict") != verdict:
            continue
        if category and row.category != category:
            continue
        if esc.get("expected") == "resolve" and esc.get("verdict") == "appropriate":
            continue
        items.append(
            {
                "audit_id": row.id,
                "case_id": row.case_id,
                "category": row.category,
                "decision": row.decision,
                "overall_score": row.overall_score,
                "expected": esc.get("expected"),
                "actual": esc.get("actual"),
                "verdict": esc.get("verdict"),
                "urgency": esc.get("urgency"),
                "destination": esc.get("destination"),
                "reason": esc.get("reason"),
                "evidence": esc.get("evidence"),
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )
    return {"total": len(items), "cases": items}


@router.get("/analytics/escalations-by-category")
def escalation_trends(project_id: str | None = None, db: Session = Depends(get_db)):
    from collections import defaultdict

    matrix = defaultdict(
        lambda: {"appropriate": 0, "under_escalation": 0, "over_escalation": 0, "other": 0}
    )
    query = db.query(AuditRecord)
    if project_id:
        query = query.filter(AuditRecord.project_id == project_id)
    for row in query.all():
        esc = row.escalation or {}
        if not esc:
            continue
        category = row.category or "uncategorized"
        verdict = esc.get("verdict", "other")
        matrix[category][
            verdict
            if verdict in ("appropriate", "under_escalation", "over_escalation")
            else "other"
        ] += 1
    return {"categories": [{"category": k, **v} for k, v in sorted(matrix.items())]}


@router.get("/analytics/trends")
def trends(project_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(AuditRecord)
    if project_id:
        query = query.filter(AuditRecord.project_id == project_id)
    rows = query.order_by(AuditRecord.created_at).all()
    # group by date
    from collections import defaultdict

    by_date = defaultdict(list)
    for r in rows:
        d = r.created_at.date().isoformat() if r.created_at else "unknown"
        by_date[d].append(r.overall_score or 0)
    trend = [
        {"date": k, "avg_score": round(sum(v) / len(v), 1) if v else 0, "count": len(v)}
        for k, v in sorted(by_date.items())
    ]
    return {"trend": trend}


@router.post("/export")
def export_audits(payload: dict, db: Session = Depends(get_db)):
    """Export audit results without raw customer text. CSV values are formula-safe; HTML is escaped."""
    import csv
    import html
    import io
    import json

    from auditor.reports.export import safe_audit_summaries
    from auditor.security.validators import sanitize_csv_value

    fmt = payload.get("format", "json").lower()
    ids = payload.get("audit_ids")
    q = db.query(AuditRecord)
    if ids:
        if not isinstance(ids, list) or len(ids) > 10000:
            raise HTTPException(422, "audit_ids must be a list of at most 10000 IDs")
        q = q.filter(AuditRecord.id.in_(ids))
    rows = q.order_by(AuditRecord.created_at.desc()).all()
    audits = []
    for r in rows:
        audits.append(
            {
                "id": r.id,
                "case_id": r.case_id,
                "category": r.category,
                "overall_score": r.overall_score,
                "decision": r.decision,
                "decision_reason": r.decision_reason,
                "evaluation_mode": r.evaluation_mode,
                "evaluator_model": r.evaluator_model,
                "confidence": r.confidence,
                "hard_stop_triggered": r.hard_stop_triggered,
                "hard_stop_reasons": r.hard_stop_reasons,
                "dimension_scores": r.dimension_scores,
                "escalation": r.escalation,
                "policy_refs": r.policy_refs,
                "missing_info": r.missing_info,
                "improvement_suggestions": r.improvement_suggestions,
                "uncertainty_flags": r.uncertainty_flags,
                "config_snapshot": r.config_snapshot,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    audits = safe_audit_summaries(audits)
    if fmt == "json":
        content = json.dumps(
            {"exported_count": len(audits), "audits": audits}, indent=2, ensure_ascii=False
        )
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audits.json"},
        )
    if fmt == "csv":
        fields = [
            "id",
            "case_id",
            "category",
            "overall_score",
            "decision",
            "evaluation_mode",
            "evaluator_model",
            "confidence",
            "hard_stop_triggered",
            "escalation_verdict",
            "escalation_expected",
            "escalation_actual",
            "dimension_scores_json",
            "created_at",
        ]
        buf = io.StringIO(newline="")
        writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for audit in audits:
            escalation = audit.get("escalation") or {}
            dims = {d.get("dimension"): d.get("score") for d in audit.get("dimension_scores") or []}
            row = {
                **audit,
                "escalation_verdict": escalation.get("verdict"),
                "escalation_expected": escalation.get("expected"),
                "escalation_actual": escalation.get("actual"),
                "dimension_scores_json": json.dumps(dims, ensure_ascii=False),
            }
            writer.writerow(
                {
                    key: sanitize_csv_value(str(row.get(key, "")))
                    if row.get(key) is not None
                    else ""
                    for key in fields
                }
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audits.csv"},
        )
    if fmt == "html":
        tr = []
        for audit in audits:
            dims = "; ".join(
                f"{html.escape(str(d.get('dimension', '')))}: {int(d.get('score', 0))}/4"
                for d in audit.get("dimension_scores") or []
            )
            tr.append(
                "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                    html.escape(str(audit.get("case_id") or "")),
                    html.escape(str(audit.get("category") or "")),
                    html.escape(str(audit.get("overall_score") or "")),
                    html.escape(str(audit.get("decision") or "")),
                    dims,
                )
            )
        document = (
            """<!doctype html><html><head><meta charset='utf-8'><title>Auditor report</title>
<style>body{font:14px system-ui,Arial;margin:32px;color:#142033}h1{color:#12233e}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d8dfeb;padding:8px;text-align:left}th{background:#12233e;color:white}tr:nth-child(even){background:#f6f8fb}.note{color:#52627a}</style></head><body><h1>Customer Support Audit Report</h1><p class='note'>Summary only. Raw customer messages are excluded from this export.</p><table><thead><tr><th>Case</th><th>Category</th><th>Score</th><th>Decision</th><th>Dimension scores</th></tr></thead><tbody>"""
            + "".join(tr)
            + "</tbody></table></body></html>"
        )
        return Response(
            content=document,
            media_type="text/html",
            headers={"Content-Disposition": "attachment; filename=audits.html"},
        )
    raise HTTPException(422, "format must be json, csv, or html")
