from .schemas import DEFAULT_WEIGHTS, DIMENSION_ANCHORS, DIMENSION_LABELS

WEIGHTS = DEFAULT_WEIGHTS
LABELS = DIMENSION_LABELS
ANCHORS = DIMENSION_ANCHORS


def weighted_score(scores: dict[str, int], weights: dict[str, float] | None = None) -> int:
    w = weights or WEIGHTS
    total_w = sum(w.values())
    if total_w <= 0:
        raise ValueError("Rubric weights must contain at least one positive value")
    norm = {k: v / total_w for k, v in w.items()}
    s = sum(scores.get(k, 0) * norm.get(k, 0) for k in norm)
    # 0-4 -> 0-100
    return int(round((s / 4) * 100))


def decision_from_score(
    overall: int,
    hard_stop: bool,
    escalation_verdict: str | None,
    min_scores: dict[str, int],
    privacy_score: int,
    policy_score: int,
    thresholds: dict[str, int] | None = None,
) -> tuple[str, str]:
    thresholds = thresholds or THRESHOLDS
    if hard_stop or privacy_score == 0 or policy_score == 0:
        return "Critical Failure", "Hard-stop triggered or critical dimension scored 0."
    if escalation_verdict == "under_escalation" and overall < 85:
        return "Escalation Required", "Under-escalation detected and score below threshold."
    if overall >= thresholds["approve"]:
        return "Approve", "High quality across dimensions; no critical issues."
    if overall >= thresholds["revision"]:
        return "Needs Revision", "Some dimensions below target; revise before sending."
    if overall >= thresholds["human_review"]:
        return "Human Review Required", "Material issues requiring human judgment."
    return "Critical Failure", "Multiple critical failures; do not send."


THRESHOLDS = {
    "approve": 85,
    "revision": 65,
    "human_review": 40,
}
