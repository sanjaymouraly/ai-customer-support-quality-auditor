from __future__ import annotations

import re
from datetime import date

from .models import RetrievedPolicy
from .store import get_all_policies

CATEGORY_POLICY_IDS = {
    "order_status": ["shipping_policy"],
    "delayed_delivery": ["shipping_policy"],
    "damaged_product": ["refund_policy", "warranty_policy"],
    "refund_request": ["refund_policy"],
    "cancellation_return": ["cancellation_policy", "refund_policy"],
    "billing_dispute": ["billing_policy", "escalation_policy"],
    "duplicate_charge": ["refund_policy", "billing_policy"],
    "subscription": ["billing_policy"],
    "warranty_claim": ["warranty_policy"],
    "account_access": ["privacy_policy"],
    "policy_exception": ["refund_policy", "escalation_policy"],
    "angry_customer": ["escalation_policy", "shipping_policy"],
    "escalation_request": ["escalation_policy"],
    "privacy_fraud": ["privacy_policy", "escalation_policy"],
    "insufficient_info": ["privacy_policy", "refund_policy", "shipping_policy", "billing_policy"],
    "multi_question": ["shipping_policy", "billing_policy", "refund_policy"],
    "multilingual_ambiguous": ["shipping_policy", "privacy_policy"],
    "adversarial": ["refund_policy", "privacy_policy", "warranty_policy"],
}


def _tokenize(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", s.lower()))


def _score(query: str, section_text: str, keywords: list[str]) -> float:
    qt = _tokenize(query)
    st = _tokenize(section_text)
    if not qt:
        return 0.0
    overlap = len(qt & st) / len(qt)
    kw_bonus = 0.0
    ql = query.lower()
    for kw in keywords:
        if kw.lower() in ql:
            kw_bonus += 0.1
    # phrase bonus: exact phrase in excerpt
    return overlap + min(kw_bonus, 0.3)


def retrieve(
    query: str, policy_ids: list[str] | None = None, top_k: int = 5
) -> list[RetrievedPolicy]:
    # Deprecated versions remain available to Policy Manager comparisons but are not used for live decisions.
    today = date.today()
    policies = []
    for policy in get_all_policies():
        if policy.status != "active":
            continue
        try:
            start = date.fromisoformat(policy.effective_date)
            if start > today:
                continue
            if policy.expires_on and date.fromisoformat(policy.expires_on) < today:
                continue
        except ValueError:
            # Invalid dates are not safely applicable; omit and let the auditor signal uncertainty.
            continue
        policies.append(policy)
    if policy_ids:
        policies = [p for p in policies if p.policy_id in policy_ids]
    results: list[RetrievedPolicy] = []
    for p in policies:
        for s in p.sections:
            txt = f"{s.title} {s.content}"
            sc = _score(query, txt, s.keywords)
            if sc > 0:
                results.append(
                    RetrievedPolicy(
                        policy_id=p.policy_id,
                        version=p.version,
                        section_id=s.section_id,
                        section_title=s.title,
                        excerpt=s.content[:600],
                        score=sc,
                    )
                )
    results.sort(key=lambda x: -x.score)
    return results[:top_k]


CATEGORY_RETRIEVAL_TERMS = {
    "multilingual_ambiguous": "shipping delivery tracking estimated arrival",
    "privacy_fraud": "privacy credentials account security identity verification",
    "insufficient_info": "refund shipping billing account verification",
}


def retrieve_for_case(
    customer_message: str,
    candidate_response: str,
    policy_ids=None,
    top_k=5,
    category: str | None = None,
):
    # Category terms help retrieve explicitly relevant English policies for non-English messages;
    # the returned excerpt is still a real section from the selected active policy document.
    category_terms = CATEGORY_RETRIEVAL_TERMS.get(category or "", "")
    q = f"{customer_message} {candidate_response} {category_terms}"
    selected = policy_ids or CATEGORY_POLICY_IDS.get(category or "")
    return retrieve(q, selected, top_k)
