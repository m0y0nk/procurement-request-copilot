from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import requests


class LLMError(RuntimeError):
    pass


class ReplayResponseMissing(LLMError):
    pass


def request_key(messages: list[dict[str, str]]) -> str:
    canonical = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def invoke(
    messages: list[dict[str, str]],
    *,
    mode: Literal["live", "replay"] | None = None,
    replay_path: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 30.0,
) -> str:
    selected_mode = mode or os.getenv("LLM_MODE", "live")
    if selected_mode not in {"live", "replay"}:
        raise ValueError("LLM_MODE must be 'live' or 'replay'.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")
    key = request_key(messages)

    if selected_mode == "replay":
        path = replay_path or Path(
            os.getenv("LLM_REPLAY_PATH", "eval/replay/responses.json")
        )
        try:
            replay = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ReplayResponseMissing(f"Replay file not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid replay JSON: {path}") from exc
        if not isinstance(replay, dict) or key not in replay:
            raise ReplayResponseMissing(f"No replay response for request hash {key}.")
        value = replay[key]
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and isinstance(value.get("content"), str):
            return value["content"]
        raise LLMError(f"Replay response for {key} must be a string or content object.")

    selected_provider = provider or os.getenv("LLM_PROVIDER", "openai")
    selected_model = model or os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME")
    selected_api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if selected_provider != "openai":
        raise LLMError(
            f"Unsupported live LLM provider {selected_provider!r}; configure openai-compatible access."
        )
    if not selected_model:
        raise LLMError("LLM_MODEL is required in live mode.")
    if not selected_api_key:
        raise LLMError("LLM_API_KEY is required in live mode.")
    endpoint = (base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    try:
        response = requests.post(
            f"{endpoint}/chat/completions",
            headers={"Authorization": f"Bearer {selected_api_key}"},
            json={"model": selected_model, "temperature": 0, "messages": messages},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"LLM request failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(content, str):
        raise LLMError("LLM response did not contain text content.")
    return content
