"""Tests for provider context_size() method — implemented in plan 07.6-01."""
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
    def test_llama_cpp_context_size_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LlamaCppChatProvider.context_size() returns 8192 when LLAMA_CPP_N_CTX is unset."""
        monkeypatch.delenv("LLAMA_CPP_N_CTX", raising=False)
        provider = LlamaCppChatProvider.__new__(LlamaCppChatProvider)
        assert provider.context_size() == 8192

    def test_llama_cpp_context_size_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LlamaCppChatProvider.context_size() returns 4096 when LLAMA_CPP_N_CTX=4096."""
        monkeypatch.setenv("LLAMA_CPP_N_CTX", "4096")
        provider = LlamaCppChatProvider.__new__(LlamaCppChatProvider)
        assert provider.context_size() == 4096


class TestGroqContextSize:
    def test_groq_context_size(self) -> None:
        """GroqChatProvider.context_size() returns 32768."""
        provider = GroqChatProvider.__new__(GroqChatProvider)
        assert provider.context_size() == 32768


class TestOpenAIContextSize:
    def test_openai_context_size(self) -> None:
        """OpenAIChatProvider.context_size() returns 128000."""
        provider = OpenAIChatProvider.__new__(OpenAIChatProvider)
        assert provider.context_size() == 128000


class TestOllamaContextSize:
    def test_ollama_context_size_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OllamaChatProvider.context_size() returns 32768 when OLLAMA_NUM_CTX unset and num_ctx==0."""
        monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
        provider = OllamaChatProvider.__new__(OllamaChatProvider)
        provider.num_ctx = 0
        assert provider.context_size() == 32768

    def test_ollama_context_size_from_num_ctx(self) -> None:
        """OllamaChatProvider.context_size() returns num_ctx when set to a positive value."""
        provider = OllamaChatProvider.__new__(OllamaChatProvider)
        provider.num_ctx = 16384
        assert provider.context_size() == 16384


class TestScriptedProviderContextSize:
    def test_scripted_provider_context_size(self) -> None:
        """ScriptedProvider.context_size() returns 32768 (stays in full tier)."""
        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        assert provider.context_size() == 32768
