"""Unit tests for ModelRouter routing split and backward compatibility.

Tests verify:
- Planning/evaluation/error_recovery tasks route to strong provider
- Tool_selection/continuation tasks route to fast provider
- Single-provider mode has has_dual_providers=False
- LangGraphOrchestrator wires self._router correctly
- Signal-based routing via route_by_signals()
- route_by_intent() deprecated shim still works (backward compat until Plan 03)
"""
from __future__ import annotations

import warnings

import pytest

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


# --- Signal-based routing tests (route_by_signals) ---


def _make_signals(
    *,
    retry_count: int = 0,
    token_budget_remaining: int = 50_000,
    mission_type: str = "unknown",
    step: int = 1,
    intent_classification: dict | None = None,
) -> dict:
    """Helper to build a RoutingSignals-compatible dict."""
    return {
        "token_budget_remaining": token_budget_remaining,
        "mission_type": mission_type,
        "retry_count": retry_count,
        "step": step,
        "intent_classification": intent_classification,
    }


@pytest.mark.parametrize(
    "signals_kwargs, expected_provider_name, reason",
    [
        # Retry threshold: retry_count >= 2 -> strong
        ({"retry_count": 2, "token_budget_remaining": 50_000}, "strong", "retry threshold"),
        ({"retry_count": 5, "token_budget_remaining": 50_000}, "strong", "retry well above threshold"),
        # Budget threshold: budget < 5000 -> strong
        ({"retry_count": 0, "token_budget_remaining": 3000}, "strong", "budget below threshold"),
        ({"retry_count": 0, "token_budget_remaining": 4999}, "strong", "budget just below threshold"),
        # Mission type: multi_step -> strong
        ({"retry_count": 0, "token_budget_remaining": 50_000, "mission_type": "multi_step"}, "strong", "multi_step mission"),
        # Intent complexity: complex -> strong
        (
            {"retry_count": 0, "token_budget_remaining": 50_000, "mission_type": "single_step", "intent_classification": {"complexity": "complex"}},
            "strong",
            "complex intent tiebreaker",
        ),
        # Intent complexity: simple -> fast
        (
            {"retry_count": 0, "token_budget_remaining": 50_000, "mission_type": "single_step", "intent_classification": {"complexity": "simple"}},
            "fast",
            "simple intent routes fast",
        ),
        # Default: unknown mission, no intent -> fast
        ({"retry_count": 0, "token_budget_remaining": 50_000, "mission_type": "unknown"}, "fast", "default routes fast"),
        # No intent, single_step -> fast
        ({"retry_count": 0, "token_budget_remaining": 50_000, "mission_type": "single_step"}, "fast", "single_step no intent routes fast"),
        # Retry overrides everything else
        (
            {"retry_count": 5, "token_budget_remaining": 50_000, "mission_type": "single_step", "intent_classification": {"complexity": "simple"}},
            "strong",
            "retry overrides simple intent",
        ),
        # Budget threshold: exact boundary (5000) -> fast (not < 5000)
        ({"retry_count": 0, "token_budget_remaining": 5000}, "fast", "budget at exact threshold routes fast"),
    ],
    ids=[
        "retry_threshold",
        "retry_high",
        "budget_low",
        "budget_just_below",
        "multi_step_mission",
        "complex_intent",
        "simple_intent",
        "default_fast",
        "single_step_no_intent",
        "retry_overrides_simple",
        "budget_exact_boundary",
    ],
)
def test_route_by_signals(signals_kwargs: dict, expected_provider_name: str, reason: str) -> None:
    """Parametrized test for signal-based routing logic."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    signals = _make_signals(**signals_kwargs)
    result = router.route_by_signals(signals)

    expected = s if expected_provider_name == "strong" else f
    assert result is expected, f"Expected {expected_provider_name} for {reason}, got {result.name}"


def test_route_by_signals_has_dual_providers() -> None:
    """has_dual_providers still works with signal-based routing."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)
    assert router.has_dual_providers is True

    single = ModelRouter(strong_provider=s)
    assert single.has_dual_providers is False


# --- Deprecated route_by_intent backward-compat tests ---


def test_route_by_intent_deprecated_emits_warning() -> None:
    """route_by_intent() emits DeprecationWarning when called."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        router.route_by_intent(intent_classification={"complexity": "complex"})
        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "route_by_signals" in str(w[0].message)


def test_route_by_intent_complex_returns_strong() -> None:
    """route_by_intent with complexity='complex' should return strong provider (backward compat)."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    intent = {"complexity": "complex", "mission_type": "analysis", "confidence": 0.8, "source": "llm"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert router.route_by_intent(intent_classification=intent) is s


def test_route_by_intent_simple_returns_fast() -> None:
    """route_by_intent with complexity='simple' should return fast provider (backward compat)."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    intent = {"complexity": "simple", "mission_type": "file_io", "confidence": 0.7, "source": "deterministic_fallback"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert router.route_by_intent(intent_classification=intent) is f


def test_route_by_intent_none_falls_back_to_task_complexity() -> None:
    """route_by_intent with None intent should fall back to task_complexity routing."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert router.route_by_intent(intent_classification=None, fallback_complexity="tool_selection") is f


def test_route_by_intent_none_planning_returns_strong() -> None:
    """route_by_intent with None intent AND fallback_complexity='planning' returns strong (backward compat)."""
    s = _StrongProvider()
    f = _FastProvider()
    router = ModelRouter(strong_provider=s, fast_provider=f)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert router.route_by_intent(intent_classification=None, fallback_complexity="planning") is s
