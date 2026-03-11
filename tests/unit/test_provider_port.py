"""Wave 0 test stubs for SYCL-01: with_port() factory and orchestrator port env var wiring.

All tests raise NotImplementedError — RED state. Implement in Plan 02.
"""
from __future__ import annotations

import pytest

try:
    from agentic_workflows.orchestration.langgraph.provider import LlamaCppChatProvider
except ImportError:
    LlamaCppChatProvider = None  # type: ignore


class TestWithPortFactory:
    def test_with_port_returns_new_provider(self) -> None:
        """with_port(9090) returns a different object, not self."""
        raise NotImplementedError("stub — implement in Plan 02")

    def test_with_port_url_contains_new_port(self) -> None:
        """New provider's client base_url contains port 9090."""
        raise NotImplementedError("stub — implement in Plan 02")

    def test_with_port_preserves_model_and_settings(self) -> None:
        """Model name and timeout_seconds are copied to the clone."""
        raise NotImplementedError("stub — implement in Plan 02")

    def test_with_port_composes_with_with_alias(self) -> None:
        """provider.with_alias('planner').with_port(8081) returns provider pointing to 8081."""
        raise NotImplementedError("stub — implement in Plan 02")


class TestOrchestratorPortEnvVarWiring:
    def test_orchestrator_reads_planner_port_env(self) -> None:
        """When LLAMA_CPP_PLANNER_PORT=9090 set, orchestrator._planner_provider URL has port 9090."""

        def _test() -> None:
            from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator  # noqa: F401

        _test()
        raise NotImplementedError("stub — implement in Plan 02")

    def test_orchestrator_reads_executor_port_env(self) -> None:
        """When LLAMA_CPP_EXECUTOR_PORT=9091 set, orchestrator._executor_provider URL has port 9091."""

        def _test() -> None:
            from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator  # noqa: F401

        _test()
        raise NotImplementedError("stub — implement in Plan 02")

    def test_orchestrator_fallback_when_no_port_envs(self) -> None:
        """Without port env vars, _planner_provider and _executor_provider are the same object as provider."""

        def _test() -> None:
            from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator  # noqa: F401

        _test()
        raise NotImplementedError("stub — implement in Plan 02")

    def test_orchestrator_warn_on_unreachable_port(self) -> None:
        """When configured port server is unreachable, logs warning and falls back (no hard fail)."""

        def _test() -> None:
            from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator  # noqa: F401

        _test()
        raise NotImplementedError("stub — implement in Plan 02")
