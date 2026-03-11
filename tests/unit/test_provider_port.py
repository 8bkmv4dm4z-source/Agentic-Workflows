"""Unit tests for SYCL-01: with_port() factory and orchestrator port env var wiring."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

try:
    from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider
except ImportError:
    LlamaCppChatProvider = None  # type: ignore


def _make_provider() -> "LlamaCppChatProvider":
    """Create a LlamaCppChatProvider with no live server (LLAMA_CPP_MODEL=test)."""
    env = {
        "LLAMA_CPP_BASE_URL": "http://127.0.0.1:8080/v1",
        "LLAMA_CPP_MODEL": "test-model",
        "P1_PROVIDER": "llama-cpp",
    }
    with patch.dict(os.environ, env):
        # Patch _detect_llama_cpp_model so no HTTP call is made at __init__
        with patch(
            "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
            return_value="test-model",
        ):
            return LlamaCppChatProvider()


class TestWithPortFactory:
    def test_with_port_returns_new_provider(self) -> None:
        """with_port(9090) returns a different object, not self."""
        p = _make_provider()
        clone = p.with_port(9090)
        assert clone is not p
        assert isinstance(clone, LlamaCppChatProvider)

    def test_with_port_url_contains_new_port(self) -> None:
        """New provider's client base_url contains port 9090."""
        p = _make_provider()
        clone = p.with_port(9090)
        url = str(clone.client.base_url)
        assert "9090" in url, f"Expected port 9090 in URL, got: {url}"
        assert "8080" not in url, f"Original port 8080 should not be in clone URL: {url}"

    def test_with_port_preserves_model_and_settings(self) -> None:
        """Model name and timeout_seconds are copied to the clone."""
        p = _make_provider()
        clone = p.with_port(9090)
        assert clone.model == p.model
        assert clone.timeout_seconds == p.timeout_seconds
        assert clone.max_retries == p.max_retries
        assert clone.retry_backoff_seconds == p.retry_backoff_seconds
        assert clone._grammar_enabled == p._grammar_enabled

    def test_with_port_composes_with_with_alias(self) -> None:
        """provider.with_alias('planner').with_port(8081) returns provider pointing to 8081."""
        p = _make_provider()
        clone = p.with_alias("planner").with_port(8081)
        assert clone.model == "planner"
        url = str(clone.client.base_url)
        assert "8081" in url, f"Expected port 8081 in URL, got: {url}"


class TestOrchestratorPortEnvVarWiring:
    def test_orchestrator_reads_planner_port_env(self) -> None:
        """When LLAMA_CPP_PLANNER_PORT=9090 set, orchestrator._planner_provider URL has port 9090."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

        env = {
            "LLAMA_CPP_BASE_URL": "http://127.0.0.1:8080/v1",
            "LLAMA_CPP_MODEL": "test-model",
            "P1_PROVIDER": "llama-cpp",
            "LLAMA_CPP_PLANNER_PORT": "9090",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
                return_value="test-model",
            ):
                # _detect_llama_cpp_model imported into graph.py — patch there too
                with patch(
                    "agentic_workflows.orchestration.langgraph.graph._detect_llama_cpp_model",
                    return_value="test-model",
                ):
                    orch = LangGraphOrchestrator()
        planner_url = str(orch._planner_provider.client.base_url)
        assert "9090" in planner_url, f"Expected port 9090 in planner URL, got: {planner_url}"

    def test_orchestrator_reads_executor_port_env(self) -> None:
        """When LLAMA_CPP_EXECUTOR_PORT=9091 set, orchestrator._executor_provider URL has port 9091."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

        env = {
            "LLAMA_CPP_BASE_URL": "http://127.0.0.1:8080/v1",
            "LLAMA_CPP_MODEL": "test-model",
            "P1_PROVIDER": "llama-cpp",
            "LLAMA_CPP_EXECUTOR_PORT": "9091",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
                return_value="test-model",
            ):
                with patch(
                    "agentic_workflows.orchestration.langgraph.graph._detect_llama_cpp_model",
                    return_value="test-model",
                ):
                    orch = LangGraphOrchestrator()
        executor_url = str(orch._executor_provider.client.base_url)
        assert "9091" in executor_url, f"Expected port 9091 in executor URL, got: {executor_url}"

    def test_orchestrator_fallback_when_no_port_envs(self) -> None:
        """Without port env vars, _planner_provider and _executor_provider are the same object as provider."""
        from tests.conftest import ScriptedProvider

        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

        scripted = ScriptedProvider(responses=["{}"])
        # Clear port env vars so no routing happens
        env_overrides = {"LLAMA_CPP_PLANNER_PORT": "", "LLAMA_CPP_EXECUTOR_PORT": ""}
        with patch.dict(os.environ, env_overrides, clear=False):
            # Remove the keys if they exist
            for key in ("LLAMA_CPP_PLANNER_PORT", "LLAMA_CPP_EXECUTOR_PORT"):
                os.environ.pop(key, None)
            orch = LangGraphOrchestrator(provider=scripted)

        assert orch._planner_provider is orch.provider
        assert orch._executor_provider is orch.provider

    def test_orchestrator_warn_on_unreachable_port(self) -> None:
        """When configured port server is unreachable, logs warning and falls back (no hard fail)."""
        import logging

        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

        env = {
            "LLAMA_CPP_BASE_URL": "http://127.0.0.1:8080/v1",
            "LLAMA_CPP_MODEL": "test-model",
            "P1_PROVIDER": "llama-cpp",
            "LLAMA_CPP_PLANNER_PORT": "9099",  # unreachable port
        }
        with patch.dict(os.environ, env, clear=False):
            with patch(
                "agentic_workflows.orchestration.langgraph.provider._detect_llama_cpp_model",
                return_value="test-model",
            ):
                # _detect_llama_cpp_model in graph.py returns None → unreachable
                with patch(
                    "agentic_workflows.orchestration.langgraph.graph._detect_llama_cpp_model",
                    return_value=None,
                ):
                    # Must not raise — soft fallback
                    orch = LangGraphOrchestrator()
        # Falls back to default provider
        assert orch._planner_provider is orch.provider
