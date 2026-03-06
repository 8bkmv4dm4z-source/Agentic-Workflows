"""Tests for provider retry logic and _is_retryable_timeout_error."""

from __future__ import annotations

from agentic_workflows.orchestration.langgraph.provider import _is_retryable_timeout_error


def test_http_500_is_retryable():
    assert _is_retryable_timeout_error(Exception("Ollama HTTP 500 error"))


def test_context_length_is_retryable():
    assert _is_retryable_timeout_error(Exception("context length exceeded: 32768"))


def test_status_code_500_is_retryable():
    assert _is_retryable_timeout_error(Exception("request failed with status code 500"))


def test_context_window_is_retryable():
    assert _is_retryable_timeout_error(Exception("context window exceeded"))


def test_payload_too_large_is_retryable():
    assert _is_retryable_timeout_error(Exception("payload too large for model"))


def test_request_entity_too_large_is_retryable():
    assert _is_retryable_timeout_error(Exception("request entity too large"))


def test_non_retryable_value_error():
    assert not _is_retryable_timeout_error(ValueError("bad request"))


def test_non_retryable_general_error():
    assert not _is_retryable_timeout_error(RuntimeError("unexpected model behavior"))


def test_existing_timeout_still_retryable():
    """Original markers must still work."""
    assert _is_retryable_timeout_error(Exception("connection timeout after 30s"))
    assert _is_retryable_timeout_error(Exception("read timeout"))
    assert _is_retryable_timeout_error(Exception("service unavailable"))
