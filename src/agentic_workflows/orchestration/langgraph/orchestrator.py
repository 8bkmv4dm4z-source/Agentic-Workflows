from __future__ import annotations

"""LangGraph orchestrator spine — module-level constants and LangGraphOrchestrator class.

This module is the authoritative source for:
- Module-level constants (_PIPELINE_TRACE_CAP, _HANDOFF_QUEUE_CAP, etc.)
- MemoizationPolicyViolation exception
- LangGraphOrchestrator class (inheriting from all four mixins)

The class only defines __init__, _compile_graph, prepare_state, and run().
All other methods are mixed in from the four *Mixin classes.

graph.py imports and re-exports everything from here for backward compatibility.

Anti-pattern: mixin modules must NOT import from this file at module level (circular).
They may use inline imports inside method bodies where needed.
"""

import contextlib  # noqa: F401 — used by lifecycle_nodes via self
import contextvars
import operator
import os
import typing
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentic_workflows.context.embedding_provider import EmbeddingProvider
    from agentic_workflows.storage.artifact_store import ArtifactStore
    from agentic_workflows.storage.mission_context_store import MissionContextStore

from agentic_workflows.logger import get_logger
from agentic_workflows.observability import (
    get_langfuse_callback_handler,
    observe,
    report_schema_compliance,  # noqa: F401 — re-exported for graph.py shim
)
from agentic_workflows.orchestration.langgraph import (
    action_parser,  # noqa: F401 — re-exported
    content_validator,  # noqa: F401 — re-exported
    directives,  # noqa: F401 — re-exported
    fallback_planner,  # noqa: F401 — re-exported
    memo_manager,  # noqa: F401 — re-exported
    mission_tracker,  # noqa: F401 — re-exported
    text_extractor,  # noqa: F401 — re-exported
)
from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.context_manager import ContextManager, MissionContext  # noqa: F401
from agentic_workflows.orchestration.langgraph.executor_node import ExecutorNodeMixin
from agentic_workflows.orchestration.langgraph.handoff import create_handoff, create_handoff_result  # noqa: F401
from agentic_workflows.orchestration.langgraph.lifecycle_nodes import LifecycleNodesMixin
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run  # noqa: F401
from agentic_workflows.orchestration.langgraph.mission_parser import (
    StructuredPlan,  # noqa: F401
    _adaptive_classifier_timeout,
    _adaptive_parser_timeout,
    parse_missions,
)
from agentic_workflows.orchestration.langgraph.model_router import (
    ModelRouter,
    RoutingSignals,  # noqa: F401
)
from agentic_workflows.orchestration.langgraph.planner_helpers import (
    PlannerHelpersMixin,
    _estimate_prompt_tokens,  # noqa: F401 — re-exported
    _read_directive_section,  # noqa: F401 — re-exported
    _select_prompt_tier,  # noqa: F401 — re-exported
)
from agentic_workflows.orchestration.langgraph.planner_node import PlannerNodeMixin
from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy
from agentic_workflows.orchestration.langgraph.provider import (
    ChatProvider,
    LlamaCppChatProvider,
    ProviderTimeoutError,  # noqa: F401 — re-exported
    _detect_llama_cpp_model,
    build_provider,
)
from agentic_workflows.orchestration.langgraph.specialist_evaluator import build_evaluator_subgraph
from agentic_workflows.orchestration.langgraph.specialist_executor import build_executor_subgraph
from agentic_workflows.orchestration.langgraph.state_schema import (
    AgentMessage,
    MemoEvent,  # noqa: F401 — re-exported
    RunResult,
    RunState,
    ensure_state_defaults,
    new_run_state,
    utc_now_iso,  # noqa: F401 — re-exported
)
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry
from agentic_workflows.tools.base import Tool  # noqa: F401 — re-exported

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    StateGraph: Any = None

try:
    from langchain_core.tools import StructuredTool  # noqa: F401
    from langgraph.prebuilt import ToolNode, tools_condition

    _TOOLNODE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TOOLNODE_AVAILABLE = False
    ToolNode = None  # type: ignore[assignment,misc]
    tools_condition = None  # type: ignore[assignment]
    StructuredTool = None  # type: ignore[assignment,misc]


_api_logger = get_logger("api_debug")


# ---------------------------------------------------------------------------
# Module-level helper functions (re-exported from graph.py shim)
# ---------------------------------------------------------------------------


def _build_port_url(base_url: str, port: int) -> str:
    """Return *base_url* with its port component replaced by *port*."""
    from urllib.parse import urlparse, urlunparse  # noqa: PLC0415

    parsed = urlparse(base_url)
    return urlunparse(parsed._replace(netloc=f"{parsed.hostname}:{port}"))


class MemoizationPolicyViolation(RuntimeError):
    """Raised when memoization policy retries are exhausted."""


# Fields in RunState that carry Annotated[list[T], operator.add] reducers.
# Sequential graph nodes mutate these lists in-place and return the full state
# dict; the reducer would double each list on every step unless we zero out the
# delta in the returned dict. Wrap every graph node with _sequential_node() to
# apply this correction automatically.
#
# W3-6: Auto-derived from RunState annotations at import time so that adding
# or removing an Annotated[list, operator.add] field is automatically reflected
# here — no manual maintenance required.


def _derive_annotated_list_fields() -> frozenset[str]:
    """Introspect RunState type hints and return fields with Annotated[list, operator.add]."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    result: set[str] = set()
    for name, hint in hints.items():
        if typing.get_origin(hint) is typing.Annotated:
            args = typing.get_args(hint)
            if len(args) >= 2 and args[1] is operator.add:
                result.add(name)
    return frozenset(result)


_ANNOTATED_LIST_FIELDS: frozenset[str] = _derive_annotated_list_fields()

# W2-5: Caps for unbounded list growth.
_PIPELINE_TRACE_CAP: int = 500
_HANDOFF_QUEUE_CAP: int = 50
_HANDOFF_RESULTS_CAP: int = 50

# W1-2: Per-run callback isolation via ContextVar.
# Each run()/streaming call sets its own callback list; concurrent runs in
# different threads each see their own value (ContextVar provides this
# automatically). Default is [] (no callbacks when credentials absent).
_active_callbacks_var: contextvars.ContextVar[list] = contextvars.ContextVar(
    "_active_callbacks"
)


def _sequential_node(fn):  # type: ignore[no-untyped-def]
    """Wrap a sequential LangGraph node so Annotated list fields return [] (empty delta).

    Background: RunState has four list fields annotated with operator.add so that
    parallel Send() branches can append without overwriting each other (Phase 4).
    In sequential operation every node returns the full state dict; the reducer
    would concatenate old+returned, doubling those lists on each graph step.
    By zeroing out those fields in the returned dict, operator.add(old, []) is a
    no-op — the in-place mutations already committed to state are preserved.
    """

    def wrapper(state: RunState) -> RunState:
        result = fn(state)
        if isinstance(result, dict):
            for field in _ANNOTATED_LIST_FIELDS:
                if field in result:
                    result[field] = []  # type: ignore[assignment]
        return result  # type: ignore[return-value]

    wrapper.__name__ = getattr(fn, "__name__", repr(fn))
    wrapper.__qualname__ = getattr(fn, "__qualname__", repr(fn))
    return wrapper


_ROLE_TOKEN_BUDGETS: dict[str, int] = {
    "classifier": 300,
    "planner": 2500,
    "executor": 300,
}


# ---------------------------------------------------------------------------
# Main orchestrator class
# ---------------------------------------------------------------------------


class LangGraphOrchestrator(
    PlannerHelpersMixin,
    PlannerNodeMixin,
    ExecutorNodeMixin,
    LifecycleNodesMixin,
):
    """State-graph orchestrator with memoization and checkpoint guardrails.

    Methods are distributed across four mixin classes:
    - PlannerHelpersMixin   — prompt builders, log helpers, env helpers, timeout
    - PlannerNodeMixin      — _plan_next_action() (the planning loop)
    - ExecutorNodeMixin     — _route_to_specialist(), _execute_action()
    - LifecycleNodesMixin   — _finalize(), _enforce_memo_policy(), shims, cache

    This class owns only __init__, _compile_graph, prepare_state, and run().
    """

    def __init__(
        self,
        *,
        provider: ChatProvider | None = None,
        fast_provider: ChatProvider | None = None,
        memo_store: SQLiteMemoStore | None = None,
        checkpoint_store: SQLiteCheckpointStore | None = None,
        policy: MemoizationPolicy | None = None,
        max_steps: int = 80,
        max_invalid_plan_retries: int = 8,
        max_provider_timeout_retries: int = 3,
        plan_call_timeout_seconds: float | None = None,
        max_content_validation_retries: int = 2,
        max_duplicate_tool_retries: int = 6,
        max_finish_rejections: int = 6,
        on_specialist_route: Any = None,
        embedding_provider: EmbeddingProvider | None = None,
        mission_context_store: MissionContextStore | None = None,
        artifact_store: ArtifactStore | None = None,
        fallback_provider: ChatProvider | None = None,
    ) -> None:
        self.provider = provider or build_provider()
        self._fallback_provider = fallback_provider
        self._consecutive_parse_failures = 0
        try:
            _ctx_size = self.provider.context_size()
        except AttributeError:
            # Graceful fallback for providers that predate context_size() — treat as full tier.
            _ctx_size = 32768
        self._prompt_tier = _select_prompt_tier(_ctx_size)
        # Alias-based dual providers: read env vars for strong/fast model aliases
        strong_alias = os.getenv("LLAMA_CPP_STRONG_ALIAS")
        fast_alias = os.getenv("LLAMA_CPP_FAST_ALIAS")
        if (strong_alias or fast_alias) and isinstance(self.provider, LlamaCppChatProvider):
            _strong = self.provider.with_alias(strong_alias) if strong_alias else self.provider
            _fast = self.provider.with_alias(fast_alias) if fast_alias else self.provider
            self._router = ModelRouter(strong_provider=_strong, fast_provider=_fast)
        else:
            self._router = ModelRouter(
                strong_provider=self.provider,
                fast_provider=fast_provider,
            )
        # Role-specific port routing (SYCL multi-server support)
        self._planner_provider: ChatProvider = self.provider
        self._executor_provider: ChatProvider = self.provider
        if isinstance(self.provider, LlamaCppChatProvider):
            _planner_port = os.getenv("LLAMA_CPP_PLANNER_PORT")
            _executor_port = os.getenv("LLAMA_CPP_EXECUTOR_PORT")
            if _planner_port:
                _p_url = _build_port_url(str(self.provider.client.base_url), int(_planner_port))
                if _detect_llama_cpp_model(_p_url) is not None:
                    self._planner_provider = self.provider.with_port(int(_planner_port))
                else:
                    _LOG_ORCH = get_logger("langgraph.orchestrator")
                    _LOG_ORCH.warning(
                        "LLAMA_CPP_PLANNER_PORT=%s server unreachable — using default server for planner",
                        _planner_port,
                    )
            if _executor_port:
                _e_url = _build_port_url(str(self.provider.client.base_url), int(_executor_port))
                if _detect_llama_cpp_model(_e_url) is not None:
                    self._executor_provider = self.provider.with_port(int(_executor_port))
                else:
                    _LOG_ORCH = get_logger("langgraph.orchestrator")
                    _LOG_ORCH.warning(
                        "LLAMA_CPP_EXECUTOR_PORT=%s server unreachable — using default server for executor",
                        _executor_port,
                    )
        self.memo_store = memo_store or SQLiteMemoStore()
        self.checkpoint_store = checkpoint_store or SQLiteCheckpointStore()
        self.policy = policy or MemoizationPolicy()
        self.logger = get_logger("langgraph.orchestrator")
        self.max_steps = max_steps
        self.max_invalid_plan_retries = max_invalid_plan_retries
        self.max_provider_timeout_retries = max_provider_timeout_retries
        self.plan_call_timeout_seconds = (
            plan_call_timeout_seconds
            if plan_call_timeout_seconds is not None
            else self._env_float("P1_PLAN_CALL_TIMEOUT_SECONDS", 45.0)
        )
        self.max_content_validation_retries = max_content_validation_retries
        self.max_duplicate_tool_retries = max_duplicate_tool_retries
        self.max_finish_rejections = max_finish_rejections
        self._on_specialist_route = on_specialist_route
        self._embedding_provider = embedding_provider
        self._mission_context_store = mission_context_store
        self._artifact_store = artifact_store
        self.context_manager = ContextManager(
            large_result_threshold=800,
            sliding_window_cap=20,
            mission_context_store=mission_context_store,
            embedding_provider=embedding_provider,
            artifact_store=artifact_store,
        )
        self.strict_single_action_mode = self._env_bool("P1_STRICT_SINGLE_ACTION", False)
        self.tools = build_tool_registry(
            self.memo_store,
            checkpoint_store=self.checkpoint_store,
            mission_context_store=mission_context_store,
            embedding_provider=embedding_provider,
        )
        self._action_json_schema: dict = self._build_action_json_schema()
        self._executor_subgraph = build_executor_subgraph(memo_store=self.memo_store)
        self._evaluator_subgraph = build_evaluator_subgraph()
        self._invalidate_known_poisoned_cache_entries()
        self.system_prompt = self._build_system_prompt()
        self._compiled = self._compile_graph()

    def _compile_graph(self):  # type: ignore[no-untyped-def]
        """Compile runtime graph topology: plan -> execute -> policy -> finalize.

        When P1_PROVIDER=anthropic, an additional 'tools' node backed by ToolNode
        (from langgraph-prebuilt) is added to the graph. The ToolNode path handles
        Anthropic tool-call format natively, replacing the XML/JSON envelope parser
        for that provider only.

        All other provider paths (ollama, openai, groq, scripted) use the existing
        ChatProvider pattern unchanged.
        """
        if StateGraph is None:
            raise RuntimeError(
                "langgraph is not installed. Add langgraph to requirements and install dependencies."
            )

        use_tool_node = (
            _TOOLNODE_AVAILABLE
            and os.getenv("P1_PROVIDER", "ollama").lower() == "anthropic"
        )

        builder = StateGraph(RunState)
        builder.add_node("plan", _sequential_node(self._plan_next_action))
        builder.add_node("execute", _sequential_node(self._route_to_specialist))
        builder.add_node("policy", _sequential_node(self._enforce_memo_policy))
        builder.add_node("finalize", _sequential_node(self._finalize))
        builder.add_edge(START, "plan")
        builder.add_edge("finalize", END)

        if use_tool_node:
            # Anthropic provider path: plan → tools (ToolNode) → plan ReAct loop.
            # tools_condition routes to "tools" when the last message contains
            # tool_calls (Anthropic native format), otherwise to END → "finalize".
            # The XML/JSON envelope parser (_parse_all_actions_json) is gated out
            # in _plan_next_action for this path.
            #
            # seen_tool_signatures deduplication is preserved via the
            # _dedup_then_tool_node() wrapper that runs BEFORE ToolNode executes.
            lc_tools = self._build_lc_tools()
            _tool_node = ToolNode(tools=lc_tools, handle_tool_errors=True)  # type: ignore[operator]
            dedup_node = self._dedup_then_tool_node(_tool_node)
            builder.add_node("tools", dedup_node)
            builder.add_conditional_edges(
                "plan",
                tools_condition,  # type: ignore[arg-type]
                {"tools": "tools", END: "finalize"},
            )
            builder.add_edge("tools", "plan")
            self.logger.info(
                "TOOLNODE WIRED provider=anthropic tools=%s handle_tool_errors=True",
                [t.name for t in lc_tools],
            )
        else:
            # Standard path: plan → execute → policy → plan loop.
            builder.add_node("clarify", self._clarify_node)
            builder.add_conditional_edges(
                "plan",
                self._route_after_plan,
                {"plan": "plan", "execute": "execute", "finish": "finalize", "clarify": "clarify"},
            )
            builder.add_edge("clarify", "finalize")
            builder.add_edge("execute", "policy")
            builder.add_edge("policy", "plan")

        return builder.compile()

    def prepare_state(
        self,
        user_input: str,
        run_id: str | None = None,
        *,
        prior_context: list[AgentMessage] | None = None,
        rerun_context: dict[str, Any] | None = None,
    ) -> RunState:
        """Single source of truth for run state initialization.

        Called by both run() and the SSE route handler. Encapsulates:
        new_run_state + prior_context merge + ensure_state_defaults +
        mission parsing + _write_shared_plan + initial checkpoint.save.
        """
        state = new_run_state(self.system_prompt, user_input, run_id=run_id)
        if prior_context:
            # Merge prior-context system content into the main system prompt
            # to avoid consecutive system messages (breaks Ollama JSON mode).
            prior_system_parts = [m["content"] for m in prior_context if m.get("role") == "system"]
            prior_conversation = [m for m in prior_context if m.get("role") != "system"]
            if prior_system_parts:
                for msg in state["messages"]:
                    if msg.get("role") == "system":
                        msg["content"] += "\n\n" + "\n".join(prior_system_parts)
                        break
            if prior_conversation:
                system_msgs = [m for m in state["messages"] if m.get("role") == "system"]
                user_msgs = [m for m in state["messages"] if m.get("role") != "system"]
                state["messages"] = system_msgs + prior_conversation + user_msgs
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        state["rerun_context"] = dict(rerun_context or {})
        structured_plan = parse_missions(
            user_input,
            timeout_seconds=_adaptive_parser_timeout(self.provider),
            classifier_provider=None,
            classifier_timeout=_adaptive_classifier_timeout(self.provider),
        )
        if structured_plan.parsing_method == "regex_fallback":
            state["structural_health"]["parser_timeout_count"] = (
                state["structural_health"].get("parser_timeout_count", 0) + 1
            )
        missions = structured_plan.flat_missions
        contracts = self._build_mission_contracts_from_plan(structured_plan, missions)
        state["missions"] = missions
        state["structured_plan"] = structured_plan.to_dict()
        state["mission_contracts"] = contracts
        state["mission_reports"] = self._initialize_mission_reports(missions, contracts=contracts)
        state["active_mission_index"] = -1
        state["active_mission_id"] = 0
        self._emit_trace(
            state,
            "parser",
            method=structured_plan.parsing_method,
            step_count=len(structured_plan.steps),
            flat_count=len(structured_plan.flat_missions),
            flat_previews=[m[:80] for m in structured_plan.flat_missions[:5]],
        )
        self._write_shared_plan(state)
        self.logger.info("RUN START run_id=%s missions=%s", state["run_id"], len(missions))
        _api_logger.info(
            "RUN_START run_id=%s missions=%d system_prompt_len=%d parser_timeout=%.1f classifier_timeout=%.1f",
            state["run_id"],
            len(missions),
            len(self.system_prompt),
            _adaptive_parser_timeout(self.provider),
            _adaptive_classifier_timeout(self.provider),
        )
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="init",
            state=state,
        )
        return state

    @observe("langgraph.orchestrator.run")
    def run(
        self,
        user_input: str,
        run_id: str | None = None,
        *,
        rerun_context: dict[str, Any] | None = None,
        prior_context: list[AgentMessage] | None = None,
    ) -> RunResult:
        """Execute one end-to-end run and return audit-friendly artifacts."""
        # W1-2: Set per-run callbacks via ContextVar for thread-level isolation.
        _handler = get_langfuse_callback_handler()
        _active_callbacks_var.set([_handler] if _handler else [])
        state = self.prepare_state(
            user_input,
            run_id=run_id,
            prior_context=prior_context,
            rerun_context=rerun_context,
        )
        final_state = self._compiled.invoke(
            state,
            config={"recursion_limit": self.max_steps * 9, "callbacks": _active_callbacks_var.get([])},
        )
        final_state = ensure_state_defaults(final_state, system_prompt=self.system_prompt)
        memo_entries = self.memo_store.list_entries(run_id=final_state["run_id"])
        derived_snapshot = self._build_derived_snapshot(final_state, memo_entries)
        self.logger.info(
            "DERIVED SNAPSHOT run_id=%s snapshot=%s", final_state["run_id"], derived_snapshot
        )
        return {
            "answer": final_state.get("final_answer", ""),
            "tools_used": final_state.get("tool_history", []),
            "mission_report": final_state.get("mission_reports", []),
            "run_id": final_state.get("run_id"),
            "memo_events": final_state.get("memo_events", []),
            "memo_store_entries": memo_entries,
            "derived_snapshot": derived_snapshot,
            "checkpoints": self.checkpoint_store.list_checkpoints(final_state["run_id"]),
            "audit_report": final_state.get("audit_report"),
            "state": final_state,
        }
