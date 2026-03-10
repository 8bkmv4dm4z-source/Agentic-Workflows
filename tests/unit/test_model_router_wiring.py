"""Unit tests for ModelRouter routing split and backward compatibility.

Tests verify:
- Planning/evaluation/error_recovery tasks route to strong provider
- Tool_selection/continuation tasks route to fast provider
- Single-provider mode has has_dual_providers=False
- LangGraphOrchestrator wires self._router correctly
"""
from __future__ import annotations

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.model_router import ModelRouter


class _StrongProvider:
    name = "strong"

    def generate(self, messages: list[dict]) -> str:  # type: ignore[type-arg]
        return '{"action":"finish","answer":"done"}'


class _FastProvider:
    name = "fast"

    def generate(self, messages: list[dict]) -> str:  # type: ignore[type-arg]
        return '{"action":"finish","answer":"done"}'


def test_model_router_routes_planning_to_strong() -> None:
    """Planning, evaluation, and error_recovery should all route to the strong provider."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    assert router.route("planning") is s, "planning should route to strong"
    assert router.route("evaluation") is s, "evaluation should route to strong"
    assert router.route("error_recovery") is s, "error_recovery should route to strong"


def test_model_router_routes_fast_tasks_to_fast() -> None:
    """Tool_selection and continuation should route to the fast provider."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    assert router.route("tool_selection") is f, "tool_selection should route to fast"
    assert router.route("continuation") is f, "continuation should route to fast"


def test_model_router_single_provider_compat() -> None:
    """Single-provider mode: has_dual_providers=False; all routes return same instance."""
    p = _StrongProvider()
    router = ModelRouter(strong_provider=p)

    assert router.has_dual_providers is False, "single-provider should have has_dual_providers=False"
    assert router.route("planning") is p, "planning should route to the only provider"
    assert router.route("tool_selection") is p, "tool_selection should route to the only provider"


def test_orchestrator_wires_router() -> None:
    """LangGraphOrchestrator(provider=...) should expose self._router."""
    orch = LangGraphOrchestrator(provider=_StrongProvider())

    assert hasattr(orch, "_router"), "_router attribute missing on orchestrator"
    assert orch._router.has_dual_providers is False, "single-provider mode: has_dual_providers must be False"


def test_orchestrator_dual_provider() -> None:
    """LangGraphOrchestrator(provider=strong, fast_provider=fast) should set has_dual_providers=True."""
    strong = _StrongProvider()
    fast = _FastProvider()
    orch = LangGraphOrchestrator(provider=strong, fast_provider=fast)

    assert orch._router.has_dual_providers is True, "dual-provider mode: has_dual_providers must be True"


# --- Intent-driven routing tests ---


def test_route_by_intent_complex_returns_strong() -> None:
    """route_by_intent with complexity='complex' should return strong provider."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    intent = {"complexity": "complex", "mission_type": "analysis", "confidence": 0.8, "source": "llm"}
    assert router.route_by_intent(intent_classification=intent) is s, "complex intent should route to strong"


def test_route_by_intent_simple_returns_fast() -> None:
    """route_by_intent with complexity='simple' should return fast provider."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    intent = {"complexity": "simple", "mission_type": "file_io", "confidence": 0.7, "source": "deterministic_fallback"}
    assert router.route_by_intent(intent_classification=intent) is f, "simple intent should route to fast"


def test_route_by_intent_none_falls_back_to_task_complexity() -> None:
    """route_by_intent with None intent should fall back to task_complexity routing."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    # With fallback_complexity="tool_selection" -> should route to fast
    assert router.route_by_intent(intent_classification=None, fallback_complexity="tool_selection") is f, (
        "None intent with tool_selection fallback should route to fast"
    )


def test_route_by_intent_none_planning_returns_strong() -> None:
    """route_by_intent with None intent AND fallback_complexity='planning' returns strong (backward compat)."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    assert router.route_by_intent(intent_classification=None, fallback_complexity="planning") is s, (
        "None intent with planning fallback should route to strong"
    )


def test_route_by_intent_integration_with_parse_missions() -> None:
    """Integration: intent classification dict -> route_by_intent -> correct provider."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    # Simulate what parse_missions produces for a simple task
    simple_intent = {"complexity": "simple", "mission_type": "file_io", "confidence": 0.6, "source": "deterministic_fallback"}
    assert router.route_by_intent(intent_classification=simple_intent) is f

    # Simulate what parse_missions produces for a complex task
    complex_intent = {"complexity": "complex", "mission_type": "multi_step", "confidence": 0.8, "source": "llm"}
    assert router.route_by_intent(intent_classification=complex_intent) is s

    # Simulate missing classification (backward compat)
    assert router.route_by_intent(intent_classification=None) is s  # defaults to "planning" -> strong
