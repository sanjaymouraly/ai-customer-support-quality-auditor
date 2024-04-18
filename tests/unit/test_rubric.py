from auditor.evaluation.rubric import weighted_score


def test_weighted_score():
    scores = {
        k: 4
        for k in [
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
    }
    assert weighted_score(scores) == 100
    scores = {k: 0 for k in scores}
    assert weighted_score(scores) == 0


def test_partial():
    s = {
        "factual_accuracy": 2,
        "completeness": 2,
        "policy_compliance": 2,
        "hallucination": 2,
        "resolution_guidance": 2,
        "tone_clarity": 2,
        "privacy_safety": 2,
        "escalation": 2,
        "actionability": 2,
    }
    assert 45 < weighted_score(s) < 55
