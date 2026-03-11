"""Unit tests for LlamaCppChatProvider: with_alias() and grammar auto-detection."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


@patch("agentic_workflows.orchestration.langgraph.provider.OpenAI")
@patch(
    "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
    return_value="base-model",
)
class TestLlamaCppWithAlias:
    """Tests for LlamaCppChatProvider.with_alias()."""

    def _make_provider(self, mock_detect: MagicMock, mock_openai: MagicMock):
        from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider

        provider = LlamaCppChatProvider(model="base-model")
        return provider

    def test_alias_returns_provider_with_alias_model(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ):
        """with_alias('planner') returns a LlamaCppChatProvider with model='planner'."""
        from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider

        provider = self._make_provider(mock_detect, mock_openai)
        aliased = provider.with_alias("planner")
        assert isinstance(aliased, LlamaCppChatProvider)
        assert aliased.model == "planner"

    def test_alias_shares_same_client(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ):
        """Aliased provider shares the same OpenAI client instance (is check)."""
        provider = self._make_provider(mock_detect, mock_openai)
        aliased = provider.with_alias("executor")
        assert aliased.client is provider.client

    def test_alias_preserves_retry_attributes(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ):
        """Aliased provider preserves timeout_seconds, max_retries, retry_backoff_seconds."""
        provider = self._make_provider(mock_detect, mock_openai)
        provider.timeout_seconds = 42.0
        provider.max_retries = 5
        provider.retry_backoff_seconds = 3.0

        aliased = provider.with_alias("planner")
        assert aliased.timeout_seconds == 42.0
        assert aliased.max_retries == 5
        assert aliased.retry_backoff_seconds == 3.0

    def test_alias_preserves_grammar_enabled(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ):
        """Aliased provider preserves _grammar_enabled from source."""
        provider = self._make_provider(mock_detect, mock_openai)
        provider._grammar_enabled = False

        aliased = provider.with_alias("planner")
        assert aliased._grammar_enabled is False

    def test_source_model_unchanged_after_alias(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ):
        """Source provider's model is unchanged after with_alias() call."""
        provider = self._make_provider(mock_detect, mock_openai)
        original_model = provider.model

        provider.with_alias("planner")
        assert provider.model == original_model

    def test_two_aliases_independent_instances(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ):
        """Two different aliases from same source produce independent instances."""
        provider = self._make_provider(mock_detect, mock_openai)

        alias_a = provider.with_alias("planner")
        alias_b = provider.with_alias("executor")

        assert alias_a is not alias_b
        assert alias_a.model == "planner"
        assert alias_b.model == "executor"
        assert alias_a.client is alias_b.client  # both share source client


@patch("agentic_workflows.orchestration.langgraph.provider.OpenAI")
@patch(
    "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
    return_value="Qwen3-8B-Q4_K_M.gguf",
)
class TestLlamaCppGrammarAutoDetect:
    """Tests for Qwen3 grammar auto-detection in LlamaCppChatProvider."""

    def test_qwen3_auto_disables_grammar(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Grammar is auto-disabled for Qwen3 models when env var is unset."""
        from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider

        with patch.dict(os.environ, {}, clear=False):
            # Ensure LLAMA_CPP_GRAMMAR is not set
            os.environ.pop("LLAMA_CPP_GRAMMAR", None)
            provider = LlamaCppChatProvider()
        assert provider._grammar_enabled is False

    def test_qwen3_explicit_grammar_true_overrides_auto(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Explicit LLAMA_CPP_GRAMMAR=true overrides Qwen3 auto-detection."""
        from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider

        with patch.dict(os.environ, {"LLAMA_CPP_GRAMMAR": "true"}, clear=False):
            provider = LlamaCppChatProvider()
        assert provider._grammar_enabled is True

    def test_qwen3_explicit_grammar_false_respected(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Explicit LLAMA_CPP_GRAMMAR=false is respected for Qwen3."""
        from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider

        with patch.dict(os.environ, {"LLAMA_CPP_GRAMMAR": "false"}, clear=False):
            provider = LlamaCppChatProvider()
        assert provider._grammar_enabled is False


@patch("agentic_workflows.orchestration.langgraph.provider.OpenAI")
@patch(
    "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
    return_value="Qwen2.5-7B-Instruct-Q4_K_M.gguf",
)
class TestLlamaCppGrammarNonQwen3:
    """Grammar stays enabled for non-Qwen3 models."""

    def test_non_qwen3_grammar_enabled_by_default(
        self, mock_detect: MagicMock, mock_openai: MagicMock
    ) -> None:
        """Non-Qwen3 models have grammar enabled by default."""
        from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLAMA_CPP_GRAMMAR", None)
            provider = LlamaCppChatProvider()
        assert provider._grammar_enabled is True
