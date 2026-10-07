from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.solution import handle_request

ROOT = Path(__file__).resolve().parent
REQUESTS = json.loads((ROOT / "data" / "requests.json").read_text(encoding="utf-8"))
BY_ID = {r["request_id"]: r for r in REQUESTS}

st.set_page_config(page_title="Procurement Request Copilot", layout="wide")
st.title("AI Procurement Request Copilot")
st.caption("Starter UI only - replace or extend it as part of your product design.")

request_id = st.sidebar.selectbox(
    "Request",
    list(BY_ID.keys()),
    format_func=lambda rid: f"{rid} - {BY_ID[rid]['product_name']}",
)
architecture = st.sidebar.radio("Architecture", ["single", "staged"], horizontal=True)
req = BY_ID[request_id]

left, right = st.columns([1.05, 0.95], gap="large")
with left:
    st.subheader("Purchase request")
    st.json(req)

with right:
    st.subheader("Copilot recommendation")
    if st.button("Run analysis", type="primary", use_container_width=True):
        try:
            result = handle_request(request_id, architecture=architecture)
        except NotImplementedError as exc:
            st.info(str(exc))
        except Exception as exc:
            st.exception(exc)
        else:
            payload = result.model_dump() if hasattr(result, "model_dump") else result
            st.json(payload)
    else:
        st.info("Connect this panel to your implementation in `src/solution.py`.")

st.divider()
st.caption("Important: recommendations are advisory. Human approval remains required for purchasing decisions.")
