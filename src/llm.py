from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests


class LLMError(RuntimeError):
    pass


class ReplayResponseMissing(LLMError):
    pass


@dataclass(frozen=True)
class LLMToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: tuple[LLMToolCall, ...]
    finish_reason: str | None
    usage: dict[str, int]
    raw_message: dict[str, object]


def request_key(messages: list[dict[str, object]]) -> str:
    canonical = json.dumps(messages, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_tool_call(value: object) -> LLMToolCall:
    if not isinstance(value, dict):
        raise LLMError("LLM tool call must be an object.")
    function = value.get("function")
    if not isinstance(function, dict) or not isinstance(function.get("name"), str):
        raise LLMError("LLM tool call is missing its function name.")
    arguments = function.get("arguments", "{}")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise LLMError("LLM tool arguments are not valid JSON.") from exc
    if not isinstance(arguments, dict):
        raise LLMError("LLM tool arguments must decode to an object.")
    call_id = value.get("id")
    if not isinstance(call_id, str) or not call_id:
        raise LLMError("LLM tool call is missing its call id.")
    return LLMToolCall(id=call_id, name=function["name"], arguments=arguments)


def _response_from_message(
    message: object,
    *,
    finish_reason: object = None,
    usage: object = None,
) -> LLMResponse:
    if not isinstance(message, dict):
        raise LLMError("LLM response message must be an object.")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise LLMError("LLM response content must be text or null.")
    raw_calls = message.get("tool_calls", [])
    if not isinstance(raw_calls, list):
        raise LLMError("LLM response tool_calls must be a list.")
    parsed_calls = tuple(_parse_tool_call(call) for call in raw_calls)
    normalized_usage: dict[str, int] = {}
    if isinstance(usage, dict):
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and value >= 0:
                normalized_usage[key] = value
    return LLMResponse(
        content=content,
        tool_calls=parsed_calls,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        usage=normalized_usage,
        raw_message=message,
    )


def invoke_chat(
    messages: list[dict[str, object]],
    *,
    mode: Literal["live", "replay"] | None = None,
    replay_path: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 30.0,
    tools: list[dict[str, object]] | None = None,
) -> LLMResponse:
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
            value = {"content": value}
        if not isinstance(value, dict):
            raise LLMError(
                f"Replay response for {key} must be a string or response object."
            )
        return _response_from_message(
            value,
            finish_reason=value.get("finish_reason"),
            usage=value.get("usage"),
        )

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
    endpoint = (
        base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1"
    ).rstrip("/")
    payload: dict[str, object] = {
        "model": selected_model,
        "temperature": 0,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        response = requests.post(
            f"{endpoint}/chat/completions",
            headers={"Authorization": f"Bearer {selected_api_key}"},
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        message = body["choices"][0]["message"]
        finish_reason = body["choices"][0].get("finish_reason")
        usage = body.get("usage")
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"LLM request failed: {type(exc).__name__}: {exc}") from exc
    return _response_from_message(
        message,
        finish_reason=finish_reason,
        usage=usage,
    )


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
    response = invoke_chat(
        messages,
        mode=mode,
        replay_path=replay_path,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )
    if response.content is None:
        raise LLMError("LLM response did not contain text content.")
    return response.content
