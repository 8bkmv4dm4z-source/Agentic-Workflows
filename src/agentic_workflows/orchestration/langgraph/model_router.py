from __future__ import annotations

"""Cost-aware model router for multi-tier provider selection.

Implements a 70/30 routing split: lightweight tasks (tool selection,
continuation) use a fast/cheap provider; complex tasks (planning,
evaluation, error recovery) use a strong provider.

Stub implementation — both providers can be the same instance initially.
When a second provider is configured, routing decisions take effect.
"""

from typing import TYPE_CHECKING, Literal

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


class ModelRouter:
    """Route tasks to strong or fast providers based on complexity classification."""

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

    @property
    def has_dual_providers(self) -> bool:
        """True when strong and fast providers are distinct instances."""
        return self._strong is not self._fast
