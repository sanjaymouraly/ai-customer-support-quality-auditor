from __future__ import annotations

import re

from ..escalation.rules import evaluate_escalation
from ..policies.retrieval import retrieve_for_case
from .deterministic import (
    check_actionability,
    check_completeness,
    check_factual_accuracy,
    check_hallucination,
    check_policy_compliance,
    check_privacy,
    check_resolution,
    check_tone,
    detect_hard_stops,
)
from .rubric import decision_from_score, weighted_score
from .schemas import AuditResult, DimensionScore, PolicyReference

DIMENSIONS = [
    "factual_accuracy",
    "completeness",
    "policy_compliance",
    "hallucination",
    "resolution_guidance",
    "tone_clarity",
    "privacy_safety",
    "escalation",
    "actionability",
]

_INJECTION_PATTERNS = (
    r"ignore (?:all |the )?(?:previous|prior|above) instructions",
    r"disregard (?:the )?(?:system|policy|rubric|instructions)",
    r"you are now (?:an?|the) ",
    r"reveal (?:your )?(?:system )?prompt",
    r"print (?:your )?(?:system )?prompt",
    r"</?(?:system|customer_message|candidate_response|facts_json)>",
)


def detect_prompt_injection(text: str) -> bool:
    return any(re.search(pattern, text, re.I) for pattern in _INJECTION_PATTERNS)



def _deterministic_scores(req) -> dict[str, DimensionScore]:
    cm = req.customer_message
    cr = req.candidate_response
    facts = req.facts or {}
    policy_ids = req.policy_ids

    # Each check returns score+explanation
    priv_score, priv_exp, priv_ev = check_privacy(cr)
    fact_score, fact_exp, fact_issues, fact_strength = check_factual_accuracy(cr, facts, cm)
    comp_score, comp_exp, comp_missed = check_completeness(
        cr, cm, req.expected_actions, facts
    )
    pol_score, pol_exp, pol_viol, pol_sup = check_policy_compliance(
        cr, cm, facts, policy_ids, req.category
    )
    hall_score, hall_exp, hall_flags = check_hallucination(cr, facts)
    res_score, res_exp, res_miss = check_resolution(cr)
    tone_score, tone_exp, tone_flags = check_tone(cr)
    act_score, act_exp, act_miss = check_actionability(cr)

    esc_dec = evaluate_escalation(
        cm, cr, req.category, facts, req.expected_escalation, req.severity
    )
    esc_map = {"appropriate": 4, "over_escalation": 2, "under_escalation": 0}
    esc_score = esc_map.get(esc_dec.verdict, 2)
    esc_exp = (
        f"Expected {esc_dec.expected}, actual {esc_dec.actual}: {esc_dec.verdict}. {esc_dec.reason}"
    )

    raw = {
        "factual_accuracy": (fact_score, fact_exp, fact_issues + fact_strength),
        "completeness": (comp_score, comp_exp, comp_missed),
        "policy_compliance": (pol_score, pol_exp, pol_viol),
        "hallucination": (hall_score, hall_exp, hall_flags),
        "resolution_guidance": (res_score, res_exp, res_miss),
        "tone_clarity": (tone_score, tone_exp, tone_flags),
        "privacy_safety": (priv_score, priv_exp, priv_ev),
        "escalation": (esc_score, esc_exp, esc_dec.evidence),
        "actionability": (act_score, act_exp, act_miss),
    }
    out = {}
    for dim in DIMENSIONS:
        sc, exp, ev = raw[dim]
        heuristic_confidence = {
            "factual_accuracy": 0.75 if facts else 0.45,
            "completeness": 0.62,
            "policy_compliance": 0.76 if pol_score != 2 else 0.42,
            "hallucination": 0.72 if facts else 0.50,
            "resolution_guidance": 0.65,
            "tone_clarity": 0.50,
            "privacy_safety": 0.78,
            "escalation": 0.65,
            "actionability": 0.60,
        }
        out[dim] = DimensionScore(
            dimension=dim,
            score=sc,
            explanation=exp,
            evidence=ev[:3],
            confidence=heuristic_confidence.get(dim, 0.5),
        )
    return out, esc_dec, {"refund_violation": pol_score == 0 and "refund" in cr.lower()}


def evaluate_deterministic(req, weights=None, thresholds=None) -> AuditResult:
    scores, esc_dec, checks = _deterministic_scores(req)
    # Weight and threshold snapshots are explicit inputs; defaults remain versioned.
    plain = {k: v.score for k, v in scores.items()}
    overall = weighted_score(plain, weights)
    hard_reasons = detect_hard_stops(plain, checks)
    hard_stop = len(hard_reasons) > 0
    decision, reason = decision_from_score(
        overall,
        hard_stop,
        esc_dec.verdict,
        plain,
        plain.get("privacy_safety", 4),
        plain.get("policy_compliance", 4),
        thresholds,
    )
    if hard_stop:
        reason = "Hard stop: " + "; ".join(hard_reasons)
    # High/critical under-escalation must surface as an escalation decision rather than
    # being hidden by a strong weighted average or a lower decision band.
    if esc_dec.verdict == "under_escalation" and esc_dec.urgency in ("high", "critical"):
        decision = "Escalation Required"
        reason = (
            f"High-risk under-escalation (expected {esc_dec.expected}, response indicates "
            f"{esc_dec.actual}). A supervisor/security specialist must review before use."
        )

    # policy refs
    retrieved = retrieve_for_case(
        req.customer_message, req.candidate_response, req.policy_ids, top_k=4, category=req.category
    )
    refs = [
        PolicyReference(
            policy_id=r.policy_id,
            version=r.version,
            section=r.section_title,
            excerpt=r.excerpt,
            relevance=r.score,
        )
        for r in retrieved
    ]

    # missing / suggestions
    missing = []
    suggestions = []
    if plain["completeness"] < 3:
        missing.append("Some customer questions not addressed")
        suggestions.append("Answer every customer question explicitly; use bullet list.")
    if plain["resolution_guidance"] < 3:
        suggestions.append(
            "Add clear next steps with owner and timeline (e.g., 'We will... within 24h')."
        )
    if plain["hallucination"] < 4:
        suggestions.append("Remove unsupported promises; cite only verified facts/policies.")
    if plain["escalation"] < 4:
        suggestions.append(
            f"Correct escalation: expected {esc_dec.expected}, actual {esc_dec.actual}. Follow escalation playbook."
        )
    if plain["privacy_safety"] < 4:
        suggestions.append("Use secure verification flow; never request full card/CVV/password.")
    if plain["policy_compliance"] < 3:
        suggestions.append("Align with policy: reference correct window and required evidence.")

    uncertainty_flags = []
    if not req.facts:
        uncertainty_flags.append(
            "No verified case facts supplied; factual checks are necessarily limited."
        )
    injection_sources = []
    if detect_prompt_injection(req.customer_message):
        injection_sources.append("customer message")
    if detect_prompt_injection(req.candidate_response):
        injection_sources.append("candidate response")
    if injection_sources:
        uncertainty_flags.append(
            "Prompt-injection-like text detected in the "
            + " and ".join(injection_sources)
            + ". Instructions inside submitted text were treated as data; review the response behavior manually."
        )
    if not retrieved or plain["policy_compliance"] == 2:
        uncertainty_flags.append(
            "No sufficiently relevant policy evidence was retrieved; absence of evidence is not proof of a violation."
        )
    versions_by_id = {}
    for ref in retrieved:
        versions_by_id.setdefault(ref.policy_id, set()).add(ref.version)
    conflicts = [policy_id for policy_id, versions in versions_by_id.items() if len(versions) > 1]
    if conflicts:
        uncertainty_flags.append(
            "Multiple active versions of policy were retrieved for: "
            + ", ".join(sorted(conflicts))
            + ". Human review is required until policy activation is resolved."
        )
        if decision == "Approve":
            decision = "Human Review Required"
            reason = "Conflicting active policy versions require human review."
    if esc_dec.expected in ("ask_info", "verify_identity") and not esc_dec.correct:
        uncertainty_flags.append(
            "Customer intent or authorization is insufficiently established; human review may be appropriate."
        )
    if not req.expected_actions:
        uncertainty_flags.append(
            "No expected-action checklist supplied; completeness relies on deterministic heuristics."
        )
    declared_language = str((req.facts or {}).get("language", "en")).strip().lower().split("-")[0]
    text_probe = (req.customer_message + " " + req.candidate_response).lower()
    spanish_marker = re.search(
        r"(?:¡|¿|\b(?:hola|gracias|pedido|orden|seguimiento|entrega|inglés|español|entiendo|puedo|favor)\b)",
        text_probe,
    )
    likely_non_english = declared_language not in ("", "en", "unknown") or bool(spanish_marker)
    if likely_non_english:
        uncertainty_flags.append(
            "Non-English content detected; this rule engine has limited language coverage. Bilingual human review is recommended."
        )
        if decision == "Approve":
            decision = "Human Review Required"
            reason = "Potential language mismatch or limited rule coverage requires a bilingual reviewer before approval."

    # Surface dimension-level evidence, prioritizing issues; do not echo sensitive numbers unnecessarily.
    highlights = []
    for dim_result in scores.values():
        if dim_result.score < 4:
            highlights.extend(dim_result.evidence[:2])
    if not highlights and req.candidate_response:
        highlights.append(
            "Candidate response was reviewed against supplied facts and retrieved policies; no specific issue passage was identified."
        )
    highlights = highlights[:12]

    hall_flags = [f for f in scores["hallucination"].evidence]
    strengths = []
    for dim, sc in scores.items():
        if sc.score == 4:
            strengths.append(f"{dim}: {sc.explanation}")

    confidence = max(
        0.15,
        min(
            0.90,
            round(
                sum(d.confidence for d in scores.values()) / len(scores)
                - 0.03 * len(uncertainty_flags),
                2,
            ),
        ),
    )
    return AuditResult(
        case_id=req.case_id,
        overall_score=overall,
        dimension_scores=list(scores.values()),
        decision=decision,
        decision_reason=reason,
        escalation=esc_dec,
        policy_refs=refs,
        hard_stop_triggered=hard_stop,
        hard_stop_reasons=hard_reasons,
        missing_info=missing,
        improvement_suggestions=suggestions,
        evidence_highlights=highlights,
        hallucination_flags=hall_flags,
        uncertainty_flags=uncertainty_flags,
        strengths=strengths[:3],
        confidence=confidence,
        confidence_basis="Uncalibrated heuristic based on fact/policy evidence availability, rubric coverage, and uncertainty flags; not a probability."
        + (
            " Non-English inputs are subject to limited rule coverage."
            if likely_non_english
            else ""
        ),
        evaluation_mode="deterministic",
        evaluator_model="rule-engine-v1",
        evaluation_config={"weights": weights, "thresholds": thresholds}
        if weights is not None or thresholds is not None
        else None,
    )


async def evaluate_hybrid(req, provider=None, model=None, weights=None, thresholds=None):
    # Deterministic baseline + bounded LLM refinement; deterministic safety/policy hard stops never overridden.
    base = evaluate_deterministic(req, weights=weights, thresholds=thresholds)
    if provider is None or req.evaluation_mode in ("deterministic", "offline"):
        return base
    try:
        from .llm_judge import llm_evaluate

        llm_data = await llm_evaluate(
            req.customer_message,
            req.candidate_response,
            req.facts,
            req.expected_actions,
            req.expected_escalation,
            req.category,
            req.severity,
            req.policy_ids,
            provider,
            model,
            req.temperature,
        )
        # Merge: keep hard-stop dimensions from deterministic if they are 0, otherwise average with llm where available
        llm_scores = {d["dimension"]: d for d in llm_data.get("dimension_scores", [])}
        merged = []
        llm_only_dimensions = {
            "completeness",
            "tone_clarity",
            "resolution_guidance",
            "actionability",
        }
        use_llm_only = req.evaluation_mode == "llm"
        known_text = [req.customer_message, req.candidate_response]
        known_text.extend(ref.excerpt for ref in base.policy_refs)
        normalized_known = [" ".join(item.lower().split()) for item in known_text if item]
        unverified_evidence = False
        for ds in base.dimension_scores:
            if ds.dimension in llm_scores:
                model_dim = llm_scores[ds.dimension]
                llm_sc = int(model_dim.get("score", ds.score))
                # A deterministic zero is immutable. LLM mode uses the judge only for
                # subjective dimensions; hybrid averages those dimensions, while safety/
                # factual dimensions may only be made more conservative by the LLM.
                if ds.score == 0:
                    final = 0
                elif ds.dimension in llm_only_dimensions:
                    final = llm_sc if use_llm_only else int(round((ds.score + llm_sc) / 2))
                elif use_llm_only:
                    final = ds.score
                else:
                    final = min(ds.score, llm_sc)
                model_evidence = model_dim.get("evidence") or []
                verified = []
                for item in model_evidence:
                    normalized = " ".join(str(item).lower().split())
                    if normalized and any(normalized in source for source in normalized_known):
                        verified.append(str(item))
                    elif str(item).strip():
                        unverified_evidence = True
                from ..security.validators import redact_pii

                if verified:
                    explanation = redact_pii(
                        f"LLM judgment (model-generated; evidence matched supplied text): {model_dim.get('explanation', ds.explanation)}"
                    )
                    evidence = [redact_pii(item) for item in verified[:3]]
                    conf = 0.72
                else:
                    explanation = redact_pii(
                        f"LLM hypothesis requiring human verification: {model_dim.get('explanation', ds.explanation)}"
                    )
                    evidence = ds.evidence
                    conf = 0.45
                    unverified_evidence = True
                merged.append(
                    DimensionScore(
                        dimension=ds.dimension,
                        score=final,
                        explanation=explanation,
                        evidence=evidence,
                        confidence=conf,
                    )
                )
            else:
                merged.append(ds)
        # recompute overall
        plain = {m.dimension: m.score for m in merged}
        overall = weighted_score(plain, weights)
        # keep hard_stop from base
        decision, reason = decision_from_score(
            overall,
            base.hard_stop_triggered,
            base.escalation.verdict if base.escalation else None,
            plain,
            plain.get("privacy_safety", 4),
            plain.get("policy_compliance", 4),
            thresholds,
        )
        if base.decision in ("Critical Failure", "Escalation Required"):
            decision = base.decision
            reason = base.decision_reason
        uncertainty = list(base.uncertainty_flags)
        if unverified_evidence:
            uncertainty.append(
                "One or more judge citations could not be verified as an exact excerpt from supplied customer, response, or policy text; treat model reasoning as a hypothesis."
            )
        # Model-generated flags are explicitly labeled; no unsupported judge assertion is presented as verified fact.
        llm_flags = []
        for flag in llm_data.get("hallucination_flags", []):
            normalized = " ".join(str(flag).lower().split())
            if normalized and any(normalized in source for source in normalized_known):
                from ..security.validators import redact_pii

                llm_flags.append(redact_pii(str(flag)))
            else:
                from ..security.validators import redact_pii

                llm_flags.append(redact_pii(f"LLM hypothesis requiring human verification: {flag}"))
        mode_label = "hybrid" if req.evaluation_mode == "hybrid" else "LLM-assisted"
        return AuditResult(
            case_id=base.case_id,
            overall_score=overall,
            dimension_scores=merged,
            decision=decision,
            decision_reason=reason
            + f" ({mode_label}: deterministic safety checks + bounded LLM judgment)",
            escalation=base.escalation,
            policy_refs=base.policy_refs,
            hard_stop_triggered=base.hard_stop_triggered,
            hard_stop_reasons=base.hard_stop_reasons,
            missing_info=[
                redact_pii(str(x)) for x in llm_data.get("missing_info", base.missing_info)
            ],
            improvement_suggestions=[
                redact_pii(str(x))
                for x in llm_data.get("improvement_suggestions", base.improvement_suggestions)
            ],
            evidence_highlights=base.evidence_highlights,
            hallucination_flags=llm_flags or base.hallucination_flags,
            uncertainty_flags=uncertainty,
            strengths=base.strengths,
            confidence=min(base.confidence, float(llm_data.get("confidence", 0.5))),
            confidence_basis="Minimum of deterministic evidence-coverage estimate and LLM self-reported confidence; neither is calibrated probability.",
            evaluation_mode=req.evaluation_mode
            if req.evaluation_mode in ("llm", "hybrid")
            else "hybrid",
            evaluator_model=model or getattr(provider, "default_model", None) or "llm",
            evaluation_config={"weights": weights, "thresholds": thresholds}
            if weights is not None or thresholds is not None
            else None,
        )
    except Exception as e:
        # fallback to deterministic
        base.evaluation_mode = f"{req.evaluation_mode}-fallback"
        base.confidence = min(base.confidence, 0.5)
        base.confidence_basis = (
            "Deterministic fallback after provider failure; heuristic and not calibrated."
        )
        # Do not expose raw provider exceptions (which can contain sensitive request metadata).
        base.improvement_suggestions.append(
            f"LLM judge unavailable ({type(e).__name__}); deterministic fallback used."
        )
        return base


def evaluate(req, provider=None, model=None):
    # Sync wrapper for deterministic
    return evaluate_deterministic(req)
