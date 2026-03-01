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
_langfuse_available = False

try:
    from langfuse import Langfuse
    from langfuse.decorators import observe as _langfuse_observe

    _langfuse_available = True
except ImportError:
    _langfuse_observe = None


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
