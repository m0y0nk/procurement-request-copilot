from __future__ import annotations

import os

import requests

API_BASE_URL = os.getenv(
    "PROCUREMENT_API_BASE_URL",
    "http://127.0.0.1:8000",
).rstrip("/")
REQUEST_TIMEOUT_SECONDS = 30
ANALYSIS_TIMEOUT_SECONDS = int(
    os.getenv("PROCUREMENT_ANALYSIS_TIMEOUT_SECONDS", "600")
)

if ANALYSIS_TIMEOUT_SECONDS <= 0:
    raise ValueError("PROCUREMENT_ANALYSIS_TIMEOUT_SECONDS must be positive.")


def api_get(path: str) -> requests.Response:
    response = requests.get(
        f"{API_BASE_URL}{path}",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return response


def api_post(
    path: str,
    payload: dict[str, object],
    *,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
) -> requests.Response:
    response = requests.post(
        f"{API_BASE_URL}{path}",
        json=payload,
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return response
