from __future__ import annotations

from ..evaluation.schemas import EscalationDecision

# Expected escalation mapping based on categories / triggers
ESCALATION_TRIGGERS = {
    "escalate_security": {
        "keywords": [
            "hacked",
            "account takeover",
            "unauthorized access",
            "fraud",
            "stolen",
            "someone else using my account",
            "identity theft",
            "phishing",
            "security breach",
        ],
        "destination": "Security / Fraud Team",
        "urgency": "critical",
    },
    "escalate_billing": {
        "keywords": [
            "duplicate charge",
            "double charged",
            "billing dispute",
            "incorrect invoice",
            "overcharged",
            "payment failure",
            "chargeback",
        ],
        "destination": "Billing Specialist",
        "urgency": "high",
    },
    "escalate_supervisor": {
        "keywords": [
            "supervisor",
            "manager",
            "escalate",
            "legal",
            "lawyer",
            "attorney",
            "lawsuit",
            "ombudsman",
            "regulatory",
        ],
        "destination": "Supervisor / Customer Relations",
        "urgency": "high",
    },
    "verify_identity": {
        "keywords": [
            "verify identity",
            "identity verification",
            "account access",
            "locked out",
            "reset password",
            "two-factor",
            "otp",
        ],
        "destination": "Identity Verification Flow",
        "urgency": "medium",
    },
}


def detect_expected_escalation(
    customer_message: str, category: str, facts: dict, severity: str
) -> tuple[str, str, str]:
    """
    Returns (expected_escalation, urgency, reason)
    """
    msg = customer_message.lower()
    # category hints
    cat_map = {
        "account_access": "verify_identity",
        "insufficient_info": "ask_info",
        "privacy_fraud": "escalate_security",
        "billing_dispute": "escalate_billing",
        "duplicate_charge": "escalate_billing",
        "policy_exception": "escalate_supervisor",
        "escalation_request": "escalate_supervisor",
        "angry_customer": "escalate_supervisor" if severity == "critical" else "resolve",
        "adversarial": "escalate_security" if "fraud" in msg or "hack" in msg else "resolve",
    }
    if category in cat_map:
        candidate = cat_map[category]
        if candidate == "ask_info":
            return "ask_info", "low", "Customer request lacks essential information"
        # check triggers override
        for esc_type, cfg in ESCALATION_TRIGGERS.items():
            if any(kw in msg for kw in cfg["keywords"]):
                return (
                    esc_type,
                    cfg["urgency"],
                    f"Customer message contains escalation trigger for {esc_type}",
                )
        return (
            candidate,
            "medium"
            if candidate == "verify_identity"
            else "high"
            if "escalate" in candidate
            else "low",
            f"Category {category} suggests {candidate}",
        )
    # keyword scan
    for esc_type, cfg in ESCALATION_TRIGGERS.items():
        if any(kw in msg for kw in cfg["keywords"]):
            return esc_type, cfg["urgency"], f"Trigger keyword for {esc_type}"
    # check for high-risk facts
    if facts.get("fraud_suspected") or facts.get("account_takeover"):
        return "escalate_security", "critical", "Facts indicate fraud/account takeover"
    if facts.get("legal_threat"):
        return "escalate_supervisor", "high", "Legal threat detected"
    return "resolve", "low", "No escalation trigger; direct resolution expected"


def detect_actual_escalation(response: str) -> str:
    r = response.lower()
    explicit_action = any(
        word in r
        for word in [
            "escalat",
            "refer",
            "transfer",
            "forward",
            "flagged",
            "submitted",
            "send this to",
            "send it to",
            "connect you",
            "opened a case",
            "notify",
            "ask our",
        ]
    )
    # Merely mentioning a supervisor/team or proposing an optional transfer is not a completed escalation.
    optional = any(
        p in r
        for p in [
            "if you'd like",
            "if you would like",
            "would you like me to",
            "i can escalate",
            "can escalate if",
            "or escalate to",
        ]
    ) and not any(
        p in r
        for p in [
            "i've escalated",
            "i have escalated",
            "i'm escalating",
            "i am escalating",
            "i'll escalate",
            "i will escalate",
            "escalated to",
        ]
    )
    if optional:
        return "ask_info"
    if explicit_action:
        if any(term in r for term in ["security", "fraud", "hacked", "account takeover"]):
            return "escalate_security"
        if any(term in r for term in ["billing specialist", "billing team", "billing department"]):
            return "escalate_billing"
        if any(term in r for term in ["supervisor", "manager", "customer relations"]):
            return "escalate_supervisor"
    if any(
        p in r
        for p in [
            "verify your identity",
            "please verify",
            "otp",
            "government id",
            "identity verification",
            "secure recovery portal",
        ]
    ):
        return "verify_identity"
    if any(
        p in r
        for p in [
            "could you provide",
            "please share",
            "additional information",
            "more details",
            "what is your order id",
        ]
    ):
        return "ask_info"
    return "resolve"


def evaluate_escalation(
    customer_message: str,
    candidate_response: str,
    category: str | None,
    facts: dict,
    expected_escalation: str | None = None,
    severity: str = "medium",
) -> EscalationDecision:
    if expected_escalation:
        expected = expected_escalation
        exp_urg = (
            "high"
            if "escalate" in expected
            else "medium"
            if expected in ("verify_identity", "ask_info")
            else "low"
        )
        reason = f"Expected escalation provided as ground truth: {expected}"
    else:
        expected, exp_urg, reason = detect_expected_escalation(
            customer_message, category or "", facts, severity
        )

    actual = detect_actual_escalation(candidate_response)

    # verdict logic
    escalation_levels = {
        "resolve": 0,
        "ask_info": 1,
        "verify_identity": 2,
        "refer": 2,
        "escalate_billing": 3,
        "escalate_supervisor": 3,
        "escalate_security": 4,
    }
    exp_l = escalation_levels.get(expected, 0)
    act_l = escalation_levels.get(actual, 0)

    if expected == actual:
        verdict = "appropriate"
        correct = True
    elif act_l < exp_l:
        verdict = "under_escalation"
        correct = False
    elif act_l > exp_l + 1:
        verdict = "over_escalation"
        correct = False
    elif act_l > exp_l:
        verdict = "over_escalation"
        correct = False
    else:
        verdict = "appropriate"
        correct = True

    # Clarifying questions and evidence requests are not the same as an unnecessary specialist handoff.
    response_low = candidate_response.lower()
    is_consent_to_escalate = "supervisor" in response_low and any(
        term in response_low
        for term in [
            "would you like",
            "if you'd like",
            "if you would like",
            "submit that exception",
        ]
    )
    if expected == "resolve" and actual == "ask_info":
        verdict = "appropriate"
        correct = True
    if expected == "escalate_supervisor" and actual == "ask_info" and is_consent_to_escalate:
        verdict = "appropriate"
        correct = True

    dest = ESCALATION_TRIGGERS.get(expected, {}).get("destination") if not correct else None
    if actual in ESCALATION_TRIGGERS:
        dest = ESCALATION_TRIGGERS[actual].get("destination")

    evidence = []
    # Include a response passage as traceable evidence; keep excerpts short.
    passage = response_low
    keywords = {
        "escalate_security": ["security", "fraud", "hacked", "account"],
        "escalate_billing": ["billing", "duplicate charge", "invoice"],
        "escalate_supervisor": ["supervisor", "manager", "legal"],
        "verify_identity": ["verify", "otp", "identity"],
        "ask_info": ["please share", "could you", "would you like", "please provide"],
    }.get(actual, [])
    for kw in keywords:
        pos = response_low.find(kw)
        if pos >= 0:
            passage = candidate_response[
                max(0, pos - 55) : min(len(candidate_response), pos + 120)
            ].strip()
            break
    if verdict == "under_escalation":
        evidence.append(
            f"Expected {expected} but response attempted {actual}; response passage: {passage}"
        )
    elif verdict == "over_escalation":
        evidence.append(
            f"Expected {expected} but response escalated to {actual}; response passage: {passage}"
        )
    else:
        evidence.append(f"Escalation appropriate: {actual}; response passage: {passage}")

    return EscalationDecision(
        expected=expected,
        actual=actual,
        correct=correct,
        verdict=verdict,
        urgency=exp_urg,
        destination=dest,
        reason=reason,
        evidence=evidence,
    )
