"""Workspace, provider, rubric, and data-management settings."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ..ui import (
    api_delete,
    api_get,
    api_post,
    api_put,
    empty_state,
    get_projects,
    hero,
    provider_metadata,
    provider_status_frame,
    section,
    selected_project,
    show_error,
)


def _project_section() -> None:
    section(
        "Workspaces",
        "A workspace groups audit history and can restrict the active policy catalogue. It is "
        "a local policy profile, not a multi-tenant authentication boundary.",
    )
    projects = get_projects()
    policies = api_get("/api/policies/") or []
    policy_ids = [policy["policy_id"] for policy in policies]
    if projects:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Name": project["name"],
                        "ID": project["project_id"],
                        "Audits": project.get("audit_count", 0),
                        "Policies": ", ".join(project.get("policy_ids") or [])
                        or "All active",
                        "Default": project.get("is_default"),
                    }
                    for project in projects
                ]
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.warning("No workspaces were returned. The default workspace is created on API startup.")

    create_tab, edit_tab = st.tabs(["Create workspace", "Edit / delete workspace"])
    with create_tab:
        with st.form("create_project"):
            new_id = st.text_input(
                "Workspace ID", placeholder="support-eu", key="project_new_id"
            )
            new_name = st.text_input(
                "Display name", placeholder="EU Support", key="project_new_name"
            )
            new_description = st.text_area(
                "Description", key="project_new_description", height=80
            )
            new_policies = st.multiselect(
                "Policy scope (empty = all active policies)",
                policy_ids,
                key="project_new_policies",
            )
            submitted = st.form_submit_button("Create workspace", type="primary")
        if submitted:
            response = api_post(
                "/api/projects",
                {
                    "project_id": new_id.strip(),
                    "name": new_name.strip(),
                    "description": new_description,
                    "policy_ids": new_policies,
                },
            )
            if response is not None and response.ok:
                st.success("Workspace created.")
                st.session_state.pop("project_id", None)
                st.rerun()
            elif response is not None:
                show_error(response, "Workspace creation failed")

    with edit_tab:
        if projects:
            selection = st.selectbox(
                "Workspace",
                [project["project_id"] for project in projects],
                format_func=lambda value: next(
                    project["name"] for project in projects if project["project_id"] == value
                ),
                key="project_edit_id",
            )
            editing = next(
                project for project in projects if project["project_id"] == selection
            )
            with st.form("edit_project"):
                name = st.text_input(
                    "Display name",
                    value=editing["name"],
                    key=f"project_edit_name_{selection}",
                )
                description = st.text_area(
                    "Description",
                    value=editing.get("description") or "",
                    key=f"project_edit_description_{selection}",
                    height=80,
                )
                scoped = st.multiselect(
                    "Policy scope (empty = all active policies)",
                    policy_ids,
                    default=[
                        item for item in editing.get("policy_ids") or [] if item in policy_ids
                    ],
                    key=f"project_edit_policies_{selection}",
                )
                update = st.form_submit_button("Save workspace", type="primary")
            if update:
                response = api_put(
                    f"/api/projects/{selection}",
                    {
                        "name": name.strip(),
                        "description": description,
                        "policy_ids": scoped,
                    },
                )
                if response is not None and response.ok:
                    st.success("Workspace updated.")
                    st.rerun()
                elif response is not None:
                    show_error(response, "Workspace update failed")
            if editing.get("is_default"):
                st.caption("The default workspace cannot be deleted.")
            else:
                confirm = st.checkbox(
                    "I understand this cannot be undone.",
                    key=f"project_delete_confirm_{selection}",
                )
                if st.button(
                    "Delete workspace",
                    type="secondary",
                    disabled=not confirm,
                    key=f"project_delete_{selection}",
                ):
                    response = api_delete(f"/api/projects/{selection}")
                    if response is not None and response.ok:
                        st.success("Workspace deleted.")
                        st.session_state.pop("project_id", None)
                        st.rerun()
                    elif response is not None:
                        show_error(response, "Workspace deletion failed")


def _provider_section() -> None:
    section(
        "Provider connections",
        "Keys are encrypted at rest on the server, never returned to this UI, and never stored "
        "in audit results. Environment variables remain supported for shared deployments.",
    )
    current = api_get("/api/providers")
    if not current:
        empty_state("Provider status unavailable", "Start the API to configure providers.")
        return
    connections = {row["provider"]: row for row in current.get("connection_profiles", [])}
    metadata = provider_metadata()
    names = [
        name
        for name in current.get("available", [])
        if name != "offline" and name in metadata
    ]
    st.dataframe(
        provider_status_frame(list(connections.values())), width="stretch", hide_index=True
    )
    st.caption(current.get("credential_notice", ""))

    tabs = st.tabs([metadata[name].get("label", name) for name in names])
    for tab, name in zip(tabs, names, strict=True):
        with tab:
            connection = connections.get(name, {})
            meta = metadata.get(name, {})
            status = []
            if connection.get("api_key_set"):
                status.append(f"encrypted key {connection.get('api_key_hint')}")
            elif connection.get("env_configured"):
                status.append("environment key")
            if connection.get("last_test_ok") is True:
                status.append("last test passed")
            elif connection.get("last_test_ok") is False:
                status.append("last test failed")
            st.caption(
                ("Configured: " + ", ".join(status)) if status else "Not configured yet."
            )
            if meta.get("docs"):
                st.markdown(f"[Provider key documentation]({meta['docs']})")
            with st.form(f"provider_form_{name}"):
                base_url = st.text_input(
                    "Base URL",
                    value=connection.get("base_url") or meta.get("default_base_url") or "",
                    key=f"provider_base_{name}",
                    help="For local Ollama use http://localhost:11434/v1",
                )
                model = st.text_input(
                    "Default model",
                    value=connection.get("model") or "",
                    placeholder=meta.get("model_placeholder", ""),
                    key=f"provider_model_{name}",
                )
                api_key = st.text_input(
                    "API key",
                    type="password",
                    key=f"provider_key_{name}",
                    placeholder=(
                        "Leave blank to keep the saved key"
                        if connection.get("api_key_set")
                        else "Not required for local Ollama"
                    ),
                )
                c1, c2, c3 = st.columns(3)
                timeout = c1.number_input(
                    "Timeout (s)",
                    min_value=5,
                    max_value=300,
                    value=int(connection.get("timeout") or 30),
                    key=f"provider_timeout_{name}",
                )
                temperature = c2.number_input(
                    "Temperature",
                    min_value=0.0,
                    max_value=2.0,
                    value=float(connection.get("temperature") or 0.2),
                    step=0.1,
                    key=f"provider_temp_{name}",
                )
                max_tokens = c3.number_input(
                    "Max tokens",
                    min_value=100,
                    max_value=16000,
                    value=int(connection.get("max_tokens") or 1500),
                    step=100,
                    key=f"provider_tokens_{name}",
                )
                with st.expander("Advanced: headers and price schedule"):
                    headers_raw = st.text_area(
                        "Extra headers JSON",
                        value=json.dumps(connection.get("headers") or {}, indent=2),
                        height=90,
                        key=f"provider_headers_{name}",
                    )
                    p1, p2 = st.columns(2)
                    pricing = connection.get("pricing") or {}
                    input_price = p1.number_input(
                        "Input USD per 1M tokens",
                        min_value=0.0,
                        value=float(pricing.get("input_usd_per_1m") or 0.0),
                        step=0.01,
                        key=f"provider_price_in_{name}",
                    )
                    output_price = p2.number_input(
                        "Output USD per 1M tokens",
                        min_value=0.0,
                        value=float(pricing.get("output_usd_per_1m") or 0.0),
                        step=0.01,
                        key=f"provider_price_out_{name}",
                    )
                    st.caption(
                        "Prices are operator-supplied and only used for estimates. No price "
                        "schedule is bundled because provider pricing changes."
                    )
                b1, b2 = st.columns(2)
                save = b1.form_submit_button("Save connection", type="primary")
                save_test = b2.form_submit_button("Save and test")

            if save or save_test:
                try:
                    headers = json.loads(headers_raw) if headers_raw.strip() else {}
                    if not isinstance(headers, dict):
                        raise ValueError("Headers must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    st.error(f"Headers must be valid JSON: {exc}")
                else:
                    payload = {
                        "base_url": base_url,
                        "model": model,
                        "timeout": int(timeout),
                        "temperature": float(temperature),
                        "max_tokens": int(max_tokens),
                        "headers": headers,
                        "pricing": {
                            "input_usd_per_1m": float(input_price),
                            "output_usd_per_1m": float(output_price),
                        },
                    }
                    if api_key.strip():
                        payload["api_key"] = api_key.strip()
                    response = api_put(f"/api/providers/connections/{name}", payload)
                    if response is not None and response.ok:
                        if save_test:
                            tested = api_post(
                                "/api/providers/test",
                                {"provider": name, "model": model or None},
                            )
                            if tested is not None and tested.ok:
                                result = tested.json()
                                if result.get("ok"):
                                    st.success(
                                        f"{meta.get('label', name)} responded successfully "
                                        f"with model {result.get('model')}."
                                    )
                                else:
                                    st.error(result.get("error", "Connection test failed."))
                            elif tested is not None:
                                show_error(tested, "Connection test failed")
                        else:
                            st.success("Connection saved.")
                        st.rerun()
                    elif response is not None:
                        show_error(response, "Could not save provider connection")

            with st.expander("Test, discover models, or delete this connection"):
                t1, t2 = st.columns(2)
                if t1.button("Test saved connection", key=f"provider_test_{name}"):
                    tested = api_post(
                        "/api/providers/test",
                        {"provider": name, "model": model or None},
                    )
                    if tested is not None and tested.ok:
                        result = tested.json()
                        if result.get("ok"):
                            st.success(
                                f"Connection works; model {result.get('model')}."
                            )
                        else:
                            st.error(result.get("error", "Connection test failed."))
                    elif tested is not None:
                        show_error(tested, "Connection test failed")
                if t2.button("Discover models", key=f"provider_discover_{name}"):
                    discovered = api_get(
                        "/api/providers/models", params={"provider": name}
                    )
                    if discovered and discovered.get("models"):
                        st.write(discovered["models"])
                    elif discovered:
                        st.warning(
                            discovered.get(
                                "error", "No models returned; verify the connection."
                            )
                        )
                confirm = st.checkbox(
                    "Confirm removal of the saved key and settings.",
                    key=f"provider_delete_confirm_{name}",
                )
                if st.button(
                    "Delete saved connection",
                    type="secondary",
                    disabled=not (connection.get("configured") and confirm),
                    key=f"provider_delete_{name}",
                ):
                    response = api_delete(f"/api/providers/connections/{name}")
                    if response is not None and response.ok:
                        st.success("Saved connection deleted. Environment settings, if any, still apply.")
                        st.rerun()
                    elif response is not None:
                        show_error(response, "Could not delete connection")


def _usage_section() -> None:
    usage = api_get("/api/providers/usage")
    if not usage:
        return
    section("Provider budget", "Conservative estimate; actual provider billing may differ.")
    c1, c2, c3 = st.columns(3)
    c1.metric(
        "Reserved tokens today",
        f"{usage.get('estimated_tokens_reserved', 0):,}",
        f"budget {usage.get('daily_token_budget', 0):,}",
    )
    c2.metric("Provider attempts", usage.get("calls", 0))
    c3.metric(
        "Estimated cost",
        f"${usage['estimated_cost_usd']:.4f}"
        if usage.get("estimated_cost_usd") is not None
        else "Not set",
        help="Set a price schedule on the provider connection to estimate spend.",
    )
    st.caption(usage.get("cost_estimate_note", ""))


def _rubric_section() -> None:
    section(
        "Rubric weights and thresholds",
        "Weights are normalized at evaluation time. Each audit stores a snapshot of the "
        "rubric and thresholds used.",
    )
    config = api_get("/api/settings/evaluation")
    if not config:
        empty_state("Rubric unavailable", "Start the API to edit evaluation settings.")
        return
    dimensions = config.get("dimensions", {})
    weights = config.get("weights", {})
    thresholds = config.get("thresholds", {})
    with st.form("evaluation_config_form"):
        new_weights = {}
        columns = st.columns(3)
        for index, (name, value) in enumerate(weights.items()):
            new_weights[name] = columns[index % 3].slider(
                dimensions.get(name, name),
                0.0,
                1.0,
                float(value),
                0.01,
                key=f"weight_{name}",
            )
        st.caption(
            "Zero disables a dimension's contribution to the composite score; hard-stop "
            "rules and uncertainty flags remain active."
        )
        t1, t2, t3 = st.columns(3)
        approve = t1.number_input(
            "Approve at or above", 0, 100, int(thresholds.get("approve", 85)), key="th_approve"
        )
        revision = t2.number_input(
            "Needs Revision at or above",
            0,
            100,
            int(thresholds.get("revision", 65)),
            key="th_revision",
        )
        human = t3.number_input(
            "Human Review at or above",
            0,
            100,
            int(thresholds.get("human_review", 40)),
            key="th_human",
        )
        save = st.form_submit_button("Save evaluation settings", type="primary")
    if save:
        response = api_put(
            "/api/settings/evaluation",
            {
                "weights": new_weights,
                "thresholds": {
                    "approve": int(approve),
                    "revision": int(revision),
                    "human_review": int(human),
                },
            },
        )
        if response is not None and response.ok:
            st.success("Evaluation settings saved.")
        elif response is not None:
            show_error(response, "Invalid evaluation settings")


def _security_section() -> None:
    section("Security, privacy, and data management")
    st.markdown(
        """
- **Deterministic/offline mode** makes no external model calls.
- **Hybrid/LLM mode** sends only the current case, facts, expected actions/escalation, and retrieved policy excerpts to the selected judge provider.
- **Provider keys** are encrypted at rest with a server-side key at `data/.provider_key` (file permissions `0600`). This is encryption at rest, not a hardware security module. Restrict filesystem access and rotate keys if exposed.
- **Environment variables** (`OPENAI_API_KEY`, etc.) are recommended for shared deployments. A saved connection overrides only fields you explicitly save.
- **Authentication** is optional and off by default for local single-user use. Set `API_ACCESS_TOKEN` to require a bearer token; do not expose an unauthenticated instance to the internet.
- **Data retention:** audit text and reviews live in local SQLite until deleted. Avoid unnecessary PII.
- **Exports** exclude raw customer text and neutralise spreadsheet formula prefixes.
- **The auditor never performs** refunds, account locks, customer contact, or case transfers.
"""
    )
    st.markdown("**Delete one saved audit and its linked human reviews**")
    delete_id = st.number_input(
        "Audit ID", min_value=1, step=1, key="delete_audit_id"
    )
    confirm = st.checkbox(
        "I understand deletion cannot be undone.", key="delete_audit_confirm"
    )
    if st.button(
        "Delete audit",
        type="secondary",
        disabled=not confirm,
        key="delete_audit_button",
    ):
        response = api_delete(f"/api/audits/{int(delete_id)}")
        if response is not None and response.ok:
            st.success(f"Deleted audit {delete_id} and linked reviews.")
        elif response is not None:
            show_error(response, "Delete failed")


def render() -> None:
    hero(
        "Settings",
        "Workspaces, encrypted provider connections, model discovery, rubric thresholds, "
        "budget visibility, and data controls.",
        kicker="OPERATIONS",
    )
    project = selected_project()
    if project:
        st.caption(
            f"Active workspace: **{project['name']}** (`{project['project_id']}`). "
            "Changing the workspace in the sidebar scopes new audits."
        )
    tabs = st.tabs(
        ["Workspaces", "Providers & models", "Rubric", "Security & data"]
    )
    with tabs[0]:
        _project_section()
    with tabs[1]:
        _provider_section()
        st.divider()
        _usage_section()
    with tabs[2]:
        _rubric_section()
    with tabs[3]:
        _security_section()
    st.divider()
    health = api_get("/api/health") or {}
    st.caption(
        f"API status: {health.get('status', 'unknown')} · version {health.get('version', '—')} · "
        "Streamlit UI v0.2.0"
    )
