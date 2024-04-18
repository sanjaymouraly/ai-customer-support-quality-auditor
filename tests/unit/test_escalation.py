from auditor.escalation.rules import evaluate_escalation


def test_fraud_escalation_needed():
    dec = evaluate_escalation(
        "Someone hacked my account, unknown orders!",
        "Please change your password",
        "privacy_fraud",
        {"fraud_suspected": True},
        None,
        "critical",
    )
    assert dec.expected == "escalate_security"
    assert dec.verdict == "under_escalation"


def test_correct_escalation():
    dec = evaluate_escalation(
        "Someone hacked my account",
        "Escalating immediately to security team, locking account",
        "privacy_fraud",
        {"fraud_suspected": True},
        "escalate_security",
        "critical",
    )
    assert dec.verdict == "appropriate"


def test_over_escalation():
    dec = evaluate_escalation(
        "Where is my tracking for ORD-123?",
        "I have escalated to supervisor, they will contact you in 24h",
        "order_status",
        {},
        None,
        "low",
    )
    assert dec.verdict == "over_escalation"
