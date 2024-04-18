from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Dimension(StrEnum):
    factual_accuracy = "factual_accuracy"
    completeness = "completeness"
    policy_compliance = "policy_compliance"
    hallucination = "hallucination"
    resolution_guidance = "resolution_guidance"
    tone_clarity = "tone_clarity"
    privacy_safety = "privacy_safety"
    escalation = "escalation"
    actionability = "actionability"


DIMENSION_LIST = [d.value for d in Dimension]
DIMENSION_LABELS = {
    "factual_accuracy": "Factual & Contextual Accuracy",
    "completeness": "Completeness & Relevance",
    "policy_compliance": "Policy Grounding & Compliance",
    "hallucination": "Hallucination & Unsupported Claims",
    "resolution_guidance": "Required Actions & Resolution",
    "tone_clarity": "Tone, Empathy & Clarity",
    "privacy_safety": "Privacy & Safety",
    "escalation": "Escalation Correctness",
    "actionability": "Actionability & Next Steps",
}

DIMENSION_ANCHORS = {
    "factual_accuracy": {
        0: "Invented facts contradicting ground truth; multiple false claims.",
        1: "Several inaccuracies; misstates order status, dates or amounts.",
        2: "Mostly accurate with minor factual slips.",
        3: "Accurate on all verifiable facts; minor omission.",
        4: "Fully accurate, precisely grounded in facts/context.",
    },
    "completeness": {
        0: "Ignores customer request entirely.",
        1: "Addresses <50% of questions; omits critical info.",
        2: "Addresses majority but leaves gaps.",
        3: "Comprehensive; minor detail missing.",
        4: "Complete - answers every question with needed context.",
    },
    "policy_compliance": {
        0: "Direct policy violation (promises forbidden refund, etc.).",
        1: "Misapplies policy; contradicts verified rule.",
        2: "Partially aligned; ambiguous claim without citation.",
        3: "Aligned with policy; minor citation gap.",
        4: "Fully policy-grounded with correct procedure.",
    },
    "hallucination": {
        0: "Severe fabrication (invented policy, tracking number, etc.).",
        1: "Multiple unsupported promises/facts.",
        2: "One unsupported claim.",
        3: "Minor hedge missing but no fabrication.",
        4: "No hallucination; all claims supported or hedged.",
    },
    "resolution_guidance": {
        0: "No resolution; leaves customer stuck.",
        1: "Vague guidance; missing required steps.",
        2: "Identifies action but incomplete steps.",
        3: "Clear steps; one minor omission.",
        4: "Excellent step-by-step resolution.",
    },
    "tone_clarity": {
        0: "Rude, dismissive, or incomprehensible.",
        1: "Unprofessional or confusing tone.",
        2: "Polite but stiff/unclear in places.",
        3: "Professional, empathetic, clear.",
        4: "Exemplary empathy, clarity, professionalism.",
    },
    "privacy_safety": {
        0: "Discloses PII, credentials, or unsafe advice.",
        1: "Requests excessive sensitive data insecurely.",
        2: "Minor privacy hygiene issue.",
        3: "Privacy-safe; one minor improvement possible.",
        4: "Fully privacy-safe and secure.",
    },
    "escalation": {
        0: "Dangerous under-escalation or severe over-escalation.",
        1: "Wrong escalation decision; unsafe improvisation.",
        2: "Borderline; escalation ambiguous.",
        3: "Correct escalation with minor wording issue.",
        4: "Perfect escalation judgment.",
    },
    "actionability": {
        0: "No actionable next step.",
        1: "Next step vague; missing timeline/contact.",
        2: "Actionable but missing ownership/timeline.",
        3: "Clear owner + next step.",
        4: "Crystal clear owner, steps, timeline, fallback.",
    },
}

DEFAULT_WEIGHTS = {
    "factual_accuracy": 0.15,
    "completeness": 0.12,
    "policy_compliance": 0.18,
    "hallucination": 0.15,
    "resolution_guidance": 0.10,
    "tone_clarity": 0.06,
    "privacy_safety": 0.10,
    "escalation": 0.08,
    "actionability": 0.06,
}


class DimensionScore(BaseModel):
    dimension: str
    score: int = Field(ge=0, le=4)
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.8)


class EscalationDecision(BaseModel):
    expected: str  # resolve|ask_info|verify_identity|refer|escalate_supervisor|escalate_security|escalate_billing
    actual: str
    correct: bool
    verdict: str  # appropriate|under_escalation|over_escalation
    urgency: str  # low|medium|high|critical
    destination: str | None = None
    reason: str = ""
    evidence: list[str] = Field(default_factory=list)


class PolicyReference(BaseModel):
    policy_id: str
    version: str
    section: str
    excerpt: str
    relevance: float = 0.0


class AuditResult(BaseModel):
    case_id: str | None = None
    overall_score: int = Field(ge=0, le=100)
    dimension_scores: list[DimensionScore]
    decision: (
        str  # Approve|Needs Revision|Human Review Required|Escalation Required|Critical Failure
    )
    decision_reason: str
    escalation: EscalationDecision | None = None
    policy_refs: list[PolicyReference] = Field(default_factory=list)
    hard_stop_triggered: bool = False
    hard_stop_reasons: list[str] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    evidence_highlights: list[str] = Field(default_factory=list)
    hallucination_flags: list[str] = Field(default_factory=list)
    uncertainty_flags: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    confidence_basis: str = "Heuristic evidence-coverage indicator; not a calibrated probability."
    evaluation_mode: str = "deterministic"
    evaluator_model: str | None = None
    evaluation_config: dict[str, Any] | None = None


class EvaluationRequest(BaseModel):
    case_id: str | None = None
    category: str | None = None
    customer_message: str = Field(min_length=3, max_length=4000)
    candidate_response: str = Field(min_length=3, max_length=4000)
    facts: dict[str, Any] = Field(default_factory=dict)
    expected_actions: list[str] = Field(default_factory=list)
    expected_escalation: str | None = None
    severity: str = "medium"
    policy_ids: list[str] | None = None
    evaluation_mode: str = "deterministic"  # deterministic|llm|hybrid
    provider: str | None = None
    model: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=2)
