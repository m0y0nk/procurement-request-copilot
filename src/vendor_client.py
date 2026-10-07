from __future__ import annotations

import os
from urllib.parse import quote
import requests


def get_vendor_risk(vendor_name: str, timeout_seconds: float = 3.0) -> dict:
    """Low-level API client. Decide yourself whether/how this becomes an agent tool."""
    base_url = os.getenv("VENDOR_RISK_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    url = f"{base_url}/vendor-risk/{quote(vendor_name, safe='')}"
    response = requests.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.json()
