"""Escalation intelligence dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..ui import active_project_id, api_get, empty_state, hero, render_audit_result, section


def render() -> None:
    hero(
        "Escalation Intelligence",
        "Find under-escalation, over-escalation, and human-intervention cases with urgency, "
        "destination, and evidence.",
        kicker="ROUTING SAFETY",
    )
    st.caption(
        "The auditor records recommendations only. It never contacts a customer, issues a "
        "refund, locks an account, or transfers a case."
    )
    c1, c2, c3 = st.columns(3)
    urgency = c1.selectbox(
        "Urgency", ["(all)", "low", "medium", "high", "critical"], key="esc_urgency"
    )
    verdict = c2.selectbox(
        "Verdict",
        ["(all)", "under_escalation", "over_escalation", "appropriate"],
        key="esc_verdict",
    )
    category = c3.text_input("Category", placeholder="privacy_fraud", key="esc_category")
    params: dict = {"limit": 1000}
    project_id = active_project_id()
    if project_id:
        params["project_id"] = project_id
    if urgency != "(all)":
        params["urgency"] = urgency
    if verdict != "(all)":
        params["verdict"] = verdict
    if category:
        params["category"] = category

    data = api_get("/api/escalations", params=params)
    if data is None:
        empty_state("Escalation data unavailable", "Start the API and run an audit first.")
        return
    cases = data.get("cases", [])
    st.metric("Cases matching filters", data.get("total", 0))
    if not cases:
        st.info("No escalation cases match these filters.")
    else:
        frame = pd.DataFrame(cases)
        display = frame[
            [
                "audit_id",
                "case_id",
                "category",
                "expected",
                "actual",
                "verdict",
                "urgency",
                "destination",
                "overall_score",
                "decision",
            ]
        ]
        st.dataframe(display, width="stretch", hide_index=True, height=320)
        choice = st.selectbox(
            "Inspect escalation case",
            [row["audit_id"] for row in cases],
            key="esc_detail_id",
        )
        detail = api_get(f"/api/audits/{choice}")
        if detail:
            st.divider()
            st.subheader(f"{detail.get('case_id')} — {detail['escalation'].get('verdict', '')}")
            render_audit_result(detail, audit_id=choice, show_download=False, compact=True)

    trends = api_get(
        "/api/analytics/escalations-by-category",
        params={"project_id": project_id} if project_id else None,
    ) or {}
    if trends.get("categories"):
        section("Routing outcomes by category")
        frame = pd.DataFrame(trends["categories"])
        melted = frame.melt(
            id_vars="category",
            value_vars=["appropriate", "under_escalation", "over_escalation"],
            var_name="Verdict",
            value_name="Count",
        )
        fig = px.bar(
            melted,
            x="category",
            y="Count",
            color="Verdict",
            barmode="group",
            color_discrete_map={
                "appropriate": "#16a34a",
                "under_escalation": "#dc2626",
                "over_escalation": "#f59e0b",
            },
        )
        fig.update_layout(
            height=360,
            margin=dict(l=8, r=8, t=16, b=8),
            xaxis_title="Category",
            legend_title="",
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No escalation verdicts are recorded yet.")
