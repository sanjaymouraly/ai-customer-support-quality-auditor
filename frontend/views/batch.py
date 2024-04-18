"""Batch auditing for uploaded datasets and the bundled synthetic benchmark."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from ..ui import (
    DECISION_COLORS,
    ESCALATIONS,
    active_project_id,
    api_get,
    api_post,
    empty_state,
    hero,
    provider_choices,
    safe_csv,
    section,
    selected_project,
    show_error,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
OPTIONAL_FIELDS = (
    "case_id",
    "category",
    "facts",
    "expected_actions",
    "expected_escalation",
    "severity",
    "policy_ids",
)


def _normalize_row(row: dict, index: int) -> dict | None:
    message = str(row.get("customer_message") or "").strip()
    response = str(row.get("candidate_response") or "").strip()
    if not message or not response:
        return None
    facts = row.get("facts") or {}
    if isinstance(facts, str):
        try:
            facts = json.loads(facts) if facts.strip() else {}
        except json.JSONDecodeError:
            facts = {}
    if not isinstance(facts, dict):
        facts = {}
    actions = row.get("expected_actions") or []
    if isinstance(actions, str):
        actions = [
            item.strip()
            for item in actions.replace("\n", ";").replace(",", ";").split(";")
            if item.strip()
        ]
    escalation = row.get("expected_escalation") or None
    if escalation not in ESCALATIONS:
        escalation = None
    severity = row.get("severity") or "medium"
    if severity not in ("low", "medium", "high", "critical"):
        severity = "medium"
    policy_ids = row.get("policy_ids") or []
    if isinstance(policy_ids, str):
        policy_ids = [item.strip() for item in policy_ids.split(",") if item.strip()]
    return {
        "customer_message": message,
        "candidate_response": response,
        "case_id": str(row.get("case_id") or f"row-{index + 1}"),
        "category": row.get("category") or None,
        "facts": facts,
        "expected_actions": actions,
        "expected_escalation": escalation,
        "severity": severity,
        "policy_ids": policy_ids or None,
    }


def _parse_upload(uploaded) -> tuple[list[dict], list[str]]:
    if uploaded.size > MAX_UPLOAD_BYTES:
        return [], ["Upload exceeds the 10 MB application limit."]
    content = uploaded.getvalue()
    name = uploaded.name.lower()
    rows: list[dict] = []
    errors: list[str] = []
    try:
        if name.endswith(".csv"):
            text = content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            if not reader.fieldnames:
                return [], ["CSV has no header row."]
            missing = {
                "customer_message",
                "candidate_response",
            } - {field.strip() for field in reader.fieldnames}
            if missing:
                return [], [f"CSV is missing required columns: {', '.join(sorted(missing))}"]
            rows = [dict(row) for row in reader]
        elif name.endswith(".json"):
            data = json.loads(content.decode("utf-8"))
            if isinstance(data, dict):
                data = data.get("cases", [])
            if not isinstance(data, list):
                return [], ["JSON must be a list of cases or an object with a 'cases' list."]
            rows = [row for row in data if isinstance(row, dict)]
        elif name.endswith((".jsonl", ".ndjson")):
            for line_number, line in enumerate(content.decode("utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    errors.append(f"Line {line_number}: invalid JSON ({exc.msg}).")
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                else:
                    errors.append(f"Line {line_number}: expected an object.")
        else:
            return [], ["Unsupported file type. Use CSV, JSON, or JSONL."]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"Could not parse the upload: {type(exc).__name__}."]

    cases: list[dict] = []
    skipped = 0
    for index, row in enumerate(rows):
        case = _normalize_row(row, index)
        if case is None:
            skipped += 1
            continue
        cases.append(case)
    if skipped:
        errors.append(f"Skipped {skipped} row(s) missing customer_message or candidate_response.")
    return cases, errors


def _batch_inputs() -> tuple[str | None, bool]:
    batch_id = st.text_input(
        "Batch ID (optional; keep it to resume a partial run)",
        placeholder="support-week-42",
        key="batch_id",
    )
    resume = st.checkbox(
        "Resume previously persisted items for this Batch ID",
        key="batch_resume",
        help="Completed items are skipped only when their full request hash matches.",
    )
    return (batch_id.strip() or None), resume


def _run_batch(
    cases: list[dict],
    *,
    project_id: str | None,
    mode: str,
    provider: str,
    model: str | None,
    batch_id: str | None,
    resume: bool,
) -> None:
    if not cases:
        st.error("No valid cases to audit.")
        return
    if len(cases) > 500:
        st.error("The API accepts at most 500 cases per batch.")
        return
    if mode in ("hybrid", "llm") and provider == "offline":
        st.error("Hybrid/LLM batch evaluation requires a non-offline provider.")
        return
    payload = {
        "cases": cases,
        "evaluation_mode": mode,
        "provider": provider if provider != "offline" else None,
        "model": model or None,
        "batch_id": batch_id,
        "project_id": project_id,
        "resume": resume,
    }
    with st.spinner(f"Auditing {len(cases)} cases…"):
        response = api_post("/api/audit/batch", payload, timeout=1800)
    if response is None:
        st.error("Backend unreachable.")
    elif response.ok:
        st.session_state["batch_response"] = response.json()
        st.success("Batch finished.")
    else:
        show_error(response, "Batch failed")


def _render_results(payload: dict) -> None:
    results = payload.get("results", [])
    done = [item for item in results if item.get("result")]
    failed = [item for item in results if not item.get("result")]
    frame = pd.DataFrame(
        [
            {
                "index": item.get("index"),
                "case_id": item.get("case_id"),
                "score": (item.get("result") or {}).get("overall_score"),
                "decision": (item.get("result") or {}).get("decision", "ERROR"),
                "hard_stop": (item.get("result") or {}).get("hard_stop_triggered"),
                "resumed": item.get("resumed", False),
                "error": item.get("error"),
            }
            for item in results
        ]
    )
    scores = [item["result"]["overall_score"] for item in done]
    full_batch_id = str(payload.get("batch_id") or "—")
    cols = st.columns(5)
    cols[0].metric("Batch", "Finished", help=full_batch_id)
    cols[1].metric("Evaluated", len(done))
    cols[2].metric("Errors", len(failed))
    cols[3].metric("Average score", f"{sum(scores) / len(scores):.1f}" if scores else "—")
    cols[4].metric("Resumed", payload.get("resumed_count", 0))
    st.caption(f"Batch ID: `{full_batch_id}`")

    if failed:
        st.warning(
            f"{len(failed)} item(s) failed. Errors are shown below and do not invalidate completed items."
        )

    if done:
        chart_frame = pd.DataFrame(
            [
                {"Decision": item["result"]["decision"]}
                for item in done
            ]
        )
        fig = px.histogram(
            chart_frame,
            x="Decision",
            color="Decision",
            text_auto=True,
            color_discrete_map=DECISION_COLORS,
            title="Decisions in this batch",
        )
        fig.update_layout(height=320, showlegend=False, margin=dict(l=8, r=8, t=40, b=8))
        st.plotly_chart(fig, width="stretch")

    st.dataframe(frame, width="stretch", hide_index=True, height=340)

    st.download_button(
        "Download full JSON results",
        json.dumps(results, indent=2, ensure_ascii=False),
        file_name=f"batch-{payload.get('batch_id', 'results')}.json",
        mime="application/json",
    )
    st.download_button(
        "Download formula-safe CSV summary",
        safe_csv(frame),
        file_name=f"batch-{payload.get('batch_id', 'results')}.csv",
        mime="text/csv",
    )
    errors_frame = frame[frame["decision"] == "ERROR"]
    if not errors_frame.empty:
        st.download_button(
            "Download error rows (CSV)",
            safe_csv(errors_frame),
            file_name="batch-errors.csv",
            mime="text/csv",
        )

    with st.expander("Inspect individual results"):
        if done:
            labels = {
                f"#{item.get('index')} {item.get('case_id')} — "
                f"{item['result']['overall_score']}/100 {item['result']['decision']}": item
                for item in done
            }
            choice = st.selectbox("Result", list(labels), key="batch_result_choice")
            from ..ui import render_audit_result

            render_audit_result(
                labels[choice]["result"],
                audit_id=labels[choice].get("audit_id"),
                compact=True,
            )


def render() -> None:
    hero(
        "Batch Auditor",
        "Audit a dataset with progress, per-item error isolation, resumable batch IDs, and "
        "downloadable evidence.",
        kicker="DATASET WORKFLOW",
    )
    project = selected_project()
    project_id = active_project_id()
    if project:
        st.caption(f"New audits are filed under **{project['name']}**.")
    st.markdown(
        "**Required columns:** `customer_message`, `candidate_response`  \n"
        "**Optional:** `case_id`, `category`, `facts` (JSON), `expected_actions` "
        "(semicolon-separated), `expected_escalation`, `severity`, `policy_ids` "
        "(comma-separated). Maximum 500 cases per request, 10 MB per upload."
    )

    batch_id, resume = _batch_inputs()
    uploaded = st.file_uploader("Upload dataset", type=["csv", "json", "jsonl", "ndjson"])
    b1, b2, b3 = st.columns(3)
    mode = b1.selectbox(
        "Evaluation mode", ["deterministic", "hybrid", "llm", "offline"], key="batch_mode"
    )
    provider = b2.selectbox(
        "Judge provider", ["offline"] + provider_choices(), key="batch_provider"
    )
    model = b3.text_input("Judge model (optional)", key="batch_model")
    if mode in ("hybrid", "llm") and provider != "offline":
        st.warning(
            "External transfer: every valid case and retrieved policy excerpt will be sent to "
            "the selected judge provider. Use deterministic mode for offline processing."
        )

    example = (
        'customer_message,candidate_response,case_id,category,expected_escalation,severity\n'
        '"Where is ORD-1?","Your package shipped with tracking TRK-123.",CASE-A,'
        "order_status,resolve,low\n"
        '"Refund for a 45-day-old order","Refunded instantly!",CASE-B,'
        "refund_request,resolve,medium"
    )
    with st.expander("Example CSV"):
        st.code(example, language="csv")

    if uploaded is not None:
        cases, errors = _parse_upload(uploaded)
        for error in errors:
            st.warning(error)
        if cases:
            section("Preview", f"Parsed {len(cases)} valid case(s).")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "case_id": case.get("case_id"),
                            "category": case.get("category"),
                            "severity": case.get("severity"),
                            "customer_message": case["customer_message"][:100],
                            "candidate_response": case["candidate_response"][:100],
                        }
                        for case in cases[:8]
                    ]
                ),
                width="stretch",
                hide_index=True,
            )
            if st.button(
                f"Run batch ({len(cases)} cases)", type="primary", key="batch_run_upload"
            ):
                _run_batch(
                    cases,
                    project_id=project_id,
                    mode=mode,
                    provider=provider,
                    model=model or None,
                    batch_id=batch_id,
                    resume=resume,
                )
    else:
        section("Bundled synthetic benchmark", "170 synthetic cases · not human-reviewed")
        st.caption(
            "This runs the deterministic rule engine over the full bundled benchmark. "
            "Reference labels are synthetic and must not be reported as human annotation."
        )
        benchmark_id = st.text_input(
            "Benchmark batch ID",
            value=f"benchmark-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
            key="benchmark_batch_id",
        )
        if st.button("Run full synthetic benchmark", key="benchmark_run"):
            data = api_get("/api/cases", params={"limit": 500}) or {}
            cases = []
            for case in data.get("cases", []):
                if not str(case.get("case_id", "")).startswith("CASE-"):
                    continue
                cases.append(
                    {
                        key: case.get(key)
                        for key in (
                            "case_id",
                            "category",
                            "customer_message",
                            "candidate_response",
                            "facts",
                            "policy_ids",
                            "expected_actions",
                            "expected_escalation",
                            "severity",
                        )
                    }
                )
            _run_batch(
                cases,
                project_id=project_id,
                mode="deterministic",
                provider="offline",
                model=None,
                batch_id=benchmark_id or f"benchmark-{uuid.uuid4().hex[:8]}",
                resume=False,
            )

    payload = st.session_state.get("batch_response")
    if payload:
        st.divider()
        _render_results(payload)
    elif uploaded is None:
        empty_state(
            "No batch results yet",
            "Upload a dataset or run the bundled benchmark. Results persist in audit history.",
        )
