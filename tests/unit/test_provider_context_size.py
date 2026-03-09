"""Wave 0 stub tests for provider context_size() method.

All tests raise NotImplementedError — RED state until plan 07.6-01 implements context_size().
"""
from __future__ import annotations

import pytest

# Provider classes under test (must import without error)
from agentic_workflows.orchestration.langgraph.provider import (
    GroqChatProvider,
    LlamaCppChatProvider,
    OllamaChatProvider,
    OpenAIChatProvider,
)

# ScriptedProvider from test conftest
from tests.conftest import ScriptedProvider


class TestLlamaCppContextSize:
    def test_llama_cpp_context_size_default(self) -> None:
        """LlamaCppChatProvider.context_size() returns 8192 when LLAMA_CPP_N_CTX is unset."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_llama_cpp_context_size_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LlamaCppChatProvider.context_size() returns 4096 when LLAMA_CPP_N_CTX=4096."""
        raise NotImplementedError("stub — implement in plan 07.6-01")


class TestGroqContextSize:
    def test_groq_context_size(self) -> None:
        """GroqChatProvider.context_size() returns 32768."""
        raise NotImplementedError("stub — implement in plan 07.6-01")


class TestOpenAIContextSize:
    def test_openai_context_size(self) -> None:
        """OpenAIChatProvider.context_size() returns 128000."""
        raise NotImplementedError("stub — implement in plan 07.6-01")


class TestOllamaContextSize:
    def test_ollama_context_size_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OllamaChatProvider.context_size() returns 32768 when OLLAMA_NUM_CTX unset and num_ctx==0."""
        raise NotImplementedError("stub — implement in plan 07.6-01")


class TestScriptedProviderContextSize:
    def test_scripted_provider_context_size(self) -> None:
        """ScriptedProvider.context_size() returns 32768 (stays in full tier)."""
        raise NotImplementedError("stub — implement in plan 07.6-01")
