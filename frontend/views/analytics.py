"""Analytics, audit history, and report export."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..ui import (
    DECISION_COLORS,
    DECISIONS,
    DIMENSION_LABELS,
    api_get,
    api_post,
    empty_state,
    hero,
    render_synthetic_notice,
    section,
    selected_project,
    show_error,
)


def _scope() -> str | None:
    project = selected_project()
    if not project:
        return None
    aggregate = st.toggle(
        "Aggregate across all workspaces",
        value=False,
        key="analytics_all_projects",
    )
    if aggregate:
        return None
    st.caption(f"Scoped to **{project['name']}**.")
    return project["project_id"]


def render() -> None:
    hero(
        "Analytics & Reports",
        "Operational quality signals, hard-stop rates, dimension weaknesses, escalation "
        "routing, and exportable summaries.",
        kicker="PORTFOLIO INSIGHT",
    )
    project_id = _scope()
    scope_params = {"project_id": project_id} if project_id else {}
    summary = api_get("/api/analytics/summary", params=scope_params)
    if summary is None:
        empty_state("Analytics unavailable", "Start the API and run at least one audit.")
        return
    render_synthetic_notice(summary)

    row = st.columns(3)
    row[0].metric("Audits", summary.get("total", 0))
    row[1].metric("Average score", f"{summary.get('avg_score', 0):.1f}", help="Out of 100")
    row[2].metric("Approval rate", f"{summary.get('pass_rate', 0) * 100:.1f}%")
    row = st.columns(3)
    row[0].metric(
        "Critical rate",
        f"{summary.get('critical_rate', 0) * 100:.1f}%",
        delta_color="inverse",
    )
    row[1].metric(
        "Hard-stop rate",
        f"{summary.get('hard_stop_rate', 0) * 100:.1f}%",
        delta_color="inverse",
    )
    row[2].metric(
        "Escalation issues",
        sum(
            value
            for key, value in (summary.get("by_escalation") or {}).items()
            if key in ("under_escalation", "over_escalation")
        ),
    )

    row1, row2 = st.columns(2)
    with row1:
        section("Decision mix")
        by_decision = summary.get("by_decision") or {}
        if by_decision:
            frame = pd.DataFrame(
                [{"Decision": key, "Count": value} for key, value in by_decision.items()]
            )
            fig = px.bar(
                frame,
                x="Decision",
                y="Count",
                color="Decision",
                text="Count",
                color_discrete_map=DECISION_COLORS,
            )
            fig.update_layout(
                height=320, showlegend=False, margin=dict(l=8, r=8, t=16, b=8)
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No decisions recorded.")
    with row2:
        section("Escalation routing")
        by_escalation = summary.get("by_escalation") or {}
        if by_escalation:
            frame = pd.DataFrame(
                [{"Verdict": key, "Count": value} for key, value in by_escalation.items()]
            )
            fig = px.pie(
                frame,
                values="Count",
                names="Verdict",
                hole=0.45,
                color="Verdict",
                color_discrete_map={
                    "appropriate": "#16a34a",
                    "under_escalation": "#dc2626",
                    "over_escalation": "#f59e0b",
                    "unknown": "#94a3b8",
                },
            )
            fig.update_layout(height=320, margin=dict(l=8, r=8, t=16, b=8))
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No escalation verdicts recorded.")

    section("Dimension averages", "Identify systemic weaknesses across the scoped audits.")
    averages = summary.get("dimension_averages") or {}
    if averages:
        frame = pd.DataFrame(
            [
                {
                    "Dimension": DIMENSION_LABELS.get(key, key),
                    "Average": value,
                    "Gap to 4": round(4 - value, 2),
                }
                for key, value in averages.items()
            ]
        ).sort_values("Average")
        st.dataframe(frame, width="stretch", hide_index=True)
        fig = px.bar(
            frame,
            x="Average",
            y="Dimension",
            orientation="h",
            range_x=[0, 4],
            color="Average",
            color_continuous_scale=["#dc2626", "#f59e0b", "#22c55e"],
                range_color=[0, 4],
            text="Average",
        )
        fig.update_layout(
            height=340,
            coloraxis_showscale=False,
            margin=dict(l=8, r=16, t=16, b=8),
            xaxis_title="Average (0–4)",
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.caption("No dimension scores recorded.")

    st.divider()
    section("Audit history", "Filter, inspect, and export the matching audits.")
    f1, f2, f3, f4 = st.columns(4)
    search = f1.text_input(
        "Search", placeholder="case ID, category, customer text", key="analytics_search"
    )
    decision = f2.selectbox(
        "Decision", ["(all)"] + DECISIONS, key="analytics_decision"
    )
    severity = f3.selectbox(
        "Severity", ["(all)", "low", "medium", "high", "critical"], key="analytics_severity"
    )
    hard_stop = f4.selectbox("Hard stop", ["(all)", "yes", "no"], key="analytics_hardstop")
    params: dict = {"limit": 1000}
    params.update(scope_params)
    if search:
        params["q_text"] = search
    if decision != "(all)":
        params["decision"] = decision
    if severity != "(all)":
        params["severity"] = severity
    if hard_stop != "(all)":
        params["hard_stop"] = hard_stop == "yes"
    history = api_get("/api/audits", params=params) or {"audits": []}
    rows = history.get("audits", [])
    if not rows:
        st.info("No audits match the current filters.")
    else:
        st.caption(f"{history.get('total', len(rows))} matching audit(s); showing up to 1000.")
        frame = pd.DataFrame(rows)
        st.dataframe(frame, width="stretch", hide_index=True, height=300)
        ids = [int(row["id"]) for row in rows]
        fmt = st.selectbox("Export format", ["csv", "json", "html"], key="export_format")
        if st.button("Prepare export for filtered audits", key="export_prepare"):
            response = api_post(
                "/api/export", {"format": fmt, "audit_ids": ids}, timeout=120
            )
            if response is not None and response.ok:
                st.session_state["export_payload"] = {
                    "content": response.content,
                    "format": fmt,
                    "count": len(ids),
                }
            elif response is not None:
                show_error(response, "Export failed")
        export = st.session_state.get("export_payload")
        if export:
            mime = {
                "json": "application/json",
                "csv": "text/csv",
                "html": "text/html",
            }[export["format"]]
            st.download_button(
                f"Download {export['format'].upper()} ({export['count']} audits)",
                export["content"],
                file_name=f"audits.{export['format']}",
                mime=mime,
                key="export_download",
            )
            if export["format"] == "html":
                st.caption(
                    "Open the HTML file and use the browser's Print → Save as PDF for a PDF."
                )
            st.caption(
                "Exports omit raw customer text and neutralise spreadsheet formula prefixes."
            )

    st.divider()
    trend_data = api_get("/api/analytics/trends", params=scope_params)
    if trend_data and trend_data.get("trend"):
        section("Volume and quality over time")
        frame = pd.DataFrame(trend_data["trend"])
        c1, c2 = st.columns(2)
        fig = px.line(
            frame,
            x="date",
            y="avg_score",
            markers=True,
            title="Average score by UTC date",
        )
        fig.update_layout(height=300, margin=dict(l=8, r=8, t=40, b=8))
        fig.update_xaxes(type="category", tickangle=-20)
        c1.plotly_chart(fig, width="stretch")
        fig2 = px.bar(frame, x="date", y="count", title="Audits by UTC date")
        fig2.update_layout(height=300, margin=dict(l=8, r=8, t=40, b=8))
        fig2.update_xaxes(type="category", tickangle=-20)
        c2.plotly_chart(fig2, width="stretch")
    else:
        st.caption("Trend data will appear after audits span multiple dates.")

    agreement = api_get("/api/analytics/annotation-agreement") or {}
    section("Human annotation reliability")
    if agreement.get("status") == "computed":
        st.metric(
            "Cohen's κ (independent review decisions)",
            f"{agreement['cohen_kappa']:.3f}",
            help=agreement.get("note"),
        )
    else:
        st.caption(
            agreement.get(
                "note",
                "Agreement requires two independent human reviewers on the same audits.",
            )
        )
