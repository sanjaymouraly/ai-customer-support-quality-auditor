"""Benchmark and custom scenario explorer."""

from __future__ import annotations

import json
import uuid

import pandas as pd
import streamlit as st

from ..ui import (
    CATEGORIES,
    ESCALATIONS,
    api_delete,
    api_get,
    api_post,
    api_put,
    empty_state,
    hero,
    prefill_single_audit,
    section,
    show_error,
)

SEVERITIES = ["low", "medium", "high", "critical"]
LABELS = ["positive", "negative", "borderline"]


def _open_in_single_audit(case: dict) -> None:
    prefill_single_audit(case)
    st.session_state["nav"] = "Single Audit"
    st.rerun()


def _case_detail(case: dict) -> None:
    left, right = st.columns(2)
    left.markdown("**Customer message**")
    left.info(case.get("customer_message", ""))
    right.markdown("**Candidate response**")
    if case.get("label") == "negative":
        right.error(case.get("candidate_response", ""))
    elif case.get("label") == "positive":
        right.success(case.get("candidate_response", ""))
    else:
        right.warning(case.get("candidate_response", ""))
    meta = st.columns(4)
    meta[0].metric("Category", case.get("category", "—"))
    meta[1].metric("Severity", case.get("severity", "—"))
    meta[2].metric("Reference label", case.get("label", "—"))
    meta[3].metric("Expected escalation", case.get("expected_escalation", "—"))
    st.caption(case.get("notes", ""))
    st.json(case.get("facts") or {})
    st.markdown(
        f"**Expected actions:** {', '.join(case.get('expected_actions') or []) or '—'}  \n"
        f"**Policy IDs:** {', '.join(case.get('policy_ids') or []) or 'workspace scope'}"
    )
    provenance = (case.get("evaluation_metadata") or {}).get("label_provenance")
    if provenance:
        st.caption(f"Label provenance: `{provenance}` — not a human-reviewed ground truth.")
    if st.button("Open this case in Single Audit", type="primary", key="scenario_open_single"):
        _open_in_single_audit(case)


def _sync_custom_form(selection: str, editing: dict | None) -> None:
    if st.session_state.get("_custom_form_for") == selection:
        return
    defaults = {
        "cf_id": (editing or {}).get("case_id") or f"USR-{uuid.uuid4().hex[:6].upper()}",
        "cf_category": (editing or {}).get("category") or "order_status",
        "cf_message": (editing or {}).get("customer_message") or "",
        "cf_response": (editing or {}).get("candidate_response") or "",
        "cf_facts": json.dumps((editing or {}).get("facts") or {}, indent=2, ensure_ascii=False),
        "cf_actions": "; ".join((editing or {}).get("expected_actions") or []),
        "cf_escalation": (editing or {}).get("expected_escalation") or "resolve",
        "cf_severity": (editing or {}).get("severity") or "medium",
        "cf_label": (editing or {}).get("label") or "borderline",
        "cf_notes": (editing or {}).get("notes") or "",
    }
    for key, value in defaults.items():
        st.session_state[key] = value
    st.session_state["_custom_form_for"] = selection


def _custom_workspace() -> None:
    section(
        "Custom scenario workspace",
        "Local, user-authored cases are stored separately from the bundled synthetic benchmark. "
        "Do not enter real customer PII.",
    )
    data = api_get("/api/scenarios") or {"scenarios": []}
    rows = data.get("scenarios", [])
    options = ["Create new"] + [row["case_id"] for row in rows]
    selection = st.selectbox("Custom scenario", options, key="custom_select")
    editing = next((row for row in rows if row["case_id"] == selection), None)
    _sync_custom_form(selection, editing)

    with st.form("custom_scenario_form"):
        case_id = st.text_input("Case ID", key="cf_id", disabled=editing is not None)
        category = st.selectbox("Category", CATEGORIES, key="cf_category")
        customer_message = st.text_area("Customer message", key="cf_message", height=120)
        candidate_response = st.text_area("Candidate response", key="cf_response", height=150)
        facts_raw = st.text_area("Facts JSON", key="cf_facts", height=100)
        actions_raw = st.text_input(
            "Expected actions (semicolon separated)", key="cf_actions"
        )
        e1, e2 = st.columns(2)
        expected_escalation = e1.selectbox(
            "Expected escalation", ESCALATIONS, key="cf_escalation"
        )
        severity = e2.selectbox("Severity", SEVERITIES, key="cf_severity")
        label = st.selectbox(
            "Reference disposition (synthetic / user-authored)",
            LABELS,
            key="cf_label",
        )
        notes = st.text_input("Notes", key="cf_notes")
        save = st.form_submit_button("Save custom scenario", type="primary")

    if save:
        try:
            facts = json.loads(facts_raw) if facts_raw.strip() else {}
            if not isinstance(facts, dict):
                raise ValueError("Facts must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            st.error(f"Facts must be valid JSON: {exc}")
        else:
            payload = {
                "case_id": case_id.strip(),
                "category": category,
                "customer_message": customer_message,
                "facts": facts,
                "policy_ids": [],
                "candidate_response": candidate_response,
                "expected_actions": [
                    item.strip() for item in actions_raw.split(";") if item.strip()
                ],
                "expected_escalation": expected_escalation,
                "severity": severity,
                "label": label,
                "notes": notes,
                "evaluation_metadata": {
                    "dataset_version": "local",
                    "label_provenance": "user_authored_reference_not_human_reviewed",
                    "dataset": "local_custom",
                },
            }
            if not customer_message.strip() or not candidate_response.strip():
                st.error("Customer message and candidate response are required.")
            else:
                response = (
                    api_put(f"/api/scenarios/{selection}", payload)
                    if editing
                    else api_post("/api/scenarios", payload)
                )
                if response is not None and response.ok:
                    st.success("Custom scenario saved. It is not part of the public benchmark.")
                    st.session_state.pop("_custom_form_for", None)
                    st.rerun()
                elif response is not None:
                    show_error(response, "Could not save custom scenario")

    if editing:
        confirm = st.checkbox(
            "I understand this removes the local scenario.", key="custom_delete_confirm"
        )
        if st.button(
            "Delete selected custom scenario",
            type="secondary",
            disabled=not confirm,
            key="custom_delete",
        ):
            response = api_delete(f"/api/scenarios/{selection}")
            if response is not None and response.ok:
                st.success("Custom scenario deleted.")
                st.session_state.pop("_custom_form_for", None)
                st.rerun()
            elif response is not None:
                show_error(response, "Could not delete custom scenario")


def render() -> None:
    hero(
        "Scenario Explorer",
        "Browse the 170-case synthetic benchmark, inspect expected behaviour, and maintain "
        "local scenarios without overwriting the bundled dataset.",
        kicker="BENCHMARK LIBRARY",
    )
    data = api_get("/api/cases", params={"limit": 500})
    if data is None:
        empty_state(
            "Cases unavailable",
            "Check that the API is running and that `data/synthetic/cases.json` exists.",
        )
    else:
        cases = data.get("cases", [])
        if not cases:
            st.info("No cases are available.")
        else:
            st.caption(
                f"{len(cases)} total cases. Labels are synthetic reference design, not "
                "human-reviewed ground truth."
            )
            f1, f2, f3, f4 = st.columns(4)
            categories = sorted({case.get("category") for case in cases if case.get("category")})
            category = f1.selectbox("Category", ["(all)"] + categories, key="scenario_category")
            severity = f2.selectbox("Severity", ["(all)"] + SEVERITIES, key="scenario_severity")
            label = f3.selectbox("Reference label", ["(all)"] + LABELS, key="scenario_label")
            search = f4.text_input(
                "Search", placeholder="refund, tracking, damaged…", key="scenario_search"
            )
            filtered = cases
            if category != "(all)":
                filtered = [case for case in filtered if case.get("category") == category]
            if severity != "(all)":
                filtered = [case for case in filtered if case.get("severity") == severity]
            if label != "(all)":
                filtered = [case for case in filtered if case.get("label") == label]
            if search:
                needle = search.lower()
                filtered = [
                    case
                    for case in filtered
                    if needle in case.get("customer_message", "").lower()
                    or needle in case.get("candidate_response", "").lower()
                    or needle in case.get("case_id", "").lower()
                ]
            st.caption(f"Showing {len(filtered)} of {len(cases)} cases.")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "case_id": case.get("case_id"),
                            "category": case.get("category"),
                            "severity": case.get("severity"),
                            "label": case.get("label"),
                            "expected_escalation": case.get("expected_escalation"),
                            "customer_message": case.get("customer_message", "")[:100],
                        }
                        for case in filtered
                    ]
                ),
                width="stretch",
                hide_index=True,
                height=330,
            )
            if filtered:
                choice = st.selectbox(
                    "Inspect case",
                    [case["case_id"] for case in filtered],
                    key="scenario_detail_id",
                )
                selected = next(case for case in filtered if case["case_id"] == choice)
                st.divider()
                _case_detail(selected)
            else:
                st.info("No cases match the current filters.")

    st.divider()
    _custom_workspace()
