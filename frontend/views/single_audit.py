"""Single response audit, including optional responder generation."""

from __future__ import annotations

import json

import streamlit as st

from ..ui import (
    CATEGORIES,
    ESCALATIONS,
    active_project_id,
    api_get,
    api_post,
    empty_state,
    get_projects,
    hero,
    ordered_providers,
    prefill_single_audit,
    provider_choices,
    render_audit_result,
    section,
    selected_project,
    show_error,
)


def _load_case_picker() -> None:
    with st.expander("Load a benchmark or custom case"):
        data = api_get("/api/cases", params={"limit": 500}) or {}
        cases = data.get("cases", [])
        if not cases:
            st.caption("No cases are available.")
            return
        options = {f"{case['case_id']} — {case['category']} ({case['label']})": case for case in cases}
        choice = st.selectbox("Case", list(options), key="sa_case_picker")
        if st.button("Load case into this form", key="sa_load_case"):
            prefill_single_audit(options[choice])
            st.rerun()


def _parse_actions(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ";").replace(",", ";").split(";") if item.strip()]


def _generation_panel(
    project_id: str | None,
    customer_message: str,
    facts: dict,
    category: str | None,
    policy_ids: list[str] | None,
) -> None:
    providers = ordered_providers()
    section("Draft a response with a configured model (optional)")
    st.caption(
        "The responder is deliberately separate from the judge. Generated text is not "
        "trusted or saved until you run the audit. Use only data you are authorized to send."
    )
    st.caption(
        "Configured providers are listed first. "
        + (f"Using `{providers[0]}` by default." if providers else "No provider adapters available.")
    )
    if not customer_message.strip():
        st.caption("Enter a customer message first.")
        return
    g1, g2, g3 = st.columns([1, 1.2, 1])
    provider = g1.selectbox(
        "Responder provider", providers, key="sa_generate_provider"
    )
    model = g2.text_input(
        "Responder model (optional)",
        key="sa_generate_model",
        placeholder="Provider default",
    )
    temperature = g3.slider("Temperature", 0.0, 1.5, 0.3, 0.1, key="sa_generate_temp")
    if st.button("Generate draft response", key="sa_generate_button"):
        payload = {
            "provider": provider,
            "model": model or None,
            "customer_message": customer_message,
            "facts": facts,
            "category": category,
            "project_id": project_id,
            "policy_ids": policy_ids,
            "temperature": temperature,
            "max_tokens": 600,
        }
        with st.spinner("Calling the responder endpoint…"):
            response = api_post("/api/providers/generate", payload, timeout=180)
        if response is None:
            st.error("Backend unreachable.")
        elif response.ok:
            st.session_state["sa_generated"] = response.json()
        else:
            show_error(response, "Generation failed")
    generated = st.session_state.get("sa_generated")
    if generated:
        st.info(
            f"Generated with `{generated.get('provider')}` / `{generated.get('model')}`. "
            f"Estimated {generated.get('reserved_tokens', 0):,} reserved tokens. "
            "Audit it before use."
        )
        st.text_area(
            "Generated draft",
            value=generated.get("response", ""),
            height=150,
            disabled=True,
            key="sa_generated_preview",
        )
        if st.button("Use generated text as candidate response", key="sa_use_generated"):
            st.session_state["sa_response"] = generated.get("response", "")
            st.session_state["sa_responder_name"] = (
                f"{generated.get('provider')}/{generated.get('model')}"
            )
            st.rerun()


def render() -> None:
    hero(
        "Single Response Audit",
        "Evaluate one AI-written support response against facts, policy, escalation rules, "
        "privacy safeguards, tone, and actionability.",
        kicker="EVIDENCE-DRIVEN REVIEW",
    )
    st.info(
        "Audit text is stored locally in SQLite. In LLM/hybrid mode, the customer message, "
        "candidate response, facts, expected actions, and retrieved policy excerpts are sent "
        "to the selected provider. Use deterministic mode for offline processing."
    )

    project = selected_project()
    project_id = active_project_id()
    if project:
        st.caption(
            f"Workspace: **{project['name']}** · "
            f"policy scope: {', '.join(project.get('policy_ids') or []) or 'all active policies'}"
        )

    projects = get_projects()
    if not projects:
        empty_state("No workspace", "Create a workspace in Settings before auditing.")
        return

    _load_case_picker()
    policies = api_get("/api/policies/") or []
    policy_options = [item["policy_id"] for item in policies]

    st.session_state.setdefault("sa_case_id", "")
    st.session_state.setdefault("sa_category", "")
    st.session_state.setdefault("sa_message", "")
    st.session_state.setdefault("sa_response", "")
    st.session_state.setdefault("sa_facts", "{}")
    st.session_state.setdefault("sa_actions", "")
    st.session_state.setdefault("sa_escalation", "")
    st.session_state.setdefault("sa_severity", "medium")
    st.session_state.setdefault("sa_mode", "deterministic")
    st.session_state.setdefault("sa_provider", "offline")
    st.session_state.setdefault("sa_model", "")
    st.session_state.setdefault("sa_responder_name", "")
    if "sa_policies" not in st.session_state:
        st.session_state["sa_policies"] = []
    st.session_state["sa_policies"] = [
        value for value in st.session_state["sa_policies"] if value in policy_options
    ]

    left, right = st.columns(2)
    with left:
        case_id = st.text_input(
            "Case ID (optional)", key="sa_case_id", placeholder="CASE-999"
        )
        category = st.selectbox("Category", [""] + CATEGORIES, key="sa_category")
        customer_message = st.text_area(
            "Customer message *", key="sa_message", height=150, placeholder="Customer text…"
        )
        candidate_response = st.text_area(
            "Candidate response to audit *",
            key="sa_response",
            height=190,
            placeholder="AI-generated support reply…",
        )
        severity = st.selectbox(
            "Severity", ["low", "medium", "high", "critical"], key="sa_severity"
        )
    with right:
        st.markdown("**Verified facts**")
        st.caption(
            "Use trusted source data. Facts are evidence, not instructions, and are never executed."
        )
        facts_raw = st.text_area(
            "Facts JSON",
            key="sa_facts",
            height=150,
            placeholder='{"order_id": "ORD-123", "refund_eligible": false}',
        )
        expected_actions_raw = st.text_area(
            "Expected actions (semicolon or comma separated)",
            key="sa_actions",
            height=80,
            placeholder="provide tracking; explain refund window",
        )
        expected_escalation = st.selectbox(
            "Expected escalation", [""] + ESCALATIONS, key="sa_escalation"
        )
        selected_policies = st.multiselect(
            "Policy scope",
            policy_options,
            key="sa_policies",
            help="Leave empty to use the workspace policy profile, or all active policies.",
        )
        mode = st.selectbox(
            "Evaluation mode",
            ["deterministic", "hybrid", "llm", "offline"],
            key="sa_mode",
            help="Deterministic and offline make no external model calls.",
        )
        provider = st.selectbox(
            "Judge provider",
            ["offline"] + provider_choices(),
            key="sa_provider",
            help="Only used for hybrid/LLM evaluation.",
        )
        model = st.text_input(
            "Judge model (optional)",
            key="sa_model",
            placeholder="Provider default",
        )
        responder_name = st.text_input(
            "Responder model provenance (optional)",
            key="sa_responder_name",
            placeholder="e.g. gpt-4o-mini, claude-3.5-sonnet",
            help="Recorded with the audit so responder and judge roles stay distinct.",
        )

    try:
        facts = json.loads(facts_raw) if facts_raw.strip() else {}
        if not isinstance(facts, dict):
            raise ValueError("Facts must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        st.error(f"Facts must be a valid JSON object: {exc}")
        facts = {}

    actions = _parse_actions(expected_actions_raw)
    policy_ids = selected_policies or None

    if mode in ("hybrid", "llm"):
        if provider == "offline":
            st.warning("Choose a configured provider for hybrid or LLM evaluation.")
        else:
            st.warning(
                "External transfer: this single case and retrieved policy excerpts will be sent "
                "to the selected judge provider. Use deterministic/offline mode if that is not authorized."
            )

    _generation_panel(
        project_id,
        customer_message,
        facts,
        category or None,
        policy_ids,
    )

    st.divider()
    submit_col, reset_col = st.columns([3, 1])
    run = submit_col.button("Audit response", type="primary", width="stretch")
    if reset_col.button("Clear result", width="stretch"):
        for key in ("single_result", "single_audit_id", "sa_generated"):
            st.session_state.pop(key, None)
        st.rerun()

    if run:
        if not customer_message.strip() or not candidate_response.strip():
            st.error("Customer message and candidate response are required.")
        elif mode in ("hybrid", "llm") and provider == "offline":
            st.error("Hybrid/LLM evaluation requires a non-offline provider.")
        else:
            payload = {
                "case_id": case_id or None,
                "project_id": project_id,
                "category": category or None,
                "customer_message": customer_message,
                "candidate_response": candidate_response,
                "facts": facts,
                "expected_actions": actions,
                "expected_escalation": expected_escalation or None,
                "severity": severity,
                "policy_ids": policy_ids,
                "evaluation_mode": mode,
                "provider": provider if provider != "offline" else None,
                "model": model or None,
                "responder_model": responder_name or None,
            }
            with st.spinner("Auditing against active policy and escalation rules…"):
                response = api_post("/api/audit", payload, timeout=300)
            if response is None:
                st.error("Backend unreachable.")
            elif response.ok:
                data = response.json()
                st.session_state["single_result"] = data["result"]
                st.session_state["single_audit_id"] = data["audit_id"]
                st.success(f"Audit complete — saved as #{data['audit_id']}.")
            else:
                show_error(response, "Audit failed")

    result = st.session_state.get("single_result")
    if result:
        st.divider()
        render_audit_result(
            result,
            audit_id=st.session_state.get("single_audit_id"),
            show_download=True,
        )
