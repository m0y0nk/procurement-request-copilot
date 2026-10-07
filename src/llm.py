from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import os
import random
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import requests

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPLAY_PATH = ROOT / "eval" / "replay" / "responses.json"
DEFAULT_USAGE_PATH = ROOT / ".cache" / "llm_usage.json"
MAX_ESTIMATED_REQUEST_TOKENS = 7000
MAX_RETRIES = 4
CIRCUIT_BREAKER_FAILURES = 3


class LLMError(RuntimeError):
    pass


class ReplayResponseMissing(LLMError):
    pass


class LLMRunAborted(RuntimeError):
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
    latency_ms: float = 0
    retries: int = 0
    cached: bool = False
    rate_limits: dict[str, str] = field(default_factory=dict)


@dataclass
class LiveRunState:
    calls: int = 0
    tokens: int = 0
    retries: int = 0
    consecutive_failures: int = 0
    last_request_at: float = 0
    aborted: bool = False
    initialized: bool = False
    rolling_window: list[tuple[float, int]] = field(default_factory=list)


_STATE = LiveRunState()
_STATE_LOCK = threading.RLock()
_FILE_LOCK = threading.RLock()
_LAST_RATE_LIMITS: dict[str, str] = {}


def reset_live_run_state() -> None:
    with _STATE_LOCK:
        _STATE.calls = 0
        _STATE.tokens = 0
        _STATE.retries = 0
        _STATE.consecutive_failures = 0
        _STATE.aborted = False
        _STATE.initialized = True
        _STATE.rolling_window.clear()
        _LAST_RATE_LIMITS.clear()
        usage_path = _usage_path()
        daily = _read_daily_usage(usage_path)
        today = datetime.now(UTC).date().isoformat()
        daily_record = daily.get(today, {})
        daily_tokens = int(daily_record.get("tokens", 0))
        if daily_tokens >= _int_setting("LLM_MAX_TOKENS_PER_DAY", 200000):
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Daily token budget is already spent for {today}: "
                f"{daily_tokens} tokens recorded."
            )
        daily_calls = int(daily_record.get("calls", 0))
        if daily_calls >= _int_setting("LLM_MAX_CALLS_PER_DAY", 1000):
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Daily request budget is already spent for {today}: "
                f"{daily_calls} requests recorded."
            )
        recent = daily_record.get("recent", [])
        if isinstance(recent, list):
            _STATE.rolling_window = [
                (float(event["at"]), int(event["tokens"]))
                for event in recent
                if isinstance(event, dict)
                and isinstance(event.get("at"), (int, float))
                and isinstance(event.get("tokens"), int)
                and time.time() - float(event["at"]) < 60
            ]
        last_request_at = daily_record.get("last_request_at", 0)
        if isinstance(last_request_at, (int, float)):
            _STATE.last_request_at = float(last_request_at)


def live_run_usage() -> dict[str, int]:
    with _STATE_LOCK:
        return {
            "calls": _STATE.calls,
            "tokens": _STATE.tokens,
            "retries": _STATE.retries,
            "consecutive_failures": _STATE.consecutive_failures,
        }


def request_key(messages: list[dict[str, object]], model: str | None = None) -> str:
    selected_model = model or os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME")
    if not selected_model:
        raise LLMError("LLM_MODEL is required to identify a replay request.")
    canonical = json.dumps(
        {"model": selected_model, "messages": messages},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def estimate_tokens(messages: list[dict[str, object]]) -> int:
    return max(
        1,
        (len(json.dumps(messages, sort_keys=True, separators=(",", ":"))) + 3) // 4,
    )


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


def _normalized_usage(usage: object) -> dict[str, int]:
    normalized: dict[str, int] = {}
    if not isinstance(usage, dict):
        return normalized
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "reasoning_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, int) and value >= 0:
            normalized[key] = value
    completion_details = usage.get("completion_tokens_details")
    if (
        "reasoning_tokens" not in normalized
        and isinstance(completion_details, dict)
        and isinstance(completion_details.get("reasoning_tokens"), int)
        and completion_details["reasoning_tokens"] >= 0
    ):
        normalized["reasoning_tokens"] = completion_details["reasoning_tokens"]
    return normalized


def _messages_for_model(
    messages: list[dict[str, object]],
    model: str,
) -> list[dict[str, object]]:
    if not model.startswith("openai/gpt-oss-"):
        return messages
    system_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if message.get("role") == "system"
    )
    model_messages = [
        dict(message) for message in messages if message.get("role") != "system"
    ]
    for message in model_messages:
        if message.get("role") == "user":
            message["content"] = (
                system_text + "\n\n" + str(message.get("content", ""))
            )
            break
    else:
        model_messages.insert(0, {"role": "user", "content": system_text})
    return model_messages


def _response_from_message(
    message: object,
    *,
    finish_reason: object = None,
    usage: object = None,
    latency_ms: object = 0,
    retries: int = 0,
    cached: bool = False,
    rate_limits: dict[str, str] | None = None,
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
    normalized_usage = _normalized_usage(usage)
    latency = (
        float(latency_ms)
        if isinstance(latency_ms, (int, float)) and latency_ms >= 0
        else 0.0
    )
    return LLMResponse(
        content=content,
        tool_calls=parsed_calls,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        usage=normalized_usage,
        raw_message=message,
        latency_ms=latency,
        retries=retries,
        cached=cached,
        rate_limits=rate_limits or {},
    )


def _replay_path(path: Path | None = None) -> Path:
    return path or Path(os.getenv("LLM_REPLAY_PATH", str(DEFAULT_REPLAY_PATH)))


def _usage_path() -> Path:
    return Path(os.getenv("LLM_USAGE_PATH", str(DEFAULT_USAGE_PATH)))


def _read_replay(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise LLMError(f"Invalid replay JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LLMError(f"Replay file must contain a JSON object: {path}")
    return value


def _read_daily_usage(path: Path) -> dict[str, dict[str, object]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise LLMRunAborted(f"Invalid daily usage counter: {path}") from exc
    if not isinstance(value, dict):
        raise LLMRunAborted(f"Invalid daily usage counter: {path}")
    daily: dict[str, dict[str, object]] = {}
    try:
        for day, entry in value.items():
            if isinstance(entry, int):
                daily[str(day)] = {"tokens": entry, "calls": 0}
            elif isinstance(entry, dict):
                record: dict[str, object] = {
                    "tokens": int(entry.get("tokens", 0)),
                    "calls": int(entry.get("calls", 0)),
                    "recent": entry.get("recent", []),
                    "last_request_at": entry.get("last_request_at", 0),
                }
                daily[str(day)] = record
    except (TypeError, ValueError) as exc:
        raise LLMRunAborted(f"Invalid daily usage counter: {path}") from exc
    return daily


def _atomic_json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            json.dump(value, output, sort_keys=True, ensure_ascii=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _cache_response(
    path: Path,
    key: str,
    model: str,
    response: LLMResponse,
) -> None:
    with _FILE_LOCK:
        replay = _read_replay(path)
        replay[key] = {
            "model": model,
            "raw_message": response.raw_message,
            "finish_reason": response.finish_reason,
            "usage": response.usage,
            "latency_ms": response.latency_ms,
        }
        _atomic_json_write(path, replay)


def _load_cached(
    path: Path,
    key: str,
    model: str,
) -> LLMResponse | None:
    with _FILE_LOCK:
        replay = _read_replay(path)
    value = replay.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        value = {"content": value}
    if not isinstance(value, dict):
        raise LLMError(f"Replay response for {key} must be a response object.")
    if value.get("model") != model:
        raise ReplayResponseMissing(
            f"Replay response for request hash {key} does not match model {model}."
        )
    raw_message = value.get("raw_message", value)
    return _response_from_message(
        raw_message,
        finish_reason=value.get("finish_reason"),
        usage=value.get("usage"),
        latency_ms=value.get("latency_ms", 0),
        cached=True,
    )


def _int_setting(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise LLMRunAborted(f"{name} must be an integer.") from exc


def _float_setting(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise LLMRunAborted(f"{name} must be a number.") from exc
    if value < 0:
        raise LLMRunAborted(f"{name} cannot be negative.")
    return value


def _parse_wait(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        seconds = 0.0
        for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-z]+)", value.lower()):
            seconds += float(amount) * {
                "ms": 0.001,
                "s": 1,
                "sec": 1,
                "m": 60,
                "min": 60,
                "h": 3600,
                "d": 86400,
            }.get(unit, 0)
        if seconds:
            return seconds
        retry_at = email.utils.parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _headers(response: requests.Response) -> dict[str, str]:
    return {key.lower(): value for key, value in response.headers.items()}


def _rate_limits(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.startswith("x-ratelimit-")
        or key in {"retry-after", "retry-after-ms"}
    }


def _unadvertised_tool_call_name(
    response: requests.Response,
    payload: dict[str, object],
) -> str | None:
    try:
        body = response.json()
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict) or error.get("code") != "tool_use_failed":
        return None
    message = error.get("message")
    if not isinstance(message, str):
        return None
    match = re.search(
        r"attempted to call tool ['\"]([^'\"]+)['\"] which was not in request\.tools",
        message,
    )
    if match is None:
        return None
    tool_schemas = payload.get("tools")
    advertised_names: set[object] = set()
    if isinstance(tool_schemas, list):
        for schema in tool_schemas:
            if not isinstance(schema, dict):
                continue
            function = schema.get("function")
            if isinstance(function, dict):
                advertised_names.add(function.get("name"))
    tool_name = match.group(1)
    return tool_name if tool_name not in advertised_names else None


def _reset_wait(headers: dict[str, str], *, tokens: bool = False) -> float | None:
    suffix = "tokens" if tokens else "requests"
    for key in (f"x-ratelimit-reset-{suffix}", "x-ratelimit-reset"):
        wait = _parse_wait(headers.get(key))
        if wait is not None:
            return wait
    return None


def _daily_remaining(headers: dict[str, str], *, tokens: bool) -> int | None:
    kind = "tokens" if tokens else "requests"
    for key in (
        f"x-ratelimit-remaining-{kind}-day",
        f"x-ratelimit-remaining-{kind}-daily",
        f"x-ratelimit-remaining-day-{kind}",
        f"x-ratelimit-remaining-daily-{kind}",
    ):
        value = headers.get(key)
        if value is not None:
            try:
                return int(value)
            except ValueError:
                LOGGER.warning("Ignoring unparseable daily rate-limit header: %s", key)
    return None


def _daily_reset_wait(headers: dict[str, str], *, tokens: bool) -> float | None:
    kind = "tokens" if tokens else "requests"
    for key in (
        f"x-ratelimit-reset-{kind}-day",
        f"x-ratelimit-reset-{kind}-daily",
        f"x-ratelimit-reset-day-{kind}",
        f"x-ratelimit-reset-daily-{kind}",
        "x-ratelimit-reset-day",
        "x-ratelimit-reset-daily",
    ):
        wait = _parse_wait(headers.get(key))
        if wait is not None:
            return wait
    return None


def _daily_limit_hit(headers: dict[str, str], wait: float | None) -> bool:
    header_values = " ".join(headers.values()).lower()
    exhausted_daily = any(
        "remaining" in key
        and ("day" in key or "daily" in key)
        and int(value) <= 0
        for key, value in headers.items()
        if value.lstrip("-").isdigit()
    )
    return (
        "daily" in header_values
        or "per day" in header_values
        or exhausted_daily
        or wait is not None and wait >= 3600
    )


def _sleep_checked(wait: float, *, limit_name: str) -> None:
    max_wait = _float_setting("LLM_MAX_WAIT_SECONDS", 90)
    if wait > max_wait:
        raise LLMRunAborted(
            f"{limit_name} requires waiting {wait:.1f}s, above "
            f"LLM_MAX_WAIT_SECONDS={max_wait:.1f}s. Stop and resume after reset."
        )
    if wait > 0:
        time.sleep(wait)


def _wait_for_rate_window(headers: dict[str, str], estimate: int) -> None:
    remaining_tokens = headers.get("x-ratelimit-remaining-tokens")
    remaining_requests = headers.get("x-ratelimit-remaining-requests")
    token_wait = _reset_wait(headers, tokens=True)
    request_wait = _reset_wait(headers)
    wait: float | None = None
    limit_name = "rate limit"
    exhausted = False
    daily_tokens = _daily_remaining(headers, tokens=True)
    daily_requests = _daily_remaining(headers, tokens=False)
    if daily_tokens is not None and daily_tokens < estimate:
        exhausted = True
        wait = _daily_reset_wait(headers, tokens=True)
        limit_name = "daily token rate limit"
    if daily_requests is not None and daily_requests <= 0:
        exhausted = True
        daily_request_wait = _daily_reset_wait(headers, tokens=False)
        wait = max(wait or 0, daily_request_wait or 0)
        limit_name = "daily request rate limit"
    if remaining_tokens is not None:
        try:
            if int(remaining_tokens) < estimate:
                exhausted = True
                if wait is None:
                    wait = token_wait
                    limit_name = "per-minute token rate limit"
        except ValueError:
            LOGGER.warning("Ignoring unparseable token remaining header.")
    if remaining_requests is not None:
        try:
            if int(remaining_requests) <= 0:
                exhausted = True
                wait = max(wait or 0, request_wait or 0)
                if daily_requests is None or daily_requests > 0:
                    limit_name = "per-minute request rate limit"
        except ValueError:
            LOGGER.warning("Ignoring unparseable request remaining header.")
    if not exhausted:
        return
    if wait is None or wait <= 0:
        raise LLMRunAborted(
            f"{limit_name} is exhausted but no reset interval was provided."
        )
    _sleep_checked(wait, limit_name=limit_name)


def _daily_tokens(path: Path) -> int:
    daily = _read_daily_usage(path)
    return int(
        daily.get(datetime.now(UTC).date().isoformat(), {}).get("tokens", 0)
    )


def _daily_calls(path: Path) -> int:
    daily = _read_daily_usage(path)
    return int(
        daily.get(datetime.now(UTC).date().isoformat(), {}).get("calls", 0)
    )


def _persist_daily_usage(
    path: Path,
    *,
    tokens: int = 0,
    calls: int = 0,
    event_tokens: int | None = None,
) -> None:
    with _FILE_LOCK:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            existing = {}
        except json.JSONDecodeError as exc:
            raise LLMRunAborted(f"Invalid daily usage counter: {path}") from exc
        if not isinstance(existing, dict):
            raise LLMRunAborted(f"Invalid daily usage counter: {path}")
        today = datetime.now(UTC).date().isoformat()
        day_record = existing.get(today)
        if isinstance(day_record, int):
            day_record = {"tokens": day_record, "calls": 0, "recent": []}
        elif not isinstance(day_record, dict):
            day_record = {"tokens": 0, "calls": 0, "recent": []}
        day_record["tokens"] = int(day_record.get("tokens", 0)) + tokens
        day_record["calls"] = int(day_record.get("calls", 0)) + calls
        now = time.time()
        recent = day_record.get("recent", [])
        if not isinstance(recent, list):
            recent = []
        recent = [
            event
            for event in recent
            if isinstance(event, dict)
            and isinstance(event.get("at"), (int, float))
            and now - float(event["at"]) < 60
        ]
        if event_tokens is not None:
            recent.append({"at": now, "tokens": event_tokens})
            day_record["last_request_at"] = now
        day_record["recent"] = recent
        existing[today] = day_record
        _atomic_json_write(path, existing)


def _record_usage(
    usage: dict[str, int],
    *,
    prompt_estimate: int,
    usage_path: Path,
    reset_failures: bool,
) -> None:
    reported_tokens = usage.get("total_tokens")
    if reported_tokens is None:
        reported_tokens = (
            usage.get("prompt_tokens", prompt_estimate)
            + usage.get("completion_tokens", 0)
        )
    with _STATE_LOCK:
        if reset_failures:
            _STATE.consecutive_failures = 0
        _STATE.tokens += reported_tokens
        daily_cap = _int_setting("LLM_MAX_TOKENS_PER_DAY", 200000)
        daily_total = _daily_tokens(usage_path)
        _persist_daily_usage(usage_path, tokens=reported_tokens)
        if _STATE.tokens > _int_setting("LLM_MAX_TOKENS_PER_RUN", 200000):
            _STATE.aborted = True
            raise LLMRunAborted("Per-run token cap reached after provider response.")
        if daily_total + reported_tokens > daily_cap:
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Provider response reached the daily token cap "
                f"({daily_total + reported_tokens}/{daily_cap})."
            )


def _record_success(
    response: LLMResponse,
    *,
    prompt_estimate: int,
    usage_path: Path,
) -> None:
    _record_usage(
        response.usage,
        prompt_estimate=prompt_estimate,
        usage_path=usage_path,
        reset_failures=True,
    )


def _preflight_budgets(
    *,
    input_estimate: int,
    max_tokens: int,
    usage_path: Path,
) -> None:
    with _STATE_LOCK:
        if _STATE.aborted:
            raise LLMRunAborted("Live LLM run is stopped by its circuit breaker or budget.")
        calls_cap = _int_setting("LLM_MAX_CALLS_PER_RUN", 200)
        calls_day_cap = _int_setting("LLM_MAX_CALLS_PER_DAY", 1000)
        token_cap = _int_setting("LLM_MAX_TOKENS_PER_RUN", 200000)
        daily_cap = _int_setting("LLM_MAX_TOKENS_PER_DAY", 200000)
        daily_tokens = _daily_tokens(usage_path)
        daily_calls = _daily_calls(usage_path)
        if daily_tokens >= daily_cap:
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Daily token cap is spent ({daily_tokens}/{daily_cap})."
            )
        if _STATE.calls >= calls_cap:
            _STATE.aborted = True
            raise LLMRunAborted(f"Per-run call cap reached ({_STATE.calls}/{calls_cap}).")
        if daily_calls >= calls_day_cap:
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Daily request cap reached ({daily_calls}/{calls_day_cap})."
            )
        request_estimate = input_estimate + max_tokens
        request_limit = MAX_ESTIMATED_REQUEST_TOKENS
        if request_estimate > request_limit:
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Estimated request size ({request_estimate} tokens) exceeds "
                f"the {request_limit}-token safety limit."
            )
        projected_run = _STATE.tokens + input_estimate + max_tokens
        if projected_run > token_cap:
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Request would exceed per-run token cap "
                f"({projected_run}/{token_cap}); save progress and resume later."
            )
        projected_day = daily_tokens + input_estimate + max_tokens
        if projected_day > daily_cap:
            _STATE.aborted = True
            raise LLMRunAborted(
                f"Request would exceed daily token cap "
                f"({projected_day}/{daily_cap}); save progress and resume after UTC reset."
            )


def _request_interval(request_tokens: int) -> float:
    requests_per_minute = _int_setting("LLM_REQUESTS_PER_MINUTE", 30)
    tokens_per_minute = _int_setting("LLM_TOKENS_PER_MINUTE", 8000)
    if requests_per_minute <= 0 or tokens_per_minute <= 0:
        raise LLMRunAborted("Configured per-minute limits must be positive.")
    configured_gap = _float_setting("LLM_MIN_INTERVAL_SECONDS", 20.1)
    return max(
        configured_gap,
        60 / requests_per_minute,
        60 * request_tokens / tokens_per_minute,
    )


def _reserve_rolling_window(request_tokens: int) -> None:
    requests_per_minute = _int_setting("LLM_REQUESTS_PER_MINUTE", 30)
    tokens_per_minute = _int_setting("LLM_TOKENS_PER_MINUTE", 8000)
    if request_tokens > tokens_per_minute:
        raise LLMRunAborted(
            f"Estimated request size ({request_tokens} tokens) exceeds the "
            f"{tokens_per_minute}-token rolling minute limit."
        )
    while True:
        now = time.time()
        with _STATE_LOCK:
            _STATE.rolling_window = [
                (timestamp, tokens)
                for timestamp, tokens in _STATE.rolling_window
                if now - timestamp < 60
            ]
            existing_tokens = sum(tokens for _, tokens in _STATE.rolling_window)
            if (
                len(_STATE.rolling_window) < requests_per_minute
                and existing_tokens + request_tokens <= tokens_per_minute
            ):
                _STATE.rolling_window.append((now, request_tokens))
                return

            expirations = sorted(
                timestamp + 60 for timestamp, _ in _STATE.rolling_window
            )
            wait_seconds: float | None = None
            for expiry in expirations:
                surviving = [
                    (timestamp, tokens)
                    for timestamp, tokens in _STATE.rolling_window
                    if timestamp + 60 > expiry
                ]
                if (
                    len(surviving) < requests_per_minute
                    and sum(tokens for _, tokens in surviving) + request_tokens
                    <= tokens_per_minute
                ):
                    wait_seconds = max(0.001, expiry - now)
                    break
        if wait_seconds is None:
            raise LLMRunAborted(
                "The rolling minute quota is exhausted and cannot fit this request."
            )
        time.sleep(wait_seconds)


def _failed_call(message: str) -> LLMError:
    with _STATE_LOCK:
        _STATE.consecutive_failures += 1
        if _STATE.consecutive_failures >= CIRCUIT_BREAKER_FAILURES:
            _STATE.aborted = True
            return LLMRunAborted(
                f"Circuit breaker stopped the run after "
                f"{_STATE.consecutive_failures} consecutive failures. "
                f"{message} Check the provider status and rate-limit reset, then resume."
            )
    return LLMError(message)


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
    max_tokens: int | None = None,
    no_cache: bool | None = None,
) -> LLMResponse:
    selected_mode = mode or os.getenv("LLM_MODE", "live")
    if selected_mode not in {"live", "replay"}:
        raise ValueError("LLM_MODE must be 'live' or 'replay'.")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive.")
    selected_model = model or os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME")
    if not selected_model:
        raise LLMError("LLM_MODEL is required for live and replay requests.")
    key = request_key(messages, selected_model)
    cache_path = _replay_path(replay_path)
    if selected_mode == "replay":
        cached = _load_cached(cache_path, key, selected_model)
        if cached is None:
            raise ReplayResponseMissing(
                f"No replay response for request hash {key}."
            )
        return cached

    force_fresh = no_cache if no_cache is not None else (
        os.getenv("LLM_NO_CACHE", "").casefold() in {"1", "true", "yes"}
    )
    if not force_fresh:
        cached = _load_cached(cache_path, key, selected_model)
        if cached is not None:
            return cached

    selected_provider = provider or os.getenv("LLM_PROVIDER", "openai")
    raw_api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    if selected_provider != "openai":
        raise LLMError(
            f"Unsupported live LLM provider {selected_provider!r}; configure openai-compatible access."
        )
    if not selected_model:
        raise LLMError("LLM_MODEL is required in live mode.")
    if not raw_api_key or not raw_api_key.strip().strip("'\""):
        raise LLMError("LLM_API_KEY is required in live mode.")
    selected_api_key = raw_api_key.strip().strip("'\"")
    auth_header = (
        selected_api_key
        if selected_api_key.startswith("Bearer ")
        else f"Bearer {selected_api_key}"
    )
    with _STATE_LOCK:
        needs_initialization = not _STATE.initialized
    if needs_initialization:
        reset_live_run_state()
    endpoint = (
        base_url or os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1"
    ).rstrip("/")
    selected_max_tokens = (
        max_tokens if max_tokens is not None else _int_setting("LLM_MAX_TOKENS", 1200)
    )
    if selected_max_tokens <= 0:
        raise LLMRunAborted("LLM_MAX_TOKENS must be positive.")
    payload: dict[str, object] = {
        "model": selected_model,
        "temperature": 0,
        "messages": _messages_for_model(messages, selected_model),
    }
    if selected_model.startswith("openai/gpt-oss-"):
        payload["max_completion_tokens"] = selected_max_tokens
        reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "low").casefold()
        if reasoning_effort not in {"low", "medium", "high"}:
            raise LLMRunAborted(
                "LLM_REASONING_EFFORT must be low, medium, or high for GPT-OSS."
            )
        payload["reasoning_effort"] = reasoning_effort
    else:
        payload["max_tokens"] = selected_max_tokens
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    usage_path = _usage_path()
    budget_messages: list[dict[str, object]] = list(messages)
    if tools:
        budget_messages.append({"role": "tool_schemas", "content": tools})
    prompt_estimate = estimate_tokens(budget_messages)
    request_estimate = prompt_estimate + selected_max_tokens
    request_started = time.perf_counter()
    retries = 0
    retried_without_tools = False
    with _STATE_LOCK:
        rate_limits = dict(_LAST_RATE_LIMITS)
    while True:
        _preflight_budgets(
            input_estimate=prompt_estimate,
            max_tokens=selected_max_tokens,
            usage_path=usage_path,
        )
        _wait_for_rate_window(rate_limits, request_estimate)
        interval = _request_interval(request_estimate)
        with _STATE_LOCK:
            wait_for_gap = interval - (time.time() - _STATE.last_request_at)
        if wait_for_gap > 0:
            time.sleep(wait_for_gap)
        with _STATE_LOCK:
            calls_cap = _int_setting("LLM_MAX_CALLS_PER_RUN", 200)
            if _STATE.calls >= calls_cap:
                _STATE.aborted = True
                raise LLMRunAborted(f"Per-run call cap reached ({calls_cap}).")
            daily_calls = _daily_calls(usage_path)
            daily_calls_cap = _int_setting("LLM_MAX_CALLS_PER_DAY", 1000)
            if daily_calls >= daily_calls_cap:
                _STATE.aborted = True
                raise LLMRunAborted(
                    f"Daily request cap reached ({daily_calls}/{daily_calls_cap})."
                )
        _reserve_rolling_window(request_estimate)
        with _STATE_LOCK:
            _STATE.calls += 1
            _STATE.last_request_at = time.time()
            _persist_daily_usage(
                usage_path,
                calls=1,
                event_tokens=request_estimate,
            )
        try:
            response = requests.post(
                f"{endpoint}/chat/completions",
                headers={"Authorization": auth_header},
                json=payload,
                timeout=timeout_seconds,
            )
        except requests.Timeout:
            raise _failed_call("LLM request timed out.") from None
        except requests.RequestException as exc:
            safe_error = type(exc).__name__
            raise _failed_call(f"LLM request failed: {safe_error}.") from None

        response_headers = _headers(response)
        rate_limits = _rate_limits(response_headers)
        with _STATE_LOCK:
            _LAST_RATE_LIMITS.clear()
            _LAST_RATE_LIMITS.update(rate_limits)
        LOGGER.info("LLM provider rate-limit headers: %s", rate_limits)
        status = response.status_code
        if status == 429:
            retry_after = _parse_wait(
                response_headers.get("retry-after")
                or response_headers.get("retry-after-ms")
            )
            if response_headers.get("retry-after-ms") and retry_after is not None:
                retry_after /= 1000
            reset_after = _reset_wait(response_headers)
            wait = retry_after if retry_after is not None else reset_after
            if wait is None:
                wait = 2 ** (retries + 1) + random.uniform(0, 1)
            if _daily_limit_hit(response_headers, wait):
                raise LLMRunAborted(
                    "Groq daily rate limit reached. Stop for the UTC reset and resume."
                )
            if retries >= MAX_RETRIES:
                raise _failed_call("HTTP 429 remained after four retries.")
            if wait > _float_setting("LLM_MAX_WAIT_SECONDS", 90):
                raise LLMRunAborted(
                    f"Per-minute rate limit requires waiting {wait:.1f}s, above "
                    f"LLM_MAX_WAIT_SECONDS={_float_setting('LLM_MAX_WAIT_SECONDS', 90):.1f}s."
                )
            retries += 1
            with _STATE_LOCK:
                _STATE.retries += 1
            time.sleep(wait)
            rate_limits = {}
            continue
        if 500 <= status <= 599:
            if retries >= MAX_RETRIES:
                raise _failed_call(f"HTTP {status} remained after four retries.")
            retry_after = _parse_wait(response_headers.get("retry-after"))
            wait = retry_after if retry_after is not None else (
                2 ** (retries + 1) + random.uniform(0, 1)
            )
            if wait > _float_setting("LLM_MAX_WAIT_SECONDS", 90):
                raise LLMRunAborted(
                    f"HTTP {status} retry requires waiting {wait:.1f}s, above "
                    "LLM_MAX_WAIT_SECONDS."
                )
            retries += 1
            with _STATE_LOCK:
                _STATE.retries += 1
            time.sleep(wait)
            rate_limits = {}
            continue
        if status == 400 and not retried_without_tools:
            if _unadvertised_tool_call_name(response, payload) is not None:
                payload = {
                    key: value
                    for key, value in payload.items()
                    if key not in {"tools", "tool_choice"}
                }
                retried_without_tools = True
                retries += 1
                with _STATE_LOCK:
                    _STATE.retries += 1
                LOGGER.warning(
                    "LLM provider rejected an unadvertised tool call; "
                    "retrying once without tool schemas."
                )
                rate_limits = {}
                continue
        if status < 200 or status >= 300:
            raise _failed_call(f"LLM provider returned HTTP {status}.")
        try:
            body = response.json()
            message = body["choices"][0]["message"]
            finish_reason = body["choices"][0].get("finish_reason")
            usage = body.get("usage")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise _failed_call(
                f"LLM response could not be parsed ({type(exc).__name__})."
            ) from None
        if finish_reason == "length":
            _record_usage(
                _normalized_usage(usage),
                prompt_estimate=prompt_estimate,
                usage_path=usage_path,
                reset_failures=False,
            )
            raise _failed_call(
                "LLM response was truncated at its completion-token limit."
            )
        if (
            isinstance(message, dict)
            and not message.get("tool_calls")
            and (not isinstance(message.get("content"), str) or not message["content"].strip())
        ):
            _record_usage(
                _normalized_usage(usage),
                prompt_estimate=prompt_estimate,
                usage_path=usage_path,
                reset_failures=False,
            )
            raise _failed_call("LLM response was empty and is treated as truncated.")
        latency_ms = (time.perf_counter() - request_started) * 1000
        result = _response_from_message(
            message,
            finish_reason=finish_reason,
            usage=usage,
            latency_ms=latency_ms,
            retries=retries,
            rate_limits=rate_limits,
        )
        _record_success(
            result,
            prompt_estimate=prompt_estimate,
            usage_path=usage_path,
        )
        _cache_response(cache_path, key, selected_model, result)
        return result


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
    no_cache: bool | None = None,
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
        no_cache=no_cache,
    )
    if response.content is None:
        raise LLMError("LLM response did not contain text content.")
    return response.content
