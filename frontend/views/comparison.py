"""Matched model comparison with explicit responder/judge roles."""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from ..ui import (
    CATEGORIES,
    active_project_id,
    api_post,
    decision_badge,
    hero,
    ordered_providers,
    provider_choices,
    section,
    selected_project,
    show_error,
)

DEFAULT_MESSAGE = "I want a refund for order ORD-12345 delivered 45 days ago."
DEFAULT_FACTS = (
    '{"order_id":"ORD-12345","order_age_days":45,'
    '"refund_window_days":30,"refund_eligible":false}'
)
DEFAULT_GOOD = (
    "I can see why you asked. The verified order is 45 days old, outside our 30-day refund "
    "window. I can't promise a refund, but I can submit a store-credit exception for "
    "supervisor review within 24 hours."
)
DEFAULT_BAD = "Sure, I've refunded you $99.99. It will appear tomorrow."


def _scenario() -> tuple[str, dict, str | None, list[str], str] | None:
    with st.expander("Shared scenario", expanded=True):
        message = st.text_area(
            "Customer message", value=DEFAULT_MESSAGE, height=90, key="mc_message"
        )
        facts_raw = st.text_area(
            "Verified facts JSON", value=DEFAULT_FACTS, height=90, key="mc_facts"
        )
        c1, c2 = st.columns(2)
        category = c1.selectbox(
            "Category",
            ["refund_request"] + [value for value in CATEGORIES if value != "refund_request"],
            key="mc_category",
        )
        severity = c2.selectbox(
            "Severity", ["low", "medium", "high", "critical"], index=1, key="mc_severity"
        )
        actions_raw = st.text_input(
            "Expected actions (semicolon separated)",
            value="explain refund window; do not promise refund",
            key="mc_actions",
        )
    try:
        facts = json.loads(facts_raw) if facts_raw.strip() else {}
        if not isinstance(facts, dict):
            raise ValueError("Facts must be an object")
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"Facts must be valid JSON: {exc}")
        return None
    if not message.strip():
        st.error("Customer message is required.")
        return None
    actions = [item.strip() for item in actions_raw.split(";") if item.strip()]
    return message, facts, category, actions, severity


def _judge_controls(prefix: str) -> tuple[str, str, str]:
    c1, c2, c3 = st.columns(3)
    mode = c1.selectbox(
        "Evaluation mode",
        ["deterministic", "hybrid", "llm", "offline"],
        key=f"{prefix}_mode",
    )
    provider = c2.selectbox(
        "Judge provider", ["offline"] + provider_choices(), key=f"{prefix}_provider"
    )
    model = c3.text_input("Judge model (optional)", key=f"{prefix}_model")
    return mode, provider, model


def _audit(
    label: str,
    response: str,
    *,
    message: str,
    facts: dict,
    category: str | None,
    actions: list[str],
    severity: str,
    mode: str,
    provider: str,
    model: str,
    responder_model: str | None,
    project_id: str | None,
) -> dict | None:
    if mode in ("hybrid", "llm") and provider == "offline":
        st.error(f"{label}: hybrid/LLM mode needs a configured judge provider.")
        return None
    payload = {
        "customer_message": message,
        "candidate_response": response,
        "facts": facts,
        "category": category,
        "expected_actions": actions,
        "severity": severity,
        "expected_escalation": None,
        "evaluation_mode": mode,
        "provider": provider if provider != "offline" else None,
        "model": model or None,
        "responder_model": responder_model,
        "project_id": project_id,
    }
    result = api_post("/api/audit", payload, timeout=300)
    if result is None:
        st.error(f"{label}: backend unreachable.")
        return None
    if not result.ok:
        show_error(result, f"{label}: audit failed")
        return None
    data = result.json()
    return {
        "label": label,
        "audit_id": data.get("audit_id"),
        "result": data["result"],
        "responder_model": responder_model,
    }


def _render_outcomes(outcomes: list[dict]) -> None:
    if not outcomes:
        return
    cols = st.columns(len(outcomes))
    for column, outcome in zip(cols, outcomes, strict=True):
        result = outcome["result"]
        column.subheader(outcome["label"])
        column.metric("Score", f"{result['overall_score']}/100")
        column.markdown(
            decision_badge(result.get("decision", "")), unsafe_allow_html=True
        )
        column.caption(
            f"Evaluator: {result.get('evaluator_model') or 'rule engine'} · "
            f"mode: {result.get('evaluation_mode')} · audit #{outcome.get('audit_id')}"
        )
        if outcome.get("responder_model"):
            column.caption(f"Responder: {outcome['responder_model']}")
        frame = pd.DataFrame(
            [
                {
                    "Dimension": dimension["dimension"],
                    "Score": dimension["score"],
                }
                for dimension in result.get("dimension_scores") or []
            ]
        )
        if not frame.empty:
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
                height=300,
                coloraxis_showscale=False,
                margin=dict(l=6, r=12, t=8, b=8),
                xaxis_title="0–4",
            )
            column.plotly_chart(fig, width="stretch")
        if result.get("hard_stop_triggered"):
            column.error(
                "Hard stop: " + "; ".join(result.get("hard_stop_reasons") or [])
            )
    if len(outcomes) == 2:
        delta = outcomes[0]["result"]["overall_score"] - outcomes[1]["result"]["overall_score"]
        st.info(
            f"Score difference (A − B): **{delta:+d}** points. A single run is not evidence "
            "of model superiority; judges may share bias."
        )


def _generate_draft(label: str, message: str, facts: dict, category: str | None) -> None:
    providers = ordered_providers()
    p1, p2 = st.columns(2)
    provider = p1.selectbox(
        f"{label} provider", providers, key=f"mc_gen_{label}_provider"
    )
    model = p2.text_input(
        f"{label} model (optional)", key=f"mc_gen_{label}_model", placeholder="Provider default"
    )
    if st.button(f"Generate {label} draft", key=f"mc_generate_{label}"):
        response = api_post(
            "/api/providers/generate",
            {
                "provider": provider,
                "model": model or None,
                "customer_message": message,
                "facts": facts,
                "category": category,
                "project_id": active_project_id(),
                "temperature": 0.3,
                "max_tokens": 600,
            },
            timeout=180,
        )
        if response is not None and response.ok:
            data = response.json()
            key = "mc_response_a" if label == "A" else "mc_response_b"
            st.session_state[key] = data["response"]
            st.session_state[f"mc_name_{label.lower()}"] = (
                f"{data.get('provider')}/{data.get('model')}"
            )
            st.success(f"{label} draft generated; review it before auditing.")
        elif response is not None:
            show_error(response, f"{label} generation failed")


def _responder_mode(
    message: str,
    facts: dict,
    category: str | None,
    actions: list[str],
    severity: str,
    project_id: str | None,
) -> None:
    st.caption(
        "Responder = model that wrote the candidate. Judge = model that grades it. They may "
        "be the same provider, but the roles are recorded separately."
    )
    method = st.radio(
        "Response source",
        ["Paste two responses", "Generate two drafts with configured connections"],
        horizontal=True,
        key="mc_response_source",
    )
    if method.startswith("Generate"):
        st.warning(
            "Generation sends the scenario text and retrieved policy excerpts to each selected "
            "provider. Use local or authorized endpoints only."
        )
        _generate_draft("A", message, facts, category)
        _generate_draft("B", message, facts, category)
    st.session_state.setdefault("mc_response_a", DEFAULT_GOOD)
    st.session_state.setdefault("mc_response_b", DEFAULT_BAD)
    st.session_state.setdefault("mc_name_a", "Responder A")
    st.session_state.setdefault("mc_name_b", "Responder B")
    a1, a2 = st.columns(2)
    name_a = a1.text_input("Responder A label", key="mc_name_a")
    name_b = a2.text_input("Responder B label", key="mc_name_b")
    response_a = a1.text_area(
        "Candidate response A", key="mc_response_a", height=190
    )
    response_b = a2.text_area(
        "Candidate response B", key="mc_response_b", height=190
    )
    st.divider()
    mode, provider, model = _judge_controls("mc_shared")
    if mode in ("hybrid", "llm") and provider != "offline":
        st.warning(
            "Both candidate responses and retrieved policy excerpts will be sent to the shared "
            "judge provider."
        )
    if st.button("Audit both responses", type="primary", key="mc_run_responders"):
        if not response_a.strip() or not response_b.strip():
            st.error("Both candidate responses are required.")
            return
        outcomes = []
        for label, response in ((name_a or "Responder A", response_a), (name_b or "Responder B", response_b)):
            outcome = _audit(
                label,
                response,
                message=message,
                facts=facts,
                category=category,
                actions=actions,
                severity=severity,
                mode=mode,
                provider=provider,
                model=model,
                responder_model=label,
                project_id=project_id,
            )
            if outcome:
                outcomes.append(outcome)
        st.session_state["mc_outcomes"] = outcomes


def _judge_mode(
    message: str,
    facts: dict,
    category: str | None,
    actions: list[str],
    severity: str,
    project_id: str | None,
) -> None:
    st.warning(
        "The same candidate is sent to two judges. Different judges can share training bias; "
        "this is not a blinded or statistically powered evaluation."
    )
    st.session_state.setdefault("mc_single_response", DEFAULT_BAD)
    response = st.text_area(
        "Shared candidate response", key="mc_single_response", height=150
    )
    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("**Judge A**")
        a_mode, a_provider, a_model = _judge_controls("mc_judge_a")
    with right:
        st.markdown("**Judge B**")
        b_mode, b_provider, b_model = _judge_controls("mc_judge_b")
    if st.button("Compare judges", type="primary", key="mc_run_judges"):
        if not response.strip():
            st.error("A candidate response is required.")
            return
        outcomes = []
        specs = [
            ("Judge A", a_mode, a_provider, a_model),
            ("Judge B", b_mode, b_provider, b_model),
        ]
        for label, mode, provider, model in specs:
            outcome = _audit(
                f"{label} · {model or provider}",
                response,
                message=message,
                facts=facts,
                category=category,
                actions=actions,
                severity=severity,
                mode=mode,
                provider=provider,
                model=model,
                responder_model="Shared candidate",
                project_id=project_id,
            )
            if outcome:
                outcomes.append(outcome)
        st.session_state["mc_outcomes"] = outcomes


def render() -> None:
    hero(
        "Model Comparison",
        "Matched-scenario comparison with explicit responder and judge identities. Every run "
        "is saved in audit history for reproducibility.",
        kicker="EVALUATION LAB",
    )
    st.info(
        "A score difference is an observation, not a verdict. Keep the scenario fixed, record "
        "model provenance, and repeat runs before drawing conclusions."
    )
    kind = st.radio(
        "Compare",
        ["Responder outputs", "Judge providers"],
        horizontal=True,
        key="mc_kind",
    )
    scenario = _scenario()
    if scenario is None:
        return
    message, facts, category, actions, severity = scenario
    section(
        "Comparison setup",
        "Both sides share the same customer text, facts, expected actions, and severity.",
    )
    project = selected_project()
    if project:
        st.caption(f"Audits are filed under **{project['name']}**.")
    project_id = active_project_id()
    if kind == "Responder outputs":
        _responder_mode(message, facts, category, actions, severity, project_id)
    else:
        _judge_mode(message, facts, category, actions, severity, project_id)

    outcomes = st.session_state.get("mc_outcomes") or []
    if outcomes:
        st.divider()
        section("Results")
        _render_outcomes(outcomes)
