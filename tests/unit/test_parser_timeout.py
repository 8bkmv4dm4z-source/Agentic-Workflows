"""Tests for adaptive parser timeout selection by provider type.

Phase 7.8 stabilization: local models (LlamaCpp/Ollama) get 30s parser timeout,
cloud providers (Groq/OpenAI) keep the fast 5s default.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from agentic_workflows.orchestration.langgraph.mission_parser import (
    _adaptive_classifier_timeout,
    _adaptive_parser_timeout,
)


class _FakeProvider:
    """Minimal provider stub with only __class__.__name__ set."""

    def __init__(self, class_name: str) -> None:
        # Override __class__ to simulate real provider class names
        self.__class__ = type(class_name, (), {})


class TestAdaptiveParserTimeout:
    def test_llamacpp_gets_30s(self) -> None:
        provider = _FakeProvider("LlamaCppChatProvider")
        assert _adaptive_parser_timeout(provider) == 30.0

    def test_ollama_gets_30s(self) -> None:
        provider = _FakeProvider("OllamaChatProvider")
        assert _adaptive_parser_timeout(provider) == 30.0

    def test_groq_gets_5s(self) -> None:
        provider = _FakeProvider("GroqChatProvider")
        assert _adaptive_parser_timeout(provider) == 5.0

    def test_openai_gets_5s(self) -> None:
        provider = _FakeProvider("OpenAIChatProvider")
        assert _adaptive_parser_timeout(provider) == 5.0

    def test_none_gets_5s(self) -> None:
        assert _adaptive_parser_timeout(None) == 5.0

    def test_env_override(self) -> None:
        provider = _FakeProvider("LlamaCppChatProvider")
        with patch.dict(os.environ, {"P1_PARSER_TIMEOUT_SECONDS": "15"}):
            assert _adaptive_parser_timeout(provider) == 15.0

    def test_env_override_applies_to_cloud(self) -> None:
        provider = _FakeProvider("GroqChatProvider")
        with patch.dict(os.environ, {"P1_PARSER_TIMEOUT_SECONDS": "15"}):
            assert _adaptive_parser_timeout(provider) == 15.0


class TestAdaptiveClassifierTimeout:
    def test_llamacpp_gets_5s(self) -> None:
        provider = _FakeProvider("LlamaCppChatProvider")
        assert _adaptive_classifier_timeout(provider) == 5.0

    def test_groq_gets_half_second(self) -> None:
        provider = _FakeProvider("GroqChatProvider")
        assert _adaptive_classifier_timeout(provider) == 0.5

    def test_ollama_gets_5s(self) -> None:
        provider = _FakeProvider("OllamaChatProvider")
        assert _adaptive_classifier_timeout(provider) == 5.0

    def test_openai_gets_half_second(self) -> None:
        provider = _FakeProvider("OpenAIChatProvider")
        assert _adaptive_classifier_timeout(provider) == 0.5

    def test_none_gets_half_second(self) -> None:
        assert _adaptive_classifier_timeout(None) == 0.5
