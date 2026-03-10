"""Langfuse observability integration with graceful degradation.

If Langfuse is not installed or not configured, all decorators and functions
become no-ops so the rest of the system runs unaffected.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_langfuse_client = None
_langfuse_observe = None
_langfuse_available = False

try:
    from langfuse import Langfuse

    try:
        from langfuse.decorators import observe as _langfuse_observe  # langfuse 2.x
    except ImportError:
        from langfuse import observe as _langfuse_observe  # langfuse 3.x

    _langfuse_available = True
except ImportError:
    pass


def _is_configured() -> bool:
    """Check if Langfuse env vars are present."""
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


def get_langfuse_client() -> Any | None:
    """Return a Langfuse client if available and configured, else None."""
    global _langfuse_client
    if _langfuse_client is not None:
        return _langfuse_client
    if not _langfuse_available or not _is_configured():
        return None
    try:
        _langfuse_client = Langfuse()
        return _langfuse_client
    except Exception:
        return None


def get_langfuse_callback_handler() -> Any | None:
    """Return a LangchainCallbackHandler if langfuse is available and configured, else None.

    Gated behind _is_configured() to prevent console auth warnings when credentials are absent.
    """
    if not _langfuse_available or not _is_configured():
        return None
    try:
        from langfuse.langchain import CallbackHandler  # requires langchain (transitive dep)

        return CallbackHandler()
    except Exception:
        return None


def observe(name: str | None = None) -> Callable[[F], F]:
    """Decorator that wraps a function with Langfuse tracing if available.

    Falls back to a no-op decorator if Langfuse is not installed or configured.

    Usage:
        @observe("my_function")
        def my_function():
            ...
    """
    if _langfuse_available and _is_configured() and _langfuse_observe is not None:
        return _langfuse_observe(name=name)

    def passthrough(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return passthrough  # type: ignore[return-value]


def flush() -> None:
    """Flush any pending Langfuse events. No-op if not configured."""
    import contextlib

    client = get_langfuse_client()
    if client is not None:
        with contextlib.suppress(Exception):
            client.flush()


def report_schema_compliance(
    role: str,
    first_attempt_success: bool,
    trace_id: str | None = None,
    run_id: str | None = None,
) -> None:
    """Report schema compliance to Langfuse as a numeric score. No-op if not configured."""
    client = get_langfuse_client()
    if client is None:
        return
    import contextlib

    with contextlib.suppress(Exception):
        kwargs: dict[str, Any] = {
            "name": "schema_compliance",
            "value": 1.0 if first_attempt_success else 0.0,
            "data_type": "NUMERIC",
            "comment": f"role={role}",
        }
        if trace_id:
            kwargs["trace_id"] = trace_id
        if run_id:
            kwargs["session_id"] = run_id
        client.create_score(**kwargs)
