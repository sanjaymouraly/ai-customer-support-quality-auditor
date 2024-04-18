"""Human review workspace."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..ui import (
    DECISIONS,
    DIMENSION_LABELS,
    api_get,
    api_post,
    decision_badge,
    empty_state,
    hero,
    section,
    show_error,
)

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


def _review_form(audit: dict) -> None:
    audit_id = audit["id"]
    hard_stop = bool(audit.get("hard_stop_triggered"))
    st.caption(
        f"Machine result: {audit.get('evaluation_mode')} / "
        f"{audit.get('evaluator_model') or 'rule engine'} · confidence "
        f"{float(audit.get('confidence') or 0):.2f} (uncalibrated)."
    )
    if hard_stop:
        st.error(
            "This audit triggered a hard stop. It cannot be approved through the review API; "
            "record a non-approval disposition and investigate."
        )
    left, right = st.columns(2)
    left.markdown("**Customer message**")
    left.info(audit.get("customer_message") or "")
    right.markdown("**Candidate response**")
    right.info(audit.get("candidate_response") or "")

    dimensions = {item.get("dimension"): item for item in audit.get("dimension_scores") or []}
    with st.form(f"human_review_{audit_id}"):
        reviewer = st.text_input(
            "Reviewer ID / pseudonym",
            value="reviewer_01",
            key=f"reviewer_{audit_id}",
            help="Use a stable pseudonym; never enter secrets or customer identifiers.",
        )
        st.markdown("**Human dimension scores (0–4)**")
        revised = []
        columns = st.columns(3)
        for index, name in enumerate(DIMENSIONS):
            current = dimensions.get(name) or {}
            score = columns[index % 3].select_slider(
                DIMENSION_LABELS.get(name, name),
                options=[0, 1, 2, 3, 4],
                value=int(current.get("score", 2)),
                key=f"review_dim_{audit_id}_{name}",
            )
            revised.append({"dimension": name, "score": score, "reviewer_explanation": ""})
        decisions = [item for item in DECISIONS if not (hard_stop and item == "Approve")]
        machine_decision = audit.get("decision")
        decision = st.selectbox(
            "Human disposition",
            decisions,
            index=decisions.index(machine_decision) if machine_decision in decisions else 1,
            key=f"review_decision_{audit_id}",
        )
        overall = st.number_input(
            "Human overall score",
            min_value=0,
            max_value=100,
            value=int(audit.get("overall_score") or 0),
            key=f"review_score_{audit_id}",
        )
        comments = st.text_area(
            "Reviewer notes / evidence",
            key=f"review_comments_{audit_id}",
            placeholder="Why do you agree or disagree? Cite policy and evidence.",
        )
        submit = st.form_submit_button("Save human review", type="primary")

    if submit:
        if not reviewer.strip():
            st.error("Reviewer ID is required.")
        else:
            payload = {
                "audit_id": audit_id,
                "reviewer_id": reviewer.strip(),
                "dimension_scores": revised,
                "overall_score": int(overall),
                "decision": decision,
                "comments": comments or None,
            }
            response = api_post("/api/reviews", payload)
            if response is not None and response.ok:
                st.success(f"Human review saved as record {response.json()['review_id']}.")
                st.rerun()
            elif response is not None:
                show_error(response, "Review could not be saved")

    reviews = api_get("/api/reviews", params={"audit_id": audit_id}) or {}
    if reviews.get("reviews"):
        section("Prior human reviews")
        st.dataframe(
            pd.DataFrame(reviews["reviews"]), width="stretch", hide_index=True
        )
    else:
        st.caption("No human review has been recorded for this audit yet.")


def render() -> None:
    hero(
        "Human Review Workspace",
        "Record an independent human disposition next to the machine grade. Reviewer IDs "
        "are self-entered and are not authenticated identities.",
        kicker="HUMAN IN THE LOOP",
    )
    agreement = api_get("/api/analytics/annotation-agreement") or {}
    if agreement.get("status") == "computed":
        st.metric(
            "Cohen's κ (independent review decisions)",
            f"{agreement['cohen_kappa']:.3f}",
            help=agreement.get("note"),
        )
    else:
        st.info(
            agreement.get(
                "note",
                "Agreement requires two independent human reviewers on the same audit.",
            )
        )

    f1, f2, f3 = st.columns(3)
    decision = f1.selectbox(
        "Machine decision",
        ["(all)"] + DECISIONS,
        key="review_filter_decision",
    )
    severity = f2.selectbox(
        "Severity", ["(all)", "low", "medium", "high", "critical"], key="review_filter_severity"
    )
    hard_stop = f3.selectbox(
        "Hard stop", ["(all)", "yes", "no"], key="review_filter_hardstop"
    )
    params: dict = {"limit": 200}
    if decision != "(all)":
        params["decision"] = decision
    if severity != "(all)":
        params["severity"] = severity
    if hard_stop != "(all)":
        params["hard_stop"] = hard_stop == "yes"

    data = api_get("/api/audits", params=params)
    if data is None:
        empty_state("Audit history unavailable", "Start the API and run an audit first.")
        return
    audits = data.get("audits", [])
    if not audits:
        empty_state("No audits to review", "Run a Single Audit or Batch first.")
        return
    st.caption(f"{data.get('total', len(audits))} audit(s) match; showing up to 200.")
    st.dataframe(
        pd.DataFrame(audits)[
            [
                "id",
                "case_id",
                "project_id",
                "category",
                "severity",
                "overall_score",
                "decision",
                "hard_stop_triggered",
                "evaluation_mode",
                "created_at",
            ]
        ],
        width="stretch",
        hide_index=True,
        height=260,
    )
    audit_ids = [row["id"] for row in audits]
    if st.session_state.get("review_audit_id") not in audit_ids:
        st.session_state["review_audit_id"] = audit_ids[0]
    audit_id = st.selectbox("Select audit to review", audit_ids, key="review_audit_id")
    audit = api_get(f"/api/audits/{audit_id}")
    if not audit:
        st.error("The selected audit could not be loaded.")
        return
    st.divider()
    top = st.columns([1, 1, 1, 1])
    top[0].metric("Score", f"{audit.get('overall_score')}/100")
    top[1].markdown("**Decision**")
    top[1].markdown(decision_badge(audit.get("decision", "")), unsafe_allow_html=True)
    top[2].metric("Severity", audit.get("severity") or "—")
    top[3].metric("Hard stop", "yes" if audit.get("hard_stop_triggered") else "no")
    _review_form(audit)
