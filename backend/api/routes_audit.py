from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auditor.evaluation.config import get_evaluation_config
from auditor.evaluation.engine import evaluate_deterministic, evaluate_hybrid
from auditor.evaluation.schemas import EvaluationRequest
from auditor.providers.registry import get_provider

from ..database import get_db
from ..models import AuditRecord
from .schemas import AuditRequest, BatchRequest

router = APIRouter(prefix="/api", tags=["audit"])


def _usage_prompt_text(req: EvaluationRequest) -> str:
    from auditor.policies.retrieval import retrieve_for_case

    policy_text = "\n".join(
        item.excerpt[:500]
        for item in retrieve_for_case(
            req.customer_message,
            req.candidate_response,
            req.policy_ids,
            top_k=4,
            category=req.category,
        )
    )
    return "\n".join(
        [
            req.customer_message,
            req.candidate_response,
            json.dumps(req.facts, ensure_ascii=False),
            json.dumps(req.expected_actions, ensure_ascii=False),
            req.expected_escalation or "",
            req.category or "",
            req.severity,
            policy_text,
        ]
    )


def _req_to_eval(req: AuditRequest) -> EvaluationRequest:
    # Keep the submitted text intact. The LLM prompt explicitly frames every supplied
    # field as untrusted data; deterministic rules do not execute instructions. A small
    # injection detector adds an uncertainty flag in the engine.
    return EvaluationRequest(
        case_id=req.case_id,
        category=req.category,
        customer_message=req.customer_message[:4000],
        candidate_response=req.candidate_response[:4000],
        facts=req.facts,
        expected_actions=req.expected_actions,
        expected_escalation=req.expected_escalation,
        severity=req.severity,
        policy_ids=req.policy_ids,
        evaluation_mode=req.evaluation_mode,
        provider=req.provider,
        model=req.model,
        temperature=req.temperature,
    )


@router.post("/audit")
async def audit_single(req: AuditRequest, db: Session = Depends(get_db)):
    from backend.services.projects import effective_policy_ids, resolve_project

    try:
        project = resolve_project(db, req.project_id)
    except LookupError as exc:
        raise HTTPException(422, str(exc)) from exc
    try:
        req.policy_ids = effective_policy_ids(db, project.project_id, req.policy_ids)
    except (LookupError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    if req.evaluation_mode in ("llm", "hybrid") and not req.provider:
        raise HTTPException(
            422,
            "LLM/hybrid evaluation requires a provider. Use deterministic mode or configure a provider.",
        )
    ereq = _req_to_eval(req)
    provider = None
    config = get_evaluation_config()
    weights = config.normalized_weights()
    thresholds = config.thresholds
    if ereq.evaluation_mode in ("llm", "hybrid") and req.provider and req.provider != "offline":
        try:
            provider = get_provider(req.provider, {})
        except Exception as e:
            raise HTTPException(400, "Provider configuration is invalid") from e
        from backend.services.usage import reserve_provider_usage

        prompt_text = _usage_prompt_text(ereq)
        if getattr(provider, "api_key", None) or getattr(provider, "name", "") in (
            "custom",
            "ollama",
        ):
            try:
                reserve_provider_usage(
                    db,
                    req.provider,
                    req.model or getattr(provider, "default_model", None),
                    prompt_text,
                )
            except ValueError as e:
                raise HTTPException(429, str(e)) from e
        result = await evaluate_hybrid(
            ereq, provider, req.model, weights=weights, thresholds=thresholds
        )
    else:
        result = evaluate_deterministic(ereq, weights=weights, thresholds=thresholds)
    result.evaluation_config = {
        "weights": weights,
        "thresholds": thresholds,
        "rubric_version": "1.1",
        "project_id": project.project_id,
    }
    # persist
    rec = AuditRecord(
        case_id=result.case_id or req.case_id,
        project_id=project.project_id,
        category=req.category,
        customer_message=req.customer_message,
        candidate_response=req.candidate_response,
        facts=req.facts,
        policy_ids=req.policy_ids,
        expected_actions=req.expected_actions,
        expected_escalation=req.expected_escalation,
        severity=req.severity,
        evaluation_mode=result.evaluation_mode,
        evaluator_model=result.evaluator_model,
        responder_model=req.responder_model,
        config_snapshot=result.evaluation_config,
        overall_score=result.overall_score,
        decision=result.decision,
        decision_reason=result.decision_reason,
        dimension_scores=[d.model_dump() for d in result.dimension_scores],
        escalation=result.escalation.model_dump() if result.escalation else None,
        policy_refs=[p.model_dump() for p in result.policy_refs],
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
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"audit_id": rec.id, "result": result.model_dump()}


def _batch_hash(case: AuditRequest, weights: dict, thresholds: dict, project_id: str | None) -> str:
    import hashlib

    canonical = json.dumps(
        {
            "case": case.model_dump(),
            "weights": weights,
            "thresholds": thresholds,
            "project_id": project_id,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _result_from_record(rec: AuditRecord) -> dict:
    from auditor.evaluation.schemas import AuditResult

    return AuditResult(
        case_id=rec.case_id,
        overall_score=rec.overall_score or 0,
        dimension_scores=rec.dimension_scores or [],
        decision=rec.decision or "Human Review Required",
        decision_reason=rec.decision_reason or "Resumed from persisted batch record.",
        escalation=rec.escalation,
        policy_refs=rec.policy_refs or [],
        hard_stop_triggered=bool(rec.hard_stop_triggered),
        hard_stop_reasons=rec.hard_stop_reasons or [],
        missing_info=rec.missing_info or [],
        improvement_suggestions=rec.improvement_suggestions or [],
        evidence_highlights=rec.evidence_highlights or [],
        hallucination_flags=rec.hallucination_flags or [],
        uncertainty_flags=rec.uncertainty_flags or [],
        strengths=rec.strengths or [],
        confidence=rec.confidence or 0.0,
        confidence_basis=rec.confidence_basis or "Heuristic confidence; not calibrated.",
        evaluation_mode=rec.evaluation_mode or "deterministic",
        evaluator_model=rec.evaluator_model,
        evaluation_config=rec.config_snapshot,
    ).model_dump()


@router.post("/audit/batch")
async def audit_batch(payload: BatchRequest, db: Session = Depends(get_db)):
    import re
    import uuid

    from backend.services.projects import effective_policy_ids, resolve_project

    results = []
    batch_id = payload.batch_id or str(uuid.uuid4())
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", batch_id):
        raise HTTPException(
            422, "batch_id may contain only letters, digits, underscore, and hyphen"
        )
    if batch_id == "synthetic_demo_seed_v1":
        raise HTTPException(422, "batch_id is reserved for bundled synthetic demo provenance")
    if payload.resume and not payload.batch_id:
        raise HTTPException(422, "batch_id is required when resume=true")
    if payload.evaluation_mode in ("llm", "hybrid") and not payload.provider:
        raise HTTPException(
            422,
            "LLM/hybrid batch evaluation requires a provider. Use deterministic mode or configure a provider.",
        )
    ids = [case.case_id for case in payload.cases if case.case_id]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "case_id values must be unique within a batch")
    try:
        project = resolve_project(db, payload.project_id)
    except LookupError as exc:
        raise HTTPException(422, str(exc)) from exc
    prior_count = db.query(AuditRecord).filter(AuditRecord.batch_id == batch_id).count()
    if prior_count and not payload.resume:
        raise HTTPException(409, "batch_id already exists; set resume=true or use a new batch_id")
    provider = None
    if (
        payload.evaluation_mode in ("llm", "hybrid")
        and payload.provider
        and payload.provider != "offline"
    ):
        try:
            provider = get_provider(payload.provider, {})
        except Exception as e:
            raise HTTPException(400, "Provider configuration is invalid") from e
    resumed = 0
    for idx, case in enumerate(payload.cases):
        if payload.evaluation_mode:
            case.evaluation_mode = payload.evaluation_mode
        if payload.provider:
            case.provider = payload.provider
        if payload.model:
            case.model = payload.model
        try:
            case.project_id = project.project_id
            case.policy_ids = effective_policy_ids(db, project.project_id, case.policy_ids)
        except (LookupError, ValueError) as exc:
            results.append(
                {"index": idx, "case_id": case.case_id, "result": None, "error": str(exc)}
            )
            continue
        item_key = case.case_id or f"item-{idx + 1}"
        ereq = _req_to_eval(case)
        config = get_evaluation_config()
        weights = config.normalized_weights()
        thresholds = config.thresholds
        digest = _batch_hash(case, weights, thresholds, project.project_id)
        existing = (
            db.query(AuditRecord)
            .filter(AuditRecord.batch_id == batch_id, AuditRecord.batch_item_key == item_key)
            .first()
        )
        if existing:
            if not payload.resume:
                results.append(
                    {
                        "index": idx,
                        "case_id": case.case_id,
                        "result": None,
                        "error": "Batch item already persisted; use resume=true.",
                    }
                )
                continue
            if existing.request_hash != digest:
                results.append(
                    {
                        "index": idx,
                        "case_id": case.case_id,
                        "result": None,
                        "error": "Resume hash mismatch: item, provider, or rubric changed. Start a new batch_id.",
                    }
                )
                continue
            results.append(
                {
                    "index": idx,
                    "case_id": case.case_id,
                    "audit_id": existing.id,
                    "result": _result_from_record(existing),
                    "error": None,
                    "resumed": True,
                }
            )
            resumed += 1
            continue
        try:
            if provider:
                from backend.services.usage import reserve_provider_usage

                prompt_text = _usage_prompt_text(ereq)
                if getattr(provider, "api_key", None) or getattr(provider, "name", "") in (
                    "custom",
                    "ollama",
                ):
                    reserve_provider_usage(
                        db,
                        payload.provider or "custom",
                        payload.model or getattr(provider, "default_model", None),
                        prompt_text,
                    )
                res = await evaluate_hybrid(
                    ereq, provider, payload.model, weights=weights, thresholds=thresholds
                )
            else:
                res = evaluate_deterministic(ereq, weights=weights, thresholds=thresholds)
            res.evaluation_config = {
                "weights": weights,
                "thresholds": thresholds,
                "rubric_version": "1.1",
                "project_id": project.project_id,
            }
            rec = AuditRecord(
                case_id=res.case_id or case.case_id,
                project_id=project.project_id,
                batch_id=batch_id,
                batch_item_key=item_key,
                request_hash=digest,
                category=case.category,
                customer_message=case.customer_message,
                candidate_response=case.candidate_response,
                facts=case.facts,
                policy_ids=case.policy_ids,
                expected_actions=case.expected_actions,
                expected_escalation=case.expected_escalation,
                severity=case.severity,
                evaluation_mode=res.evaluation_mode,
                evaluator_model=res.evaluator_model,
                responder_model=case.responder_model,
                config_snapshot=res.evaluation_config,
                overall_score=res.overall_score,
                decision=res.decision,
                decision_reason=res.decision_reason,
                dimension_scores=[d.model_dump() for d in res.dimension_scores],
                escalation=res.escalation.model_dump() if res.escalation else None,
                policy_refs=[item.model_dump() for item in res.policy_refs],
                hard_stop_triggered=res.hard_stop_triggered,
                hard_stop_reasons=res.hard_stop_reasons,
                missing_info=res.missing_info,
                improvement_suggestions=res.improvement_suggestions,
                evidence_highlights=res.evidence_highlights,
                hallucination_flags=res.hallucination_flags,
                uncertainty_flags=res.uncertainty_flags,
                strengths=res.strengths,
                confidence=res.confidence,
                confidence_basis=res.confidence_basis,
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            results.append(
                {
                    "index": idx,
                    "case_id": case.case_id,
                    "audit_id": rec.id,
                    "result": res.model_dump(),
                    "error": None,
                    "resumed": False,
                }
            )
        except Exception as e:
            db.rollback()
            message = str(e) if isinstance(e, ValueError) else f"Item failed ({type(e).__name__})"
            results.append(
                {"index": idx, "case_id": case.case_id, "result": None, "error": message}
            )
    return {
        "batch_id": batch_id,
        "total": len(results),
        "resumed_count": resumed,
        "results": results,
    }


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, db: Session = Depends(get_db)):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", batch_id):
        raise HTTPException(422, "Invalid batch_id")
    records = (
        db.query(AuditRecord)
        .filter(AuditRecord.batch_id == batch_id)
        .order_by(AuditRecord.id)
        .all()
    )
    if not records:
        raise HTTPException(404, "Batch not found")
    return {
        "batch_id": batch_id,
        "persisted_items": len(records),
        "audits": [
            {
                "audit_id": r.id,
                "case_id": r.case_id,
                "batch_item_key": r.batch_item_key,
                "decision": r.decision,
                "overall_score": r.overall_score,
                "request_hash": r.request_hash,
            }
            for r in records
        ],
    }


@router.get("/audits")
def list_audits(
    limit: int = 50,
    offset: int = 0,
    decision: str | None = None,
    category: str | None = None,
    project_id: str | None = None,
    severity: str | None = None,
    hard_stop: bool | None = None,
    q_text: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(AuditRecord)
    if q_text:
        from sqlalchemy import or_

        term = f"%{q_text[:100]}%"
        q = q.filter(
            or_(
                AuditRecord.case_id.ilike(term),
                AuditRecord.category.ilike(term),
                AuditRecord.customer_message.ilike(term),
            )
        )
    q = q.order_by(AuditRecord.created_at.desc(), AuditRecord.id.desc())
    if decision:
        q = q.filter(AuditRecord.decision == decision)
    if category:
        q = q.filter(AuditRecord.category == category)
    if project_id:
        q = q.filter(AuditRecord.project_id == project_id)
    if severity:
        q = q.filter(AuditRecord.severity == severity)
    if hard_stop is not None:
        q = q.filter(AuditRecord.hard_stop_triggered == hard_stop)
    total = q.count()
    rows = q.offset(offset).limit(min(max(limit, 1), 1000)).all()

    def ser(r):
        return {
            "id": r.id,
            "case_id": r.case_id,
            "project_id": r.project_id,
            "category": r.category,
            "severity": r.severity,
            "overall_score": r.overall_score,
            "decision": r.decision,
            "evaluation_mode": r.evaluation_mode,
            "responder_model": r.responder_model,
            "evaluator_model": r.evaluator_model,
            "hard_stop_triggered": r.hard_stop_triggered,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "confidence": r.confidence,
            "confidence_basis": r.confidence_basis,
            "data_source": "synthetic_demo_seed"
            if r.batch_id == "synthetic_demo_seed_v1"
            else "submitted_case",
        }

    return {"total": total, "audits": [ser(r) for r in rows]}


@router.get("/audits/{audit_id}")
def get_audit(audit_id: int, db: Session = Depends(get_db)):
    r = db.query(AuditRecord).filter(AuditRecord.id == audit_id).first()
    if not r:
        raise HTTPException(404, "Audit not found")
    return {
        "id": r.id,
        "case_id": r.case_id,
        "project_id": r.project_id,
        "category": r.category,
        "severity": r.severity,
        "customer_message": r.customer_message,
        "candidate_response": r.candidate_response,
        "facts": r.facts,
        "policy_ids": r.policy_ids,
        "expected_actions": r.expected_actions,
        "expected_escalation": r.expected_escalation,
        "evaluation_mode": r.evaluation_mode,
        "evaluator_model": r.evaluator_model,
        "responder_model": r.responder_model,
        "config_snapshot": r.config_snapshot,
        "overall_score": r.overall_score,
        "decision": r.decision,
        "decision_reason": r.decision_reason,
        "dimension_scores": r.dimension_scores,
        "escalation": r.escalation,
        "policy_refs": r.policy_refs,
        "hard_stop_triggered": r.hard_stop_triggered,
        "hard_stop_reasons": r.hard_stop_reasons,
        "missing_info": r.missing_info,
        "improvement_suggestions": r.improvement_suggestions,
        "evidence_highlights": r.evidence_highlights,
        "hallucination_flags": r.hallucination_flags,
        "uncertainty_flags": r.uncertainty_flags,
        "strengths": r.strengths,
        "confidence": r.confidence,
        "confidence_basis": r.confidence_basis,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.delete("/audits/{audit_id}")
def delete_audit(audit_id: int, db: Session = Depends(get_db)):
    r = db.query(AuditRecord).filter(AuditRecord.id == audit_id).first()
    if not r:
        raise HTTPException(404, "Not found")
    from ..models import HumanReview

    db.query(HumanReview).filter(HumanReview.audit_id == audit_id).delete(synchronize_session=False)
    db.delete(r)
    db.commit()
    return {"deleted": audit_id}


@router.get("/analytics/summary")
def analytics_summary(project_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(AuditRecord)
    if project_id:
        q = q.filter(AuditRecord.project_id == project_id)
    rows = q.all()
    if not rows:
        return {
            "total": 0,
            "avg_score": 0,
            "pass_rate": 0,
            "critical_rate": 0,
            "hard_stop_rate": 0,
            "by_decision": {},
            "by_category": {},
            "by_severity": {},
            "by_escalation": {},
            "dimension_averages": {},
            "recent": [],
            "synthetic_demo_count": 0,
            "contains_synthetic_demo_data": False,
        }
    total = len(rows)
    synthetic_demo_count = sum(1 for row in rows if row.batch_id == "synthetic_demo_seed_v1")
    avg = sum(r.overall_score or 0 for r in rows) / total
    pass_rate = len([r for r in rows if r.decision == "Approve"]) / total
    critical = len([r for r in rows if r.decision == "Critical Failure"]) / total
    hard_stop_rate = len([r for r in rows if r.hard_stop_triggered]) / total
    by_dec = {}
    by_cat = {}
    by_esc = {}
    by_sev = {}
    dimension_totals: dict[str, list[int]] = {}
    for r in rows:
        by_dec[r.decision] = by_dec.get(r.decision, 0) + 1
        if r.category:
            by_cat[r.category] = by_cat.get(r.category, 0) + 1
        esc = (r.escalation or {}).get("verdict") if r.escalation else "unknown"
        by_esc[esc] = by_esc.get(esc, 0) + 1
        severity = r.severity or "unknown"
        by_sev[severity] = by_sev.get(severity, 0) + 1
        for dimension in r.dimension_scores or []:
            name = dimension.get("dimension")
            score = dimension.get("score")
            if name and isinstance(score, (int, float)):
                dimension_totals.setdefault(name, []).append(int(score))
    dimension_averages = {
        name: round(sum(values) / len(values), 2)
        for name, values in sorted(dimension_totals.items())
        if values
    }
    recent = [
        {
            "id": r.id,
            "case_id": r.case_id,
            "project_id": r.project_id,
            "decision": r.decision,
            "overall_score": r.overall_score,
            "severity": r.severity,
            "hard_stop_triggered": r.hard_stop_triggered,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "data_source": "synthetic_demo_seed"
            if r.batch_id == "synthetic_demo_seed_v1"
            else "submitted_case",
        }
        for r in sorted(
            rows, key=lambda x: x.created_at.timestamp() if x.created_at else 0, reverse=True
        )[:10]
    ]
    return {
        "total": total,
        "avg_score": round(avg, 1),
        "pass_rate": round(pass_rate, 3),
        "critical_rate": round(critical, 3),
        "hard_stop_rate": round(hard_stop_rate, 3),
        "by_decision": by_dec,
        "by_category": by_cat,
        "by_severity": by_sev,
        "by_escalation": by_esc,
        "dimension_averages": dimension_averages,
        "recent": recent,
        "synthetic_demo_count": synthetic_demo_count,
        "contains_synthetic_demo_data": synthetic_demo_count > 0,
    }
