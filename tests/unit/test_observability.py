"""Structural unit tests for OBSV-01: Langfuse 3.x wiring."""
from __future__ import annotations

import inspect

import pytest


def test_langfuse_available_with_3x():
    """langfuse 3.x dual-path import sets _langfuse_available=True."""
    pytest.importorskip("langfuse")
    from agentic_workflows import observability

    assert observability._langfuse_available is True, (
        "observability._langfuse_available is False — dual-path import fix not applied. "
        "Expected 'from langfuse import observe' fallback to succeed with langfuse 3.x."
    )


def test_get_langfuse_callback_handler_returns_none_without_creds(monkeypatch):
    """No credentials → handler is None → no console noise in tests."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    from agentic_workflows.observability import get_langfuse_callback_handler

    assert get_langfuse_callback_handler() is None


def test_callback_handler_wired_in_graph_invoke(monkeypatch):
    """graph.py run() passes callbacks= to _compiled.invoke. Structural check via source inspection."""
    from agentic_workflows.orchestration.langgraph import graph as graph_module

    source = inspect.getsource(graph_module.LangGraphOrchestrator.run)
    assert "_active_callbacks" in source, (
        "_active_callbacks not found in LangGraphOrchestrator.run source. "
        "CallbackHandler wiring task may not have been applied."
    )
    assert "callbacks" in source, (
        "'callbacks' key not found in run() source. "
        "config={'callbacks': ...} not wired into _compiled.invoke()."
    )


def test_ollama_generate_has_observe_decorator():
    """OllamaChatProvider.generate must be decorated with @observe() — structural guard."""
    from agentic_workflows.orchestration.langgraph.provider import OllamaChatProvider

    method = OllamaChatProvider.generate
    assert hasattr(method, "__wrapped__"), (
        "OllamaChatProvider.generate does not have __wrapped__. "
        "@observe() was either removed or not applied. "
        "functools.wraps sets __wrapped__ on both the real decorator and the no-op passthrough."
    )
