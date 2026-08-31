"""Streamlit dashboard for Chronos.

Views:
  1. Incident List
  2. Incident Detail (classification + debate transcript + decision)
  3. Ledger Viewer with verify chain button
  4. System Status (orchestrator + broker + ledger)

The dashboard connects READ-ONLY to the orchestrator's REST API. It has no
write capability.
"""
from __future__ import annotations

import os
import streamlit as st

API = os.environ.get("CHRONOS_API_URL", "http://localhost:8080/api")

st.set_page_config(page_title="Chronos", layout="wide", initial_sidebar_state="expanded")
st.title("Chronos — Governed Incident Remediation")

page = st.sidebar.radio("View", ["Incidents", "Ledger", "System Status"])


def _get(path: str):
    import httpx
    return httpx.get(f"{API}{path}", timeout=4.0)


if page == "Incidents":
    st.header("Incidents")
    st.caption("Read-only view of the workflow state machine.")
    # In production: list incidents via GET /incidents. The current API only
    # exposes /incidents/{id}; for the demo we show a curated list.
    for incident_id in ("inc_aaaaaa", "inc_bbbbbb", "inc_abcdef"):
        r = _get(f"/incidents/{incident_id}")
        if r.status_code == 200:
            data = r.json()
            with st.expander(f"{incident_id} — state: {data['state']}", expanded=False):
                st.json(data)


elif page == "Ledger":
    st.header("Tamper-Evident Ledger")
    st.caption("Each entry's hash chains to the previous. Tampering breaks verify_chain().")
    if st.button("Verify chain"):
        r = _get("/ledger/verify")
        if r.status_code == 200:
            ok = r.json().get("ok")
            head = r.json().get("head_seq")
            if ok:
                st.success(f"chain verified (head seq={head})")
            else:
                st.error("CHAIN VERIFICATION FAILED")


elif page == "System Status":
    st.header("System Status")
    col1, col2, col3 = st.columns(3)
    with col1:
        r = _get("/healthz")
        st.metric("Orchestrator", "ok" if r.status_code == 200 else "down")
    with col2:
        st.metric("Broker", "see broker logs")
    with col3:
        r = _get("/ledger/verify")
        st.metric("Ledger", "ok" if r.json().get("ok") else "broken")

    st.divider()
    st.subheader("Demo")
    st.code(
        "curl -X POST http://localhost:8080/api/incidents \\\n"
        '  -H "Content-Type: application/json" \\\n'
        "  -d '{\"incident_id\":\"inc_demo01\",\"pipeline_id\":\"pipe_demo01\","
        "\"error_log\":\"schema drift detected in upstream payload\"}'",
        language="bash",
    )