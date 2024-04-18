"""Streamlit entry point.

Run with::

    streamlit run frontend/app.py --server.address 0.0.0.0 --server.port 8501

The UI talks to the FastAPI service only; it never reads provider secrets or the database
directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from frontend.ui import (  # noqa: E402
    API_BASE,
    api_get,
    inject_css,
    project_selector,
)
from frontend.views import (  # noqa: E402
    analytics,
    batch,
    comparison,
    escalations,
    overview,
    policies,
    reviews,
    scenarios,
    settings,
    single_audit,
)

st.set_page_config(
    page_title="AI Support Auditor",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

PAGES = {
    "Overview": overview.render,
    "Single Audit": single_audit.render,
    "Batch Auditor": batch.render,
    "Scenario Explorer": scenarios.render,
    "Policy Manager": policies.render,
    "Escalation Intelligence": escalations.render,
    "Human Review": reviews.render,
    "Model Comparison": comparison.render,
    "Analytics & Reports": analytics.render,
    "Settings": settings.render,
}

st.sidebar.markdown("## 🛡️ Support Auditor")
st.sidebar.caption("Policy-grounded QA for AI support responses")

health = api_get("/api/health", timeout=3)
if not health:
    st.sidebar.error("API offline")
    st.error(
        "**The FastAPI service is not reachable.** Start it from the repository root:\n\n"
        "```bash\nuvicorn backend.app:app --host 0.0.0.0 --port 8000\n```\n\n"
        f"The UI is looking for `{API_BASE}`. Set `API_BASE_URL` if the API runs elsewhere."
    )
    st.stop()

st.sidebar.success(f"API {health.get('version', '')} online")
project_selector(include_all=False, key="project_id")
st.sidebar.divider()
page = st.sidebar.radio("Navigate", list(PAGES), key="nav")
st.sidebar.divider()
provider_info = api_get("/api/providers") or {}
configured = [
    row
    for row in provider_info.get("connection_profiles", [])
    if row.get("configured") or row.get("env_configured")
]
if configured:
    st.sidebar.caption(
        "Model providers: " + ", ".join(row["provider"] for row in configured)
    )
else:
    st.sidebar.caption("No external model provider configured — deterministic mode is ready.")
st.sidebar.caption("v0.2.0 · offline-ready · deterministic + hybrid")

PAGES[page]()
