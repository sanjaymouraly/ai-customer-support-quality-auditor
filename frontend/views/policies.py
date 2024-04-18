"""Policy catalogue, versioning, retrieval and ingestion."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..ui import (
    api_get,
    api_post,
    empty_state,
    hero,
    section,
    show_error,
)


def _policy_detail(policies: list[dict]) -> None:
    selection = st.selectbox(
        "View policy detail",
        [policy["policy_id"] for policy in policies],
        key="policy_detail_id",
    )
    if not selection:
        return
    detail = api_get(f"/api/policies/{selection}")
    if not detail:
        st.error("Policy detail could not be loaded.")
        return
    st.subheader(f"{detail['title']} (v{detail['version']})")
    meta = st.columns(4)
    meta[0].metric("Policy ID", detail["policy_id"])
    meta[1].metric("Version", detail["version"])
    meta[2].metric("Status", detail["status"])
    meta[3].metric("Effective", detail["effective_date"])
    for section_item in detail.get("sections", []):
        with st.expander(f"{section_item['section_id']} — {section_item['title']}"):
            st.write(section_item["content"])
            st.caption(
                "Keywords: " + ", ".join(section_item.get("keywords") or [])
                if section_item.get("keywords")
                else "No retrieval keywords."
            )

    versions = api_get(f"/api/policies/{selection}/versions") or []
    if versions:
        section("Version history", "Only one version per policy is active at a time.")
        st.dataframe(pd.DataFrame(versions), width="stretch", hide_index=True)
        names = [version["version"] for version in versions]
        c1, c2 = st.columns(2)
        left = c1.selectbox("Compare version A", names, key="policy_compare_left")
        right = c2.selectbox(
            "Compare version B",
            names,
            index=min(1, len(names) - 1),
            key="policy_compare_right",
        )
        if st.button("Compare versions", key="policy_compare_button"):
            if left == right:
                st.info("Choose two different versions.")
            else:
                diff = api_get(
                    f"/api/policies/{selection}/compare",
                    params={"left": left, "right": right},
                )
                if diff:
                    st.json(diff)
        active = st.selectbox("Set active version", names, key="policy_activate_version")
        if st.button("Activate selected version", key="policy_activate_button"):
            response = api_post(f"/api/policies/{selection}/activate/{active}", {})
            if response is not None and response.ok:
                st.success(f"Active version is now {active}.")
                st.rerun()
            elif response is not None:
                show_error(response, "Activation failed")


def _import_panel() -> None:
    section("Import a policy", "Markdown, text, JSON, or PDF. Uploads are size-limited and type-checked.")
    with st.form("policy_upload"):
        c1, c2 = st.columns(2)
        title = c1.text_input("Title", placeholder="Refund Policy")
        policy_id = c2.text_input("Policy ID", placeholder="refund_policy")
        c3, c4, c5 = st.columns(3)
        category = c3.text_input("Category", placeholder="refund")
        version = c4.text_input("Version", value="1.0")
        effective = c5.text_input("Effective date", value="2024-01-01")
        uploaded = st.file_uploader(
            "Policy file", type=["md", "txt", "json", "pdf"], key="policy_upload_file"
        )
        submitted = st.form_submit_button("Import file")
    if submitted:
        if not uploaded:
            st.error("Choose a policy file.")
        elif not title.strip() or not policy_id.strip() or not category.strip():
            st.error("Title, policy ID, and category are required.")
        else:
            files = {
                "file": (
                    uploaded.name,
                    uploaded.getvalue(),
                    uploaded.type or "application/octet-stream",
                )
            }
            response = api_post(
                "/api/policies/ingest",
                {
                    "title": title,
                    "policy_id": policy_id,
                    "category": category,
                    "version": version,
                    "effective_date": effective,
                },
                files=files,
                timeout=120,
            )
            if response is not None and response.ok:
                st.success(f"Ingested {response.json()}")
            elif response is not None:
                show_error(response, "Policy import failed")

    with st.expander("Ingest policy text directly"):
        with st.form("policy_text_upload"):
            text_id = st.text_input("Policy ID", key="policy_text_id")
            text_title = st.text_input("Title", key="policy_text_title")
            text_category = st.text_input("Category", key="policy_text_category")
            text_version = st.text_input("Version", value="1.0", key="policy_text_version")
            text_date = st.text_input(
                "Effective date", value="2024-01-01", key="policy_text_date"
            )
            content = st.text_area(
                "Markdown content (use `##` for sections)",
                height=220,
                key="policy_text_content",
            )
            text_submit = st.form_submit_button("Ingest text")
        if text_submit:
            if not text_id.strip() or not content.strip():
                st.error("Policy ID and content are required.")
            else:
                response = api_post(
                    "/api/policies/ingest/text",
                    {
                        "policy_id": text_id,
                        "title": text_title or text_id,
                        "category": text_category or "general",
                        "version": text_version,
                        "effective_date": text_date,
                        "content": content,
                    },
                )
                if response is not None and response.ok:
                    st.success("Policy text ingested.")
                    st.rerun()
                elif response is not None:
                    show_error(response, "Policy text ingestion failed")


def _retrieval_probe() -> None:
    section("Retrieval probe", "Test which policy sections would be cited for a query.")
    with st.form("policy_retrieval"):
        query = st.text_area(
            "Query",
            value="Customer asks for a refund outside the 30 day window",
            height=90,
            key="policy_probe_query",
        )
        top_k = st.slider("Sections", 1, 10, 5, key="policy_probe_top_k")
        run = st.form_submit_button("Retrieve")
    if run:
        if not query.strip():
            st.error("Enter a query.")
        else:
            response = api_post(
                "/api/policies/retrieve", {"query": query, "top_k": top_k}
            )
            if response is not None and response.ok:
                results = response.json().get("results", [])
                if not results:
                    st.warning("No sufficiently relevant sections were found.")
                for result in results:
                    with st.expander(
                        f"{result['policy_id']} · {result['section']} "
                        f"(v{result['version']}) — relevance {result['relevance']:.2f}"
                    ):
                        st.write(result["excerpt"])
            elif response is not None:
                show_error(response, "Retrieval failed")


def render() -> None:
    hero(
        "Policy Manager",
        "Versioned policy evidence for grounded evaluation: inspect, compare, activate, "
        "import, and probe retrieval.",
        kicker="POLICY KNOWLEDGE BASE",
    )
    st.info(
        "The bundled policy documents are fictional starter examples. Replace them with "
        "approved, current company policies before operational use."
    )
    policies = api_get("/api/policies/")
    if policies is None:
        empty_state(
            "Policy catalogue unavailable", "Start the API and verify `data/policies/`."
        )
        return
    if not policies:
        empty_state("No policies", "Import a policy to make evaluations policy-grounded.")
        return
    section("Active catalogue")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "policy_id": policy["policy_id"],
                    "title": policy["title"],
                    "version": policy["version"],
                    "status": policy["status"],
                    "category": policy["category"],
                    "sections": policy["sections"],
                    "effective_date": policy["effective_date"],
                }
                for policy in policies
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    st.divider()
    _policy_detail(policies)
    st.divider()
    _import_panel()
    st.divider()
    _retrieval_probe()
