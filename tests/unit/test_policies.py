from auditor.policies.retrieval import retrieve
from auditor.policies.store import load_policies_from_dir


def test_retrieval():
    load_policies_from_dir()
    res = retrieve("refund window 30 days eligibility", top_k=3)
    assert len(res) > 0
    assert any("refund" in r.policy_id for r in res)


def test_retrieval_policy_filter():
    load_policies_from_dir()
    res = retrieve("tracking number", policy_ids=["shipping_policy"])
    assert all(r.policy_id == "shipping_policy" for r in res)
