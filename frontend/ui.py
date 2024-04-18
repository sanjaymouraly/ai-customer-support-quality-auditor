"""Shared UI helpers for the Streamlit auditor.

The Streamlit process calls the FastAPI server side; provider keys never reach the
browser or this UI process. All visible controls in the pages are wired to real API
operations.
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DOTENV = dotenv_values(ROOT / ".env")
API_BASE = (
    os.getenv("API_BASE_URL")
    or DOTENV.get("API_BASE_URL")
    or "http://localhost:8000"
).rstrip("/")
API_TOKEN = (os.getenv("API_ACCESS_TOKEN") or DOTENV.get("API_ACCESS_TOKEN") or "").strip()
API_HEADERS = {"Authorization": f"Bearer {API_TOKEN}"} if API_TOKEN else {}

DECISIONS = [
    "Approve",
    "Needs Revision",
    "Human Review Required",
    "Escalation Required",
    "Critical Failure",
]
CATEGORIES = [
    "order_status",
    "delayed_delivery",
    "damaged_product",
    "refund_request",
    "cancellation_return",
    "billing_dispute",
    "duplicate_charge",
    "subscription",
    "warranty_claim",
    "account_access",
    "policy_exception",
    "angry_customer",
    "escalation_request",
    "privacy_fraud",
    "insufficient_info",
    "multi_question",
    "multilingual_ambiguous",
    "adversarial",
]
ESCALATIONS = [
    "resolve",
    "ask_info",
    "verify_identity",
    "refer",
    "escalate_billing",
    "escalate_supervisor",
    "escalate_security",
]
DIMENSION_LABELS = {
    "factual_accuracy": "Factual accuracy",
    "completeness": "Completeness",
    "policy_compliance": "Policy compliance",
    "hallucination": "Hallucination",
    "resolution_guidance": "Resolution guidance",
    "tone_clarity": "Tone & clarity",
    "privacy_safety": "Privacy & safety",
    "escalation": "Escalation",
    "actionability": "Actionability",
}
DECISION_COLORS = {
    "Approve": "#16a34a",
    "Needs Revision": "#d97706",
    "Human Review Required": "#7c3aed",
    "Escalation Required": "#dc2626",
    "Critical Failure": "#991b1b",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------
def api_get(path: str, params: dict | None = None, timeout: int = 20):
    try:
        response = requests.get(
            f"{API_BASE}{path}", params=params, headers=API_HEADERS, timeout=timeout
        )
        return response.json() if response.ok else None
    except (requests.RequestException, ValueError):
        return None


def api_request(
    method: str, path: str, data: dict | None = None, timeout: int = 60, files=None
):
    try:
        if files is not None:
            return requests.request(
                method,
                f"{API_BASE}{path}",
                data=data,
                files=files,
                headers=API_HEADERS,
                timeout=timeout,
            )
        return requests.request(
            method,
            f"{API_BASE}{path}",
            json=data,
            headers=API_HEADERS,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        st.error(f"API connection failed: {type(exc).__name__}. Check that FastAPI is running.")
        return None


def api_post(path: str, data: dict | None = None, timeout: int = 60, files=None):
    return api_request("POST", path, data, timeout=timeout, files=files)


def api_put(path: str, data: dict | None = None):
    return api_request("PUT", path, data, timeout=30)


def api_delete(path: str):
    return api_request("DELETE", path, timeout=20)


def show_error(response, fallback: str = "Request failed") -> None:
    if response is None:
        return
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if isinstance(detail, list):
        detail = "; ".join(str(item) for item in detail)
    st.error(f"{fallback}: {detail}")


def api_healthy() -> bool:
    return api_get("/api/health", timeout=3) is not None


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(
        """
<style>
:root { --navy:#0b1220; --blue:#2563eb; --ink:#0f172a; --muted:#64748b; }
html, body, [class*="css"] { font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
[data-testid="stAppViewContainer"] { background: #f4f7fb; }
[data-testid="stHeader"] { background: rgba(244,247,251,0.8); }
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0b1220 0%, #101d36 60%, #0e2a52 100%);
  border-right: 1px solid rgba(255,255,255,0.06);
}
[data-testid="stSidebar"] * { color: #dbe7f7; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: white; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  padding: 6px 8px; border-radius: 9px; margin: 1px 0;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(255,255,255,0.08); }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.12); }
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
  background: #ffffff; border-color: rgba(255,255,255,0.16); color: #0f172a;
}
[data-testid="stSidebar"] .react-aria-ComboBox {
  background: #ffffff; border-radius: 8px;
}
[data-testid="stSidebar"] .react-aria-ComboBox input {
  color: #0f172a !important; background: #ffffff !important;
}
[data-testid="stSidebar"] .react-aria-ComboBox button,
[data-testid="stSidebar"] .react-aria-ComboBox button svg {
  color: #0f172a !important; fill: #0f172a !important;
}
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] span,
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] input,
[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] svg {
  color: #0f172a; fill: #0f172a;
}
[data-testid="stSidebar"] [data-baseweb="popover"] * { color: #0f172a; }
[data-testid="stMetric"] {
  background: #ffffff; border: 1px solid #e2e8f0; border-radius: 15px;
  padding: 14px 18px 12px; box-shadow: 0 5px 18px rgba(15,23,42,0.05);
}
[data-testid="stMetricLabel"] { color: #64748b; font-weight: 600; }
[data-testid="stMetricValue"] {
  color: #0f172a; font-weight: 750;
  font-size: clamp(1.05rem, 1.3vw, 1.75rem);
  overflow: visible; text-overflow: clip;
}
[data-testid="stMetricValue"] > div {
  font-size: inherit !important; white-space: normal; overflow-wrap: anywhere;
}
.hero {
  background: radial-gradient(circle at 85% 15%, rgba(96,165,250,0.45), transparent 34%),
              linear-gradient(135deg, #0b1220 0%, #123b7a 55%, #2563eb 100%);
  border-radius: 20px; padding: 26px 30px 24px; margin: 4px 0 20px;
  box-shadow: 0 14px 40px rgba(15,23,42,0.16);
}
.hero-kicker { color:#93c5fd; font-size:0.78rem; letter-spacing:.14em; text-transform:uppercase; font-weight:700; }
.hero h1 { color:#ffffff !important; margin:6px 0 6px; font-size:2.05rem; letter-spacing:-0.02em; }
.hero p { color:#dbeafe; margin:0; max-width:960px; line-height:1.55; }
.eyebrow { color:#2563eb; font-weight:700; letter-spacing:.08em; text-transform:uppercase; font-size:.76rem; }
.section-title { font-weight:750; color:#0f172a; margin: 6px 0 2px; }
.badge {
  display:inline-block; padding:5px 11px; border-radius:999px; color:white;
  font-size:.78rem; font-weight:700; letter-spacing:.01em;
}
.score-ring {
  background:#fff; border:1px solid #e2e8f0; border-radius:18px; padding:20px;
  box-shadow:0 8px 24px rgba(15,23,42,0.06); text-align:center;
}
.score-ring .value { font-size:2.5rem; font-weight:800; color:#0f172a; line-height:1.05; }
.score-ring .label { color:#64748b; font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; }
.notice {
  background:#fff7ed; border:1px solid #fed7aa; color:#9a3412;
  border-radius:12px; padding:12px 15px; margin:8px 0 14px; font-size:.9rem;
}
.muted { color:#64748b; font-size:.88rem; }
.pill {
  display:inline-block; background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe;
  border-radius:999px; padding:2px 9px; margin:2px 4px 2px 0; font-size:.76rem; font-weight:600;
}
.policy-quote { border-left:3px solid #60a5fa; padding:2px 0 2px 14px; color:#334155; }
div.stButton > button[kind="primary"] { border-radius:10px; font-weight:700; }
[data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; }
[data-testid="stExpander"] { background:#ffffff; border-radius:12px; border:1px solid #e6ecf5; }
</style>
        """,
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str, kicker: str = "AI CUSTOMER SUPPORT QUALITY") -> None:
    st.markdown(
        f"""<div class="hero"><div class="hero-kicker">{html.escape(kicker)}</div>
        <h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>""",
        unsafe_allow_html=True,
    )


def section(title: str, caption: str | None = None) -> None:
    st.markdown(f"<div class='section-title'>{html.escape(title)}</div>", unsafe_allow_html=True)
    if caption:
        st.caption(caption)


def empty_state(title: str, body: str) -> None:
    st.info(f"**{title}**  \n{body}")


def decision_badge(decision: str) -> str:
    color = DECISION_COLORS.get(decision, "#475569")
    return f"<span class='badge' style='background:{color}'>{html.escape(decision)}</span>"


def score_color(score: int | float) -> str:
    if score >= 85:
        return "#16a34a"
    if score >= 65:
        return "#d97706"
    if score >= 40:
        return "#7c3aed"
    return "#dc2626"


def dimension_frame(dimensions: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Dimension": DIMENSION_LABELS.get(item.get("dimension"), item.get("dimension")),
                "Score": item.get("score", 0),
                "Confidence": item.get("confidence", 0),
                "Explanation": item.get("explanation", ""),
            }
            for item in dimensions
        ]
    )


# ---------------------------------------------------------------------------
# Projects and providers
# ---------------------------------------------------------------------------
def get_projects() -> list[dict]:
    data = api_get("/api/projects") or {}
    return data.get("projects", [])


def project_selector(include_all: bool = False, key: str = "project_id") -> str | None:
    projects = get_projects()
    if not projects:
        return None
    ids = [project["project_id"] for project in projects]
    if include_all:
        ids = ["all"] + ids
    if st.session_state.get(key) not in ids:
        st.session_state[key] = ids[0]
    names = {p["project_id"]: p["name"] for p in projects}
    names["all"] = "All projects"
    selected = st.sidebar.selectbox(
        "Workspace / project",
        ids,
        format_func=lambda value: names.get(value, value),
        key=key,
        help="Projects group audit history and may restrict the active policy catalogue.",
    )
    if selected != "all":
        project = next((p for p in projects if p["project_id"] == selected), None)
        if project and project.get("policy_ids"):
            st.sidebar.caption(f"Policies: {', '.join(project['policy_ids'])}")
    return None if selected == "all" else selected


def active_project_id() -> str | None:
    value = st.session_state.get("project_id")
    return None if value == "all" else value


def provider_choices() -> list[str]:
    data = api_get("/api/providers") or {}
    return [p for p in data.get("available", []) if p != "offline"] or [
        "openai",
        "anthropic",
        "openrouter",
        "custom",
        "ollama",
    ]


def provider_metadata() -> dict:
    data = api_get("/api/providers") or {}
    return data.get("metadata", {})


def provider_status_frame(connections: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Provider": row.get("label") or row["provider"],
                "Configured": bool(row.get("configured")),
                "Key saved": bool(row.get("api_key_set")),
                "Key hint": row.get("api_key_hint") or "—",
                "Base URL": row.get("base_url") or row.get("default_base_url") or "—",
                "Model": row.get("model") or "—",
                "Last test": (
                    "passed"
                    if row.get("last_test_ok") is True
                    else "failed"
                    if row.get("last_test_ok") is False
                    else "not run"
                ),
            }
            for row in connections
        ]
    )


def configured_providers() -> list[str]:
    data = api_get("/api/providers") or {}
    configured = {
        name
        for name, ready in (data.get("env_configured") or {}).items()
        if ready and name != "offline"
    }
    for connection in (data.get("connection_profiles") or []):
        if connection.get("configured") or connection.get("api_key_set"):
            configured.add(connection["provider"])
    return [p for p in provider_choices() if p in configured]


def ordered_providers() -> list[str]:
    """Configured providers first so a local/Ollama setup is the obvious default."""

    configured = configured_providers()
    return configured + [name for name in provider_choices() if name not in configured]


def parse_json(text: str, default: Any) -> Any:
    if not text or not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON") from exc


def safe_csv(df: pd.DataFrame) -> str:
    text = df.to_csv(index=False)
    # Spreadsheet formula injection protection for client-side downloads.
    lines = text.splitlines()
    safe_lines = []
    for idx, line in enumerate(lines):
        if idx == 0:
            safe_lines.append(line)
            continue
        cells = line.split(",")
        cells = [
            ("'" + cell) if cell[:1] in ("=", "+", "-", "@", "|") else cell for cell in cells
        ]
        safe_lines.append(",".join(cells))
    return "\n".join(safe_lines)


# ---------------------------------------------------------------------------
# Audit result renderer
# ---------------------------------------------------------------------------
def render_audit_result(
    result: dict,
    audit_id: int | None = None,
    *,
    show_download: bool = True,
    compact: bool = False,
) -> None:
    if not result:
        empty_state("No result", "Run an audit to see the evidence-driven result.")
        return
    score = int(result.get("overall_score", 0))
    decision = result.get("decision", "Human Review Required")
    escalation = result.get("escalation") or {}
    top = st.columns([1.1, 2.2, 1.2, 1.2])
    with top[0]:
        st.markdown(
            f"""<div class="score-ring"><div class="label">Quality score</div>
            <div class="value" style="color:{score_color(score)}">{score}<span style="font-size:1rem;color:#94a3b8">/100</span></div>
            <div class="muted">weighted rubric</div></div>""",
            unsafe_allow_html=True,
        )
    with top[1]:
        st.markdown("**Decision**")
        st.markdown(decision_badge(decision), unsafe_allow_html=True)
        st.markdown(
            f"<div class='muted' style='margin-top:9px'>{html.escape(result.get('decision_reason',''))}</div>",
            unsafe_allow_html=True,
        )
        if audit_id:
            st.caption(f"Saved audit #{audit_id}")
    with top[2]:
        st.metric("Confidence", f"{float(result.get('confidence', 0)):.2f}")
        st.caption("Uncalibrated evidence indicator")
    with top[3]:
        verdict_value = str(escalation.get("verdict", "n/a"))
        verdict_label = {
            "appropriate": "OK",
            "under_escalation": "Under",
            "over_escalation": "Over",
        }.get(verdict_value, verdict_value.replace("_", " ").title())
        st.metric("Routing", verdict_label)
        st.caption(f"Expected: {escalation.get('expected', 'n/a')}")

    if result.get("hard_stop_triggered"):
        st.error(
            "**Hard stop triggered — this response must not be approved automatically.** "
            + "; ".join(result.get("hard_stop_reasons", []))
        )
    if result.get("evaluation_mode", "").endswith("fallback"):
        st.warning(
            "The model judge was unavailable and the result fell back to deterministic rules. "
            "This is not a successful LLM evaluation."
        )

    dims = result.get("dimension_scores") or []
    if dims:
        section("Dimension scores", "0 = critical failure · 2 = partial · 4 = excellent")
        frame = dimension_frame(dims)
        chart_frame = frame.sort_values("Score")
        fig = px.bar(
            chart_frame,
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
            margin=dict(l=10, r=20, t=10, b=10),
            coloraxis_showscale=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="Score (0–4)",
        )
        st.plotly_chart(fig, width="stretch")
        with st.expander("Dimension explanations and evidence", expanded=not compact):
            for item in dims:
                label = DIMENSION_LABELS.get(item.get("dimension"), item.get("dimension"))
                st.markdown(f"**{label} — {item.get('score', 0)}/4**")
                st.write(item.get("explanation", ""))
                for evidence in item.get("evidence", [])[:3]:
                    st.markdown(
                        f"<div class='policy-quote'>{html.escape(str(evidence))}</div>",
                        unsafe_allow_html=True,
                    )
                st.caption(f"Dimension confidence: {float(item.get('confidence', 0)):.2f}")

    left, right = st.columns(2)
    with left:
        section("Required actions / next steps")
        suggestions = result.get("improvement_suggestions") or []
        if suggestions:
            for suggestion in suggestions:
                st.markdown(f"- {suggestion}")
        else:
            st.caption("No specific correction identified.")
        if result.get("missing_info"):
            section("Missing information")
            for item in result["missing_info"]:
                st.markdown(f"- {item}")
    with right:
        section("Escalation intelligence")
        if escalation:
            e1, e2, e3 = st.columns(3)
            e1.markdown(f"**Expected**  \n`{escalation.get('expected', 'n/a')}`")
            e2.markdown(f"**Actual**  \n`{escalation.get('actual', 'n/a')}`")
            e3.markdown(f"**Urgency**  \n`{escalation.get('urgency', 'n/a')}`")
            verdict = escalation.get("verdict", "")
            if verdict == "under_escalation":
                st.error(f"Under-escalation: {escalation.get('reason', '')}")
            elif verdict == "over_escalation":
                st.warning(f"Over-escalation: {escalation.get('reason', '')}")
            else:
                st.success(f"Appropriate routing: {escalation.get('reason', '')}")
            for evidence in escalation.get("evidence", [])[:2]:
                st.caption(evidence)
            st.caption(
                "This workspace records a recommendation only; it never contacts a customer or performs a refund, lock, or transfer."
            )
        else:
            st.caption("No escalation decision recorded.")

    section("Policy evidence", "Only active, date-applicable policy versions are retrieved.")
    refs = result.get("policy_refs") or []
    if refs:
        for ref in refs[:5]:
            title = f"{ref.get('policy_id')} · {ref.get('section')} (v{ref.get('version')})"
            with st.expander(title):
                st.markdown(
                    f"<div class='policy-quote'>{html.escape(str(ref.get('excerpt', '')))}</div>",
                    unsafe_allow_html=True,
                )
                st.caption(f"Retrieval relevance: {float(ref.get('relevance', 0)):.2f}")
    else:
        st.caption(
            "No sufficiently relevant policy section was retrieved. Absence of evidence is not proof of a violation."
        )

    tags_left, tags_right = st.columns(2)
    with tags_left:
        section("Hallucination / unsupported claims")
        flags = result.get("hallucination_flags") or []
        if flags:
            for flag in flags[:8]:
                st.warning(flag)
        else:
            st.caption("No specific unsupported claim detected by the active checks.")
    with tags_right:
        section("Uncertainty and human-review signals")
        flags = result.get("uncertainty_flags") or []
        if flags:
            for flag in flags[:8]:
                st.info(flag)
        else:
            st.caption("No additional uncertainty flags.")
        if result.get("strengths"):
            section("Strengths")
            for strength in result["strengths"][:5]:
                st.markdown(f"- {strength}")

    if show_download:
        st.download_button(
            "Download this audit (JSON)",
            json.dumps(result, indent=2),
            file_name=f"audit-{audit_id or 'result'}.json",
            mime="application/json",
        )


def load_audit(audit_id: int) -> dict | None:
    return api_get(f"/api/audits/{audit_id}")


def selected_project() -> dict | None:
    value = st.session_state.get("project_id")
    if not value:
        return None
    return next((p for p in get_projects() if p["project_id"] == value), None)


def prefill_single_audit(case: dict) -> None:
    """Put a benchmark/custom case into the Single Audit widgets.

    Widget keys are only written while the Single Audit page is not mounted, which
    avoids Streamlit's "cannot modify after instantiation" error.
    """

    facts = case.get("facts") or {}
    actions = case.get("expected_actions") or []
    st.session_state["sa_case_id"] = case.get("case_id") or ""
    st.session_state["sa_category"] = case.get("category") or ""
    st.session_state["sa_message"] = case.get("customer_message") or ""
    st.session_state["sa_response"] = case.get("candidate_response") or ""
    st.session_state["sa_facts"] = json.dumps(facts, indent=2, ensure_ascii=False)
    st.session_state["sa_actions"] = "; ".join(actions)
    st.session_state["sa_escalation"] = case.get("expected_escalation") or ""
    st.session_state["sa_severity"] = case.get("severity") or "medium"
    st.session_state["sa_policies"] = list(case.get("policy_ids") or [])


def reset_single_audit() -> None:
    for key in (
        "sa_case_id",
        "sa_category",
        "sa_message",
        "sa_response",
        "sa_facts",
        "sa_actions",
        "sa_escalation",
        "sa_severity",
        "sa_policies",
        "sa_generated",
        "single_result",
        "single_audit_id",
    ):
        st.session_state.pop(key, None)


def render_synthetic_notice(summary: dict) -> None:
    if summary.get("contains_synthetic_demo_data"):
        st.info(
            f"This workspace includes {summary.get('synthetic_demo_count', 0)} seeded synthetic "
            "demo audits. Metrics include them and are not operational outcomes."
        )
