from __future__ import annotations

"""Cost-aware model router for multi-tier provider selection.

Implements signal-based routing: runtime signals (retry count, token budget,
mission type, intent classification) drive strong-vs-fast provider selection.

Threshold logic (route_by_signals):
- retry_count >= _RETRY_STRONG_THRESHOLD -> strong
- token_budget_remaining < _BUDGET_STRONG_THRESHOLD -> strong
- mission_type == "multi_step" -> strong
- intent complexity "complex" -> strong (tiebreaker)
- otherwise -> fast
"""

import warnings
from typing import TYPE_CHECKING, Any, Literal, TypedDict

if TYPE_CHECKING:
    from agentic_workflows.orchestration.langgraph.provider import ChatProvider


TaskComplexity = Literal[
    "planning",
    "evaluation",
    "error_recovery",
    "tool_selection",
    "continuation",
]

# Tasks routed to the strong (expensive) provider.
_STRONG_TASKS: frozenset[TaskComplexity] = frozenset({
    "planning",
    "evaluation",
    "error_recovery",
})

# Signal-based routing thresholds
_BUDGET_STRONG_THRESHOLD = 5000
_RETRY_STRONG_THRESHOLD = 2


class RoutingSignals(TypedDict):
    """Runtime signals used by route_by_signals() for model selection."""

    token_budget_remaining: int
    mission_type: str
    retry_count: int
    step: int
    intent_classification: dict[str, Any] | None


class ModelRouter:
    """Route tasks to strong or fast providers based on complexity or runtime signals."""

    def __init__(
        self,
        strong_provider: ChatProvider,
        fast_provider: ChatProvider | None = None,
    ) -> None:
        self._strong = strong_provider
        self._fast = fast_provider or strong_provider

    def route(self, task_complexity: TaskComplexity) -> ChatProvider:
        """Return the appropriate provider for the given task complexity."""
        if task_complexity in _STRONG_TASKS:
            return self._strong
        return self._fast

    def route_by_signals(self, signals: RoutingSignals) -> ChatProvider:
        """Route based on runtime signals with threshold-based logic.

        Priority order (first match wins):
        1. retry_count >= threshold -> strong (error recovery needs best model)
        2. token_budget_remaining < threshold -> strong (low budget = get it right)
        3. mission_type == "multi_step" -> strong (complex orchestration)
        4. intent complexity "complex" -> strong (tiebreaker)
        5. intent complexity "simple" -> fast
        6. default -> fast
        """
        # 1. High retry count -> strong
        if signals["retry_count"] >= _RETRY_STRONG_THRESHOLD:
            return self._strong

        # 2. Low budget -> strong
        if signals["token_budget_remaining"] < _BUDGET_STRONG_THRESHOLD:
            return self._strong

        # 3. Multi-step mission -> strong
        if signals["mission_type"] == "multi_step":
            return self._strong

        # 4-5. Intent complexity as tiebreaker
        intent = signals.get("intent_classification")
        if intent is not None:
            complexity = intent.get("complexity", "complex")
            if complexity == "simple":
                return self._fast
            return self._strong

        # 6. Default -> fast
        return self._fast

    def route_by_intent(
        self,
        intent_classification: dict[str, Any] | None = None,
        fallback_complexity: TaskComplexity = "planning",
    ) -> ChatProvider:
        """Deprecated: use route_by_signals() instead.

        Kept as backward-compat shim until all callers migrate (Plan 03).
        Delegates to route_by_signals with default signal values.
        """
        warnings.warn(
            "route_by_intent() is deprecated; use route_by_signals()",
            DeprecationWarning,
            stacklevel=2,
        )
        signals: RoutingSignals = {
            "token_budget_remaining": 100_000,
            "mission_type": "unknown",
            "retry_count": 0,
            "step": 0,
            "intent_classification": intent_classification,
        }
        if intent_classification is not None:
            return self.route_by_signals(signals)
        # No intent: fall back to task complexity routing
        return self.route(fallback_complexity)

    @property
    def has_dual_providers(self) -> bool:
        """True when strong and fast providers are distinct instances."""
        return self._strong is not self._fast
