"""TEST_MODE-only tracing for LLM calls.

The query code can run outside Streamlit, so this module intentionally keeps
collection UI-free. Streamlit pages render the collected events separately.
"""

from __future__ import annotations

import os
import time
from contextvars import ContextVar
from typing import Any, Awaitable


_TRACE_EVENTS: ContextVar[list[dict[str, Any]]] = ContextVar(
    "autopm3_model_trace_events",
    default=[],
)

_MAX_TEXT_CHARS = int(os.getenv("AUTOPM3_TRACE_MAX_CHARS", "12000"))


def is_model_trace_enabled() -> bool:
    return os.environ.get("TEST_MODE") == "ON"


def clear_model_trace() -> None:
    _TRACE_EVENTS.set([])


def get_model_trace() -> list[dict[str, Any]]:
    return list(_TRACE_EVENTS.get())


def _stringify(value: Any) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = repr(value)
        except Exception:
            text = f"<unrepresentable {type(value).__name__}>"
    if len(text) > _MAX_TEXT_CHARS:
        return text[:_MAX_TEXT_CHARS].rstrip() + f"\n... [truncated at {_MAX_TEXT_CHARS} chars]"
    return text


def _response_text(response: Any) -> str:
    return _stringify(getattr(response, "content", response))


async def trace_ainvoke(
    *,
    label: str,
    model_name: str | None,
    input_payload: Any,
    awaitable: Awaitable[Any],
) -> Any:
    """Await one model call and record timing/input/output in TEST_MODE."""
    if not is_model_trace_enabled():
        return await awaitable

    events = _TRACE_EVENTS.get()
    event: dict[str, Any] = {
        "label": label,
        "model_name": model_name or "unknown",
        "input": _stringify(input_payload),
        "started_at": time.time(),
        "duration_ms": None,
        "output": "",
        "error": None,
    }
    events.append(event)
    try:
        response = await awaitable
        event["output"] = _response_text(response)
        return response
    except BaseException as exc:
        event["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        event["duration_ms"] = round((time.time() - event["started_at"]) * 1000, 1)
