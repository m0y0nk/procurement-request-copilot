from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE_URL = os.getenv("PROCUREMENT_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 30

st.set_page_config(page_title="Procurement Request Copilot", layout="wide")
st.title("AI Procurement Request Copilot")
st.caption("Recommendations support review. A human owns every purchasing decision.")


def api_get(path: str) -> requests.Response:
    response = requests.get(
        f"{API_BASE_URL}{path}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def api_post(path: str, payload: dict[str, object]) -> requests.Response:
    response = requests.post(
        f"{API_BASE_URL}{path}",
        json=payload,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def sync_analysis_scope(scope: str) -> None:
    if st.session_state.get("active_analysis_scope") != scope:
        st.session_state.pop("analysis_result", None)
        st.session_state["active_analysis_scope"] = scope


try:
    samples = api_get("/api/requests").json()
except (requests.RequestException, ValueError) as exc:
    st.error(f"Procurement API is unavailable: {exc}")
    st.stop()

request_mode = st.sidebar.radio("Request source", ["Sample request", "New request"])
architecture_label = st.sidebar.selectbox(
    "Architecture",
    ["A — Single agent", "B — Analyst + Reviewer"],
)
architecture = "A" if architecture_label.startswith("A —") else "B"

if request_mode == "Sample request":
    sample_by_id = {request["request_id"]: request for request in samples}
    request_id = st.sidebar.selectbox(
        "Sample",
        list(sample_by_id),
        format_func=lambda key: (
            f"{key} — {sample_by_id[key]['product_name']}"
        ),
    )
    request_data = sample_by_id[request_id]
    active_analysis_scope = f"sample:{request_id}:{architecture}"
    sync_analysis_scope(active_analysis_scope)
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("Purchase request")
        st.json(request_data)
    with right:
        st.subheader("Analysis")
        if st.button("Run analysis", type="primary", use_container_width=True):
            try:
                result = api_post(
                    "/api/analyze",
                    {"request_id": request_id, "architecture": architecture},
                ).json()
            except (requests.RequestException, ValueError) as exc:
                st.error(f"Analysis failed: {exc}")
            else:
                st.session_state["analysis_result"] = result
                st.session_state["analysis_request_id"] = request_id
else:
    active_analysis_scope = f"new:{architecture}"
    sync_analysis_scope(active_analysis_scope)
    st.subheader("New purchase request")
    with st.form("new_request"):
        requester_id = st.text_input("Employee ID", value="E001")
        description = st.text_area(
            "What do you need?",
            placeholder="Describe the capability and business purpose.",
        )
        product_name = st.text_input("Product name", value="")
        vendor_name = st.text_input("Vendor name", value="")
        category = st.text_input("Category", value="")
        annual_cost = st.text_input("Estimated annual cost in USD", value="")
        user_count_text = st.text_input("Number of users", value="")
        data_access_level = st.selectbox(
            "Data access level",
            [
                "unknown",
                "none",
                "internal_documents",
                "internal_marketing",
                "confidential_documents",
                "source_code",
                "production_telemetry",
                "employee_pii",
                "customer_pii",
                "credentials",
            ],
        )
        submitted = st.form_submit_button(
            "Run analysis",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        st.session_state.pop("analysis_result", None)
        try:
            user_count = int(user_count_text) if user_count_text.strip() else None
        except ValueError:
            st.error("Number of users must be a whole number.")
        else:
            request_payload: dict[str, object] = {
                "requester_id": requester_id.strip(),
                "product_name": product_name.strip(),
                "vendor_name": vendor_name.strip(),
                "category": category.strip(),
                "annual_cost_usd": annual_cost.strip() or None,
                "user_count": user_count,
                "business_justification": description.strip(),
                "data_access_level": data_access_level,
            }
            try:
                result = api_post(
                    "/api/analyze",
                    {
                        "request": request_payload,
                        "description": description,
                        "architecture": architecture,
                    },
                ).json()
            except (requests.RequestException, ValueError) as exc:
                st.error(f"Analysis failed: {exc}")
            else:
                st.session_state["analysis_result"] = result
                st.session_state["analysis_request_id"] = result["decision"]["request_id"]

result = st.session_state.get("analysis_result")
if result:
    decision = result["decision"]
    trace = result["trace"]
    st.divider()
    st.subheader("Recommendation")
    summary, approval_col = st.columns([1, 1], gap="large")
    with summary:
        st.metric("Recommended action", decision["recommendation"])
        st.write(decision["next_step"])
        st.write(f"Rule floor: `{decision['rule_floor']}`")
        st.write(f"Human review: {decision['human_review']['reason']}")
        if decision.get("failure_detail"):
            st.error(decision["failure_detail"])
    with approval_col:
        st.markdown("**Approvals required**")
        if decision["approvals_required"]:
            for approval in decision["approvals_required"]:
                st.write(
                    f"{approval['role']} — {approval['reason']} "
                    f"(`{approval['rule_id']}`)"
                )
        else:
            st.write("No specialist or spend-tier approver was computed.")
        st.markdown("**Missing information**")
        st.write(", ".join(decision["missing_information"]) or "None")

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Evidence**")
        if decision["evidence"]:
            for item in decision["evidence"]:
                st.write(
                    f"- {item['claim']} "
                    f"Source: `{item['source_tool']}`; "
                    f"record: `{item['record_ref']}`."
                )
        else:
            st.write("No grounded evidence was returned.")
    with right:
        st.markdown("**Risk flags**")
        if decision["risk_flags"]:
            for flag in decision["risk_flags"]:
                st.write(f"- **{flag['severity']} — {flag['code']}**: {flag['detail']}")
        else:
            st.write("No risk flags.")

    unavailable = [
        call for call in trace.get("tool_calls", [])
        if call.get("status") == "unavailable"
    ]
    if unavailable:
        st.markdown("**Unavailable evidence**")
        for call in unavailable:
            output = call.get("output", {})
            reason = output.get("reason") if isinstance(output, dict) else None
            st.error(
                f"{call['tool_name']} — unavailable. "
                f"{reason or 'The tool did not provide a reason.'}"
            )

    with st.expander("Run metadata and trace"):
        st.json(
            {
                "architecture": decision["meta"]["architecture"],
                "llm_calls": decision["meta"]["llm_calls"],
                "tool_calls": decision["meta"]["tool_calls"],
                "latency_ms": decision["meta"]["latency_ms"],
                "tool_call_trace": trace.get("tool_calls", []),
                "token_usage": trace.get("token_usage", {}),
            }
        )

    st.subheader("Reviewer action")
    with st.form("reviewer_action"):
        action = st.selectbox(
            "Action",
            ["accept", "reject", "request_info"],
            format_func={
                "accept": "Accept recommendation",
                "reject": "Reject request",
                "request_info": "Request more information",
            }.get,
        )
        note = st.text_area("Required reviewer note")
        reviewer = st.text_input("Reviewer", value="Procurement reviewer")
        saved = st.form_submit_button("Save decision")
    if saved:
        try:
            saved_decision = api_post(
                "/api/decisions",
                {
                    "request_id": decision["request_id"],
                    "action": action,
                    "note": note,
                    "reviewer": reviewer,
                    "recommendation": decision["recommendation"],
                },
            ).json()
        except (requests.RequestException, ValueError) as exc:
            st.error(f"Reviewer decision was not saved: {exc}")
        else:
            st.success(
                f"Decision saved as {saved_decision['action']} "
                f"({saved_decision['decision_id']})."
            )

    with st.expander("Prior reviewer decisions"):
        try:
            prior = api_get(
                f"/api/decisions?request_id={decision['request_id']}"
            ).json()
        except (requests.RequestException, ValueError) as exc:
            st.error(f"Could not load reviewer history: {exc}")
        else:
            st.json(prior)
