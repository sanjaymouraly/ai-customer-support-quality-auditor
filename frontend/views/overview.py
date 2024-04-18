"""Overview dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from ..ui import (
    DECISION_COLORS,
    api_get,
    empty_state,
    get_projects,
    hero,
    render_synthetic_notice,
    section,
    selected_project,
)


def _scope_selector() -> str | None:
    project = selected_project()
    if not project:
        return None
    all_projects = st.toggle(
        "Aggregate across all workspaces",
        value=False,
        help="Turn this on to include every project in the dashboard metrics.",
        key="overview_all_projects",
    )
    if all_projects:
        st.caption("Showing aggregate metrics for all workspaces.")
        return None
    st.caption(f"Showing **{project['name']}**.")
    return project["project_id"]


def render() -> None:
    hero(
        "AI Customer Support — Quality Auditor",
        "Policy-grounded, explainable evaluation of AI-written support responses, with "
        "hard stops, escalation intelligence, and human review.",
    )
    st.warning(
        "Decision support, not validated truth. Scores are heuristic; review the evidence, "
        "policy excerpts, and any hard stop before acting. Do not treat this dashboard as a "
        "refund, security, or legal authority."
    )

    project_id = _scope_selector()
    params = {"project_id": project_id} if project_id else {}
    summary = api_get("/api/analytics/summary", params=params)
    if summary is None:
        empty_state(
            "Backend unavailable",
            "The FastAPI service is not reachable. Start it with "
            "`uvicorn backend.app:app --host 0.0.0.0 --port 8000`.",
        )
        return
    render_synthetic_notice(summary)

    cols = st.columns(5)
    cols[0].metric("Audits", summary.get("total", 0))
    cols[1].metric("Average score", f"{summary.get('avg_score', 0):.1f}", help="Out of 100")
    cols[2].metric("Approval rate", f"{summary.get('pass_rate', 0) * 100:.1f}%")
    cols[3].metric(
        "Critical failures",
        f"{summary.get('critical_rate', 0) * 100:.1f}%",
        delta_color="inverse",
    )
    cols[4].metric(
        "Hard-stop rate",
        f"{summary.get('hard_stop_rate', 0) * 100:.1f}%",
        delta_color="inverse",
    )

    left, right = st.columns([1, 1.35])
    with left:
        section("Decision distribution")
        by_decision = summary.get("by_decision") or {}
        if by_decision:
            frame = pd.DataFrame(
                [{"Decision": key, "Count": value} for key, value in by_decision.items()]
            )
            fig = px.pie(
                frame,
                values="Count",
                names="Decision",
                hole=0.48,
                color="Decision",
                color_discrete_map=DECISION_COLORS,
            )
            fig.update_layout(
                height=330,
                margin=dict(l=8, r=8, t=16, b=8),
                legend=dict(orientation="h", y=-0.12),
            )
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state("No audits yet", "Run a Single Audit or a Batch to populate this view.")
    with right:
        section("Dimension averages", "0 = critical failure · 2 = partial · 4 = excellent")
        averages = summary.get("dimension_averages") or {}
        if averages:
            from ..ui import DIMENSION_LABELS

            frame = pd.DataFrame(
                [
                    {"Dimension": DIMENSION_LABELS.get(key, key), "Score": value}
                    for key, value in averages.items()
                ]
            ).sort_values("Score")
            fig = px.bar(
                frame,
                x="Score",
                y="Dimension",
                orientation="h",
                range_x=[0, 4],
                color="Score",
                color_continuous_scale=["#dc2626", "#f59e0b", "#22c55e"],
                range_color=[0, 4],
                text="Score",
            )
            fig.update_layout(
                height=330,
                coloraxis_showscale=False,
                margin=dict(l=8, r=16, t=16, b=8),
                xaxis_title="Average (0–4)",
            )
            st.plotly_chart(fig, width="stretch")
        else:
            empty_state("No dimension data", "Dimension averages appear after the first audit.")

    lower_left, lower_right = st.columns([1.3, 1])
    with lower_left:
        section("Recent audits")
        recent = summary.get("recent") or []
        if recent:
            frame = pd.DataFrame(recent)
            frame = frame.rename(
                columns={
                    "id": "Audit",
                    "case_id": "Case",
                    "project_id": "Workspace",
                    "decision": "Decision",
                    "overall_score": "Score",
                    "severity": "Severity",
                    "hard_stop_triggered": "Hard stop",
                    "created_at": "Created",
                    "data_source": "Source",
                }
            )
            st.dataframe(frame, width="stretch", hide_index=True, height=280)
        else:
            st.caption("No recent audits.")
    with lower_right:
        section("Severity mix")
        by_severity = summary.get("by_severity") or {}
        if by_severity:
            frame = pd.DataFrame(
                [{"Severity": key, "Count": value} for key, value in by_severity.items()]
            )
            fig = px.bar(
                frame,
                x="Severity",
                y="Count",
                color="Severity",
                text="Count",
                color_discrete_map={
                    "low": "#22c55e",
                    "medium": "#eab308",
                    "high": "#f97316",
                    "critical": "#dc2626",
                },
            )
            fig.update_layout(height=280, showlegend=False, margin=dict(l=8, r=8, t=16, b=8))
            st.plotly_chart(fig, width="stretch")
        else:
            st.caption("No severity data.")

    section("Workspaces")
    projects = get_projects()
    if projects:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Workspace": project["name"],
                        "ID": project["project_id"],
                        "Audits": project.get("audit_count", 0),
                        "Policy scope": ", ".join(project.get("policy_ids") or [])
                        or "All active policies",
                        "Default": bool(project.get("is_default")),
                    }
                    for project in projects
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    section("Quick start")
    st.markdown(
        """
1. **Single Audit** — paste a customer request and candidate response, or load a benchmark case.
2. **Batch Auditor** — upload CSV/JSON/JSONL, or run the bundled 170-case synthetic benchmark.
3. **Settings → Provider connections** — test a model endpoint. Local Ollama and deterministic mode need no paid key.
4. **Human Review** — record a separate human disposition; synthetic labels are never treated as human review.
"""
    )
