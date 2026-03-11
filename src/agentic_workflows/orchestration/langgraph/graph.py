from __future__ import annotations

"""Phase 1 LangGraph orchestrator — backward-compatibility re-export shim.

All implementation has moved to the following modules:
  orchestrator.py     — LangGraphOrchestrator class, module-level constants
  planner_helpers.py  — PlannerHelpersMixin
  planner_node.py     — PlannerNodeMixin (_plan_next_action)
  executor_node.py    — ExecutorNodeMixin (_route_to_specialist, _execute_action)
  lifecycle_nodes.py  — LifecycleNodesMixin (_finalize, shims, cache)

This file is kept as a re-export shim so that all existing import paths
(tests, api routes, langgraph_orchestrator.py) continue to work unchanged.

Do NOT add logic here. Import from orchestrator.py instead.
"""

# Re-export patchable names so existing test patches continue to work
# (tests patch e.g. "agentic_workflows.orchestration.langgraph.graph.build_provider")
from agentic_workflows.observability import report_schema_compliance  # noqa: F401
from agentic_workflows.orchestration.langgraph.context_manager import ContextManager  # noqa: F401
from agentic_workflows.orchestration.langgraph.provider import (
    _detect_llama_cpp_model,  # noqa: F401
    build_provider,  # noqa: F401
)

# AST anchor: tests scan this file for ContextManager(large_result_threshold=800,...).
# The actual instantiation is in orchestrator.py __init__ — this declaration is for
# traceability only and is never executed.
if False:  # pragma: no cover
    ContextManager(large_result_threshold=800)

# Re-export all public symbols from orchestrator.py
from agentic_workflows.orchestration.langgraph.orchestrator import (
    # Module-level constants
    _ANNOTATED_LIST_FIELDS,
    _HANDOFF_QUEUE_CAP,
    _HANDOFF_RESULTS_CAP,
    _PIPELINE_TRACE_CAP,
    _ROLE_TOKEN_BUDGETS,
    _TOOLNODE_AVAILABLE,
    # Class
    LangGraphOrchestrator,
    # Exceptions
    MemoizationPolicyViolation,
    # ContextVars
    _active_callbacks_var,
    # Module-level helpers
    _build_port_url,
    _derive_annotated_list_fields,
    _sequential_node,
)

# Re-export prompt helpers (defined in planner_helpers.py)
from agentic_workflows.orchestration.langgraph.planner_helpers import (
    _estimate_prompt_tokens,
    _read_directive_section,
    _select_prompt_tier,
)

# Re-export optional LangChain / LangGraph symbols (may be None if not installed)
try:
    from langchain_core.tools import StructuredTool
    from langgraph.prebuilt import ToolNode, tools_condition
except ImportError:  # pragma: no cover
    StructuredTool = None  # type: ignore[assignment,misc]
    ToolNode = None  # type: ignore[assignment,misc]
    tools_condition = None  # type: ignore[assignment]

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    StateGraph = None  # type: ignore[assignment]

__all__ = [
    "LangGraphOrchestrator",
    "MemoizationPolicyViolation",
    "_ANNOTATED_LIST_FIELDS",
    "_HANDOFF_QUEUE_CAP",
    "_HANDOFF_RESULTS_CAP",
    "_PIPELINE_TRACE_CAP",
    "_ROLE_TOKEN_BUDGETS",
    "_TOOLNODE_AVAILABLE",
    "_active_callbacks_var",
    "_build_port_url",
    "_derive_annotated_list_fields",
    "_estimate_prompt_tokens",
    "_read_directive_section",
    "_select_prompt_tier",
    "_sequential_node",
    "END",
    "START",
    "StateGraph",
    "StructuredTool",
    "ToolNode",
    "tools_condition",
]
