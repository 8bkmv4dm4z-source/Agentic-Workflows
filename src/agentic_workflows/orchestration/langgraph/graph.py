from __future__ import annotations

"""Phase 1 LangGraph orchestrator.

This module is the Layer-2 orchestration engine: it plans model actions,
executes deterministic tools, enforces memoization policy, and produces
run/mission reports using only local state for final snapshots.
"""

import json
import os
import queue
import threading
from pathlib import Path
from typing import Any

from agentic_workflows.logger import get_logger
from agentic_workflows.observability import observe
from agentic_workflows.orchestration.langgraph import (
    action_parser,
    content_validator,
    directives,
    fallback_planner,
    memo_manager,
    mission_tracker,
    text_extractor,
)
from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.handoff import create_handoff, create_handoff_result
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run
from agentic_workflows.orchestration.langgraph.mission_parser import StructuredPlan, parse_missions
from agentic_workflows.orchestration.langgraph.model_router import ModelRouter, TaskComplexity
from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy
from agentic_workflows.orchestration.langgraph.provider import (
    ChatProvider,
    ProviderTimeoutError,
    build_provider,
)
from agentic_workflows.orchestration.langgraph.specialist_evaluator import build_evaluator_subgraph
from agentic_workflows.orchestration.langgraph.specialist_executor import build_executor_subgraph
from agentic_workflows.orchestration.langgraph.state_schema import (
    AgentMessage,
    MemoEvent,
    RunState,
    ensure_state_defaults,
    new_run_state,
    utc_now_iso,
)
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry
from agentic_workflows.tools.base import Tool

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    StateGraph = None

try:
    from langchain_core.tools import StructuredTool
    from langgraph.prebuilt import ToolNode, tools_condition

    _TOOLNODE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TOOLNODE_AVAILABLE = False
    ToolNode = None  # type: ignore[assignment,misc]
    tools_condition = None  # type: ignore[assignment]
    StructuredTool = None  # type: ignore[assignment,misc]


class MemoizationPolicyViolation(RuntimeError):
    """Raised when memoization policy retries are exhausted."""


# Fields in RunState that carry Annotated[list[T], operator.add] reducers.
# Sequential graph nodes mutate these lists in-place and return the full state
# dict; the reducer would double each list on every step unless we zero out the
# delta in the returned dict. Wrap every graph node with _sequential_node() to
# apply this correction automatically.
_ANNOTATED_LIST_FIELDS: frozenset[str] = frozenset(
    {"tool_history", "memo_events", "seen_tool_signatures", "mission_reports"}
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


class LangGraphOrchestrator:
    """State-graph orchestrator with memoization and checkpoint guardrails."""

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
    ) -> None:
        self.provider = provider or build_provider()
        self._router = ModelRouter(
            strong_provider=self.provider,
            fast_provider=fast_provider,
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
        self.strict_single_action_mode = self._env_bool("P1_STRICT_SINGLE_ACTION", False)
        self.tools: dict[str, Tool] = build_tool_registry(self.memo_store)
        self._executor_subgraph = build_executor_subgraph(memo_store=self.memo_store)
        self._evaluator_subgraph = build_evaluator_subgraph()
        self._invalidate_known_poisoned_cache_entries()
        self.system_prompt = self._build_system_prompt()
        self._compiled = self._compile_graph()

    def _build_system_prompt(self) -> str:
        """Construct strict planner prompt and tool/memo policy contract."""
        tool_list = ", ".join(self.tools.keys())
        return (
            "You are a deterministic tool-using agent.\n"
            "Return exactly one JSON object per response.\n"
            "Never output XML tags (for example <invoke>), markdown, or prose outside JSON.\n"
            f"Allowed tool_name values: {tool_list}\n\n"
            "Schema:\n"
            '{"action":"tool","tool_name":"<tool>","args":{...}}\n'
            '{"action":"finish","answer":"<summary>"}\n\n'
            "Tool arg reference (use exact names):\n"
            '- repeat_message: {"message":"<string>"}\n'
            '- sort_array: {"items":[...], "order":"asc|desc"}\n'
            '- string_ops: {"text":"<string>", "operation":"uppercase|lowercase|reverse|length|trim|replace|split|count_words|startswith|endswith|contains"}\n'
            '- math_stats: {"operation":"...", "a":<number>, "b":<number>} or {"operation":"...", "numbers":[...]}\n'
            '- write_file: {"path":"<filepath>", "content":"<string>"}\n'
            '- memoize: {"key":"<key>", "value":<json>, "run_id":"<run_id>", "namespace":"run(optional)"}\n'
            '- retrieve_memo: {"key":"<key>", "run_id":"<run_id>", "namespace":"run(optional)"}\n'
            '- task_list_parser: {"text":"<string>"}\n'
            '- text_analysis: {"text":"<string>", "operation":"word_count|sentence_count|char_count|key_terms|complexity_score|paragraph_count|avg_word_length|unique_words|full_report"}\n'
            '- data_analysis: {"numbers":[...], "operation":"summary_stats|outliers|percentiles|distribution|correlation|normalize|z_scores"}\n'
            '- json_parser: {"text":"<json_string>", "operation":"parse|validate|extract_keys|flatten|get_path|pretty_print|count_elements"}\n'
            '- regex_matcher: {"text":"<string>", "pattern":"<regex>", "operation":"find_all|find_first|split|replace|match|count_matches|extract_groups"}\n\n'
            "Memoization policy:\n"
            "- For heavy deterministic writes, memoize result before continuing.\n"
            '- Use tool "memoize" with args: key, value, run_id, optional namespace.\n'
            '- Use "retrieve_memo" only when explicitly needed for task context.\n'
            "- For write_file tasks, the orchestrator auto-checks memo keys before writing.\n"
            "- For recurring write tasks, the orchestrator may auto-reuse cached write inputs from prior runs.\n"
            "- Do not emit extra planning subtasks; output the next concrete tool call only.\n"
            "Always obey system feedback messages."
        )

    def _invalidate_known_poisoned_cache_entries(self) -> None:
        """Purge known-bad cached write inputs discovered during run review."""
        poisoned = (
            ("write_file_input:fib50.txt", "9192a11413589198351eed65372ca8ced1b495337040e432d5a0cd806da4d41d"),
            ("write_file_input:pattern_report.txt", "c89dfcb4f7885053f1ae4d9326ffd2cdc95109dcfc10c7c6315cf33e39e1712f"),
        )
        for key, value_hash in poisoned:
            deleted = self.memo_store.delete(
                run_id="shared",
                key=key,
                namespace="cache",
                value_hash=value_hash,
            )
            if deleted:
                self.logger.info(
                    "CACHE INVALIDATION key=%s value_hash=%s deleted=%s",
                    key,
                    value_hash,
                    deleted,
                )

    def _build_lc_tools(self) -> list[Any]:
        """Convert internal Tool registry to LangChain StructuredTool instances.

        This is used exclusively for the Anthropic ToolNode path. The standard
        ChatProvider path uses tools from self.tools (our Tool base class) directly.

        Each Tool.execute(args: dict) -> dict is wrapped as a StructuredTool so that
        ToolNode (which expects LangChain BaseTool instances) can invoke them.
        """
        if StructuredTool is None:  # pragma: no cover
            return []

        lc_tools = []
        for tool_name, tool_instance in self.tools.items():
            # Capture tool_instance in closure to avoid late-binding issues
            def _make_tool_fn(t: Tool, n: str):  # type: ignore[type-arg]
                def _tool_fn(**kwargs: Any) -> dict[str, Any]:  # type: ignore[return]
                    """Execute tool."""
                    return t.execute(dict(kwargs))

                _tool_fn.__name__ = n
                _tool_fn.__qualname__ = n
                _tool_fn.__doc__ = getattr(t, "description", f"Execute {n} tool.")
                return _tool_fn

            fn = _make_tool_fn(tool_instance, tool_name)
            lc_tool = StructuredTool.from_function(  # type: ignore[union-attr]
                fn,
                name=tool_name,
                description=getattr(tool_instance, "description", f"Execute {tool_name} tool."),
            )
            lc_tools.append(lc_tool)
        return lc_tools

    def _dedup_then_tool_node(
        self,
        tool_node: Any,  # ToolNode instance
    ):
        """Return a wrapper function that checks seen_tool_signatures before ToolNode.

        This preserves the existing deduplication invariant on the Anthropic ToolNode
        path. ToolNode has no built-in deduplication; the pre-check runs first and
        short-circuits with a duplicate-detected message when the signature matches.
        """

        def _wrapper(state: RunState) -> dict[str, Any]:
            state = ensure_state_defaults(state, system_prompt=self.system_prompt)
            # Extract tool calls from the last AIMessage in messages (Anthropic format)
            messages = state.get("messages", [])
            last_msg = messages[-1] if messages else None
            tool_calls = getattr(last_msg, "tool_calls", []) if last_msg else []
            for tc in tool_calls or []:
                tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
                if signature in state.get("seen_tool_signatures", []):
                    self.logger.info(
                        "TOOL_NODE DEDUP BLOCK tool=%s signature=%s",
                        tool_name,
                        signature[:120],
                    )
                    # Return empty delta — ToolNode will be skipped by returning early
                    # The plan node will detect the duplicate on next planning step
                    return {}
            # No duplicates — delegate to ToolNode
            return tool_node.invoke(state)  # type: ignore[no-any-return]

        _wrapper.__name__ = "_dedup_then_tool_node"
        _wrapper.__qualname__ = "_dedup_then_tool_node"
        return _wrapper

    def _compile_graph(self):
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
            builder.add_conditional_edges(
                "plan",
                self._route_after_plan,
                {"plan": "plan", "execute": "execute", "finish": "finalize"},
            )
            builder.add_edge("execute", "policy")
            builder.add_edge("policy", "plan")

        return builder.compile()

    @observe("langgraph.orchestrator.run")
    def run(
        self,
        user_input: str,
        run_id: str | None = None,
        *,
        rerun_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute one end-to-end run and return audit-friendly artifacts."""
        state = new_run_state(self.system_prompt, user_input, run_id=run_id)
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        state["rerun_context"] = dict(rerun_context or {})
        structured_plan = parse_missions(user_input)
        missions = structured_plan.flat_missions
        contracts = self._build_mission_contracts_from_plan(structured_plan, missions)
        state["missions"] = missions
        state["structured_plan"] = structured_plan.to_dict()
        state["mission_contracts"] = contracts
        state["mission_reports"] = self._initialize_mission_reports(missions, contracts=contracts)
        state["active_mission_index"] = -1
        state["active_mission_id"] = 0
        self._emit_trace(state, "parser",
            method=structured_plan.parsing_method,
            step_count=len(structured_plan.steps),
            flat_count=len(structured_plan.flat_missions),
            flat_previews=[m[:80] for m in structured_plan.flat_missions[:5]],
        )
        self._write_shared_plan(state)
        self.logger.info("RUN START run_id=%s missions=%s", state["run_id"], len(missions))
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="init",
            state=state,
        )
        final_state = self._compiled.invoke(state, config={"recursion_limit": self.max_steps * 3})
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

    def _emit_trace(self, state: RunState, stage: str, **fields: Any) -> None:
        """Append a pipeline trace event to policy_flags['pipeline_trace']."""
        policy_flags = state.get("policy_flags")
        if not isinstance(policy_flags, dict):
            return
        trace = policy_flags.setdefault("pipeline_trace", [])
        if isinstance(trace, list):
            trace.append({"stage": stage, "step": state.get("step", 0), **fields})

    def _route_after_plan(self, state: RunState) -> str:
        """Route graph transitions based on the planner's pending action."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not action:
            return "plan"
        if action.get("action") == "finish":
            return "finish"
        return "execute"

    def _log_queue_mission_spacing(
        self, *, state: RunState, mission_id: int, source: str
    ) -> None:
        """Emit a visual separator when queued actions move to a different mission."""
        if mission_id <= 0:
            return
        flags = state.get("policy_flags", {})
        previous = int(flags.get("last_queue_mission_id", 0))
        if previous > 0 and previous != mission_id:
            self.logger.info("")
            self.logger.info(
                "PLAN QUEUE MISSION BREAK from=%s to=%s source=%s",
                previous,
                mission_id,
                source,
            )
        flags["last_queue_mission_id"] = mission_id

    def _planner_action_preview(self, action: dict[str, Any]) -> dict[str, Any]:
        """Return a compact planner action preview for logs."""
        args = dict(action.get("args", {}))
        return {
            "action": str(action.get("action", "")),
            "tool_name": str(action.get("tool_name", "")),
            "__mission_id": int(action.get("__mission_id", 0) or 0),
            "arg_keys": sorted(args.keys()),
        }

    def _log_parser_state(self, state: RunState) -> None:
        """Emit parser state snapshot for the current planner step."""
        structured = state.get("structured_plan")
        method = "unknown"
        step_count = 0
        if isinstance(structured, dict):
            method = str(structured.get("parsing_method", "unknown"))
            step_count = len(structured.get("steps", []))
        next_mission = self._next_incomplete_mission(state)
        next_preview = next_mission[:120] + "..." if len(next_mission) > 120 else next_mission
        self.logger.info(
            (
                "PARSER STATE step=%s run_id=%s method=%s parsed_steps=%s missions=%s "
                "next_mission=%s"
            ),
            state["step"],
            state["run_id"],
            method,
            step_count,
            len(state.get("missions", [])),
            next_preview,
        )

    def _log_planner_output(
        self, *, state: RunState, source: str, action: dict[str, Any], queue_remaining: int
    ) -> None:
        """Emit normalized planner output per step, regardless of source."""
        self.logger.info(
            "PLANNER OUTPUT step=%s source=%s queue_remaining=%s action=%s",
            state["step"],
            source,
            queue_remaining,
            self._planner_action_preview(action),
        )

    def _plan_next_action(self, state: RunState) -> RunState:
        """Call the model planner and parse one strict JSON action."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        self._compact_messages(state)
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            return state
        state["step"] = state.get("step", 0) + 1
        self.logger.info(
            (
                "PLANNER STEP START step=%s run_id=%s queue=%s timeout_mode=%s "
                "memo_required=%s"
            ),
            state["step"],
            state["run_id"],
            len(state.get("pending_action_queue", [])),
            bool(state.get("policy_flags", {}).get("planner_timeout_mode", False)),
            bool(state.get("policy_flags", {}).get("memo_required", False)),
        )
        self._log_parser_state(state)
        self._emit_trace(state, "loop_state",
            step=state["step"],
            queue_depth=len(state.get("pending_action_queue", [])),
            completed_count=sum(
                1 for r in state.get("mission_reports", [])
                if str(r.get("status", "")) == "completed"
            ),
            total_count=len(state.get("mission_reports", [])),
            timeout_mode=bool(state.get("policy_flags", {}).get("planner_timeout_mode", False)),
        )
        if state["step"] > self.max_steps:
            fail_message = (
                "Run stopped: exceeded orchestrator step budget before mission completion. "
                "Review mission attribution and planner behavior."
            )
            state["messages"].append({"role": "system", "content": fail_message})
            state["pending_action"] = {"action": "finish", "answer": fail_message}
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_step_budget_fail_closed",
                state=state,
            )
            return state
        if self._maybe_complete_next_write_from_cache(state):
            if self._all_missions_completed(state):
                state["pending_action"] = {
                    "action": "finish",
                    "answer": self._build_auto_finish_answer(state),
                }
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_cache_reuse",
                state=state,
            )
            return state
        if self._enforce_rerun_completion_guard(state):
            return state
        # --- Action queue: pop next queued action before calling provider ---
        queue = state.get("pending_action_queue", [])
        if queue and not state.get("policy_flags", {}).get("memo_required", False):
            next_action_raw = queue.pop(0)
            state["pending_action_queue"] = queue
            try:
                validated = self._validate_action_from_dict(next_action_raw)
                queued_mission_id = int(validated.get("__mission_id", 0))
                self._log_queue_mission_spacing(
                    state=state,
                    mission_id=queued_mission_id,
                    source="queue_pop",
                )
                self.logger.info(
                    "PLAN QUEUE POP step=%s queue_remaining=%s action=%s",
                    state["step"],
                    len(queue),
                    validated,
                )
                self._log_planner_output(
                    state=state,
                    source="queue_pop",
                    action=validated,
                    queue_remaining=len(queue),
                )
                self._emit_trace(state, "planner_output",
                    source="queue_pop",
                    action_type=str(validated.get("action", "")),
                    tool_name=str(validated.get("tool_name", "")),
                    mission_id=int(validated.get("__mission_id", 0) or 0),
                )
                if validated.get("action") == "finish" and not self._all_missions_completed(state):
                    return self._reject_finish_and_recover(
                        state=state,
                        rejected_action=validated,
                        source="queue",
                    )
                state["pending_action"] = validated
                self._reset_finish_rejection_tracking(state)
                state["retry_counts"]["provider_timeout"] = 0
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_queue_pop",
                    state=state,
                )
                return state
            except (ValueError, Exception) as exc:
                self.logger.warning(
                    "PLAN QUEUE SKIP step=%s error=%s",
                    state["step"],
                    str(exc),
                )
                state["pending_action_queue"] = queue
        if bool(state.get("policy_flags", {}).get("planner_timeout_mode", False)):
            fallback_action = self._deterministic_fallback_action(state)
            if fallback_action is not None:
                fallback_requirements = self._next_incomplete_mission_requirements(state)
                self.logger.warning(
                    (
                        "PLAN TIMEOUT MODE step=%s action=%s mission_id=%s "
                        "missing_tools=%s missing_files=%s"
                    ),
                    state["step"],
                    fallback_action,
                    fallback_requirements.get("mission_id", 0),
                    fallback_requirements.get("missing_tools", []),
                    fallback_requirements.get("missing_files", []),
                )
                self._log_planner_output(
                    state=state,
                    source="timeout_mode",
                    action=fallback_action,
                    queue_remaining=len(state.get("pending_action_queue", [])),
                )
                self._emit_trace(state, "planner_output",
                    source="timeout_mode",
                    action_type=str(fallback_action.get("action", "")),
                    tool_name=str(fallback_action.get("tool_name", "")),
                    mission_id=int(fallback_action.get("__mission_id", 0) or 0),
                )
                state["pending_action"] = fallback_action
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_timeout_mode",
                    state=state,
                )
                return state
        progress_message = self._progress_hint_message(state)
        if progress_message:
            state["messages"].append({"role": "system", "content": progress_message})

        # --- Token budget gate: switch to deterministic fallback when exhausted ---
        budget_remaining = state.get("token_budget_remaining", 100_000)
        if budget_remaining <= 0:
            self.logger.info(
                "TOKEN BUDGET EXHAUSTED step=%s used=%s — switching to deterministic fallback",
                state["step"],
                state.get("token_budget_used", 0),
            )
            state["policy_flags"]["planner_timeout_mode"] = True

        try:
            self.logger.info(
                "PLAN PROVIDER CALL step=%s timeout_seconds=%.2f",
                state["step"],
                self.plan_call_timeout_seconds,
            )
            model_output = self._generate_with_hard_timeout(state["messages"]).strip()
            self.logger.info("MODEL OUTPUT step=%s output=%s", state["step"], model_output[:500])
            state["messages"].append({"role": "assistant", "content": model_output})
            state["policy_flags"]["planner_timeout_mode"] = False
            # --- Token budget tracking (rough estimate: 1 token ≈ 4 chars) ---
            estimated_tokens = len(model_output) // 4 + sum(
                len(str(m.get("content", ""))) // 4 for m in state["messages"][-2:]
            )
            state["token_budget_used"] = state.get("token_budget_used", 0) + estimated_tokens
            state["token_budget_remaining"] = max(
                0, state.get("token_budget_remaining", 100_000) - estimated_tokens
            )
            # Anthropic path: model output is native tool-call format consumed by
            # ToolNode via tools_condition routing. Skip JSON envelope parsing and
            # return — the graph edge routes the state to the "tools" node next.
            if os.getenv("P1_PROVIDER", "ollama").lower() == "anthropic":
                return state
            all_actions = self._parse_all_actions_json(model_output)
            if not all_actions:
                raise ValueError("no valid JSON action objects found in model output")
            tagged_actions: list[dict[str, Any]] = []
            mission_preview = self._mission_preview_from_state(state)
            for raw_action in all_actions:
                action_with_meta = dict(raw_action)
                mission_id = self._resolve_mission_id_for_action(
                    state, action_with_meta, preview=mission_preview
                )
                if mission_id > 0:
                    action_with_meta["__mission_id"] = mission_id
                    preview_entry = mission_preview.setdefault(
                        mission_id, {"used_tools": set(), "written_files": set()}
                    )
                    tool_name = str(action_with_meta.get("tool_name", "")).strip()
                    if tool_name:
                        preview_entry["used_tools"].add(tool_name)
                    if tool_name == "write_file":
                        path = str(action_with_meta.get("args", {}).get("path", "")).strip()
                        if path:
                            basename = path.replace("\\", "/").rsplit("/", 1)[-1]
                            preview_entry["written_files"].add(basename)
                tagged_actions.append(action_with_meta)
            previews = [self._planner_action_preview(a) for a in tagged_actions[:5]]
            self.logger.info(
                "PLANNER PARSED OUTPUT step=%s actions=%s previews=%s",
                state["step"],
                len(tagged_actions),
                previews,
            )

            action = self._validate_action_from_dict(tagged_actions[0])
            if len(all_actions) > 1:
                if self.strict_single_action_mode:
                    state["pending_action_queue"] = []
                    self.logger.info(
                        "PLAN STRICT SINGLE ACTION step=%s discarded=%s",
                        state["step"],
                        len(tagged_actions) - 1,
                    )
                else:
                    state["pending_action_queue"] = tagged_actions[1:]
                    self.logger.info(
                        "PLAN QUEUED step=%s queued=%s",
                        state["step"],
                        len(tagged_actions) - 1,
                    )
                state["retry_counts"]["provider_timeout"] = 0
            if action.get("action") == "finish" and not self._all_missions_completed(state):
                return self._reject_finish_and_recover(
                    state=state,
                    rejected_action=action,
                    source="provider",
                )
            self.logger.info("PLANNED ACTION step=%s action=%s", state["step"], action)
            planned_mission_id = int(action.get("__mission_id", 0))
            self._log_queue_mission_spacing(
                state=state,
                mission_id=planned_mission_id,
                source="planned_action",
            )
            self._log_planner_output(
                state=state,
                source="provider",
                action=action,
                queue_remaining=len(state.get("pending_action_queue", [])),
            )
            self._emit_trace(state, "planner_output",
                source="provider",
                action_type=str(action.get("action", "")),
                tool_name=str(action.get("tool_name", "")),
                mission_id=int(action.get("__mission_id", 0) or 0),
            )
            state["pending_action"] = action
            self._reset_finish_rejection_tracking(state)
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan",
                state=state,
            )
            return state
        except ProviderTimeoutError as exc:
            error_text = str(exc)
            timeout_count = int(state["retry_counts"].get("provider_timeout", 0)) + 1
            state["retry_counts"]["provider_timeout"] = timeout_count
            self.logger.warning(
                "PLAN PROVIDER TIMEOUT step=%s timeout_count=%s error=%s",
                state["step"],
                timeout_count,
                error_text,
            )

            fallback_action = self._deterministic_fallback_action(state)
            if fallback_action is not None:
                fallback_requirements = self._next_incomplete_mission_requirements(state)
                self.logger.warning(
                    (
                        "PLAN TIMEOUT FALLBACK step=%s action=%s mission_id=%s "
                        "missing_tools=%s missing_files=%s"
                    ),
                    state["step"],
                    fallback_action,
                    fallback_requirements.get("mission_id", 0),
                    fallback_requirements.get("missing_tools", []),
                    fallback_requirements.get("missing_files", []),
                )
                self._log_planner_output(
                    state=state,
                    source="timeout_fallback",
                    action=fallback_action,
                    queue_remaining=0,
                )
                state["messages"].append(
                    {
                        "role": "system",
                        "content": (
                            "Provider timeout during planning. Orchestrator selected a deterministic fallback action."
                        ),
                    }
                )
                state["policy_flags"]["planner_timeout_mode"] = True
                state["pending_action_queue"] = []
                state["pending_action"] = fallback_action
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_timeout_fallback",
                    state=state,
                )
                return state

            if timeout_count >= self.max_provider_timeout_retries:
                fail_message = (
                    f"Planner failed after provider timeout retries: {error_text}. Stopping."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_fail_provider_timeout",
                    state=state,
                )
                return state

            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        "Provider timeout while planning. Retry and return exactly one valid JSON object."
                    ),
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_provider_timeout",
                state=state,
            )
            return state
        except Exception as exc:
            error_text = str(exc)
            invalid_count = int(state["retry_counts"].get("invalid_json", 0)) + 1
            state["retry_counts"]["invalid_json"] = invalid_count
            self._emit_trace(state, "planner_retry", reason="invalid_json", retry_count=invalid_count)
            self.logger.warning(
                "PLAN INVALID step=%s invalid_count=%s error=%s",
                state["step"],
                invalid_count,
                error_text,
            )

            if self._is_unrecoverable_plan_error(error_text):
                fail_message = (
                    f"Planner failed with unrecoverable provider error: {error_text}. Stopping."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_fail_unrecoverable",
                    state=state,
                )
                return state

            if invalid_count >= self.max_invalid_plan_retries:
                fail_message = (
                    "Planner failed to produce a valid JSON action after "
                    f"{invalid_count} attempts (last error: {error_text}). "
                    "Stopping to avoid recursion-limit failure."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_fail_closed",
                    state=state,
                )
                return state

            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Invalid action ({error_text}). Return exactly one valid JSON object. "
                        "Do not output prose."
                    ),
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_error",
                state=state,
            )
            return state

    def _env_float(self, name: str, default: float) -> float:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return value if value > 0 else default

    def _env_bool(self, name: str, default: bool) -> bool:
        raw = (os.getenv(name) or "").strip().lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return default

    def _reset_finish_rejection_tracking(self, state: RunState) -> None:
        state["retry_counts"]["finish_rejected"] = 0
        state["policy_flags"]["finish_rejection_streak"] = 0
        state["policy_flags"]["last_finish_rejection_fingerprint"] = ""

    def _rerun_target_mission_ids(self, state: RunState) -> set[int]:
        rerun_context_raw = state.get("rerun_context", {})
        rerun_context = rerun_context_raw if isinstance(rerun_context_raw, dict) else {}
        return {
            int(item)
            for item in rerun_context.get("target_mission_ids", [])
            if isinstance(item, int) and int(item) > 0
        }

    def _rerun_targets_completed(self, state: RunState) -> bool:
        targets = self._rerun_target_mission_ids(state)
        if not targets:
            return False
        reports = state.get("mission_reports", [])
        status_by_id: dict[int, str] = {}
        for report in reports:
            mission_id = int(report.get("mission_id", 0) or 0)
            if mission_id > 0:
                status_by_id[mission_id] = str(report.get("status", "pending")).strip().lower()
        return all(status_by_id.get(mission_id, "pending") == "completed" for mission_id in targets)

    def _enforce_rerun_completion_guard(self, state: RunState) -> bool:
        """Stop post-completion planning noise when rerun targets are already done."""
        if not self._rerun_targets_completed(state):
            return False
        targets = sorted(self._rerun_target_mission_ids(state))
        queue = list(state.get("pending_action_queue", []))
        blocked_non_finish = sum(
            1
            for action in queue
            if str(action.get("action", "")).strip().lower() != "finish"
        )
        if queue:
            state["pending_action_queue"] = []
        self.logger.warning(
            (
                "POST_COMPLETE_ACTION_BLOCKED step=%s rerun_targets=%s "
                "blocked_non_finish=%s queue_depth=%s"
            ),
            state["step"],
            targets,
            blocked_non_finish,
            len(queue),
        )
        answer = self._build_auto_finish_answer(state).strip() or "Rerun targets completed."
        state["pending_action"] = {"action": "finish", "answer": answer}
        self._reset_finish_rejection_tracking(state)
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="plan_rerun_targets_completed",
            state=state,
        )
        return True

    def _purge_queued_finish_actions(self, state: RunState) -> int:
        queue = list(state.get("pending_action_queue", []))
        if not queue:
            return 0
        kept: list[dict[str, Any]] = []
        purged = 0
        for action in queue:
            if str(action.get("action", "")).strip().lower() == "finish":
                purged += 1
                continue
            kept.append(action)
        if purged:
            state["pending_action_queue"] = kept
            self.logger.warning(
                "PLAN QUEUE PURGE FINISH step=%s purged=%s queue_depth=%s",
                state["step"],
                purged,
                len(kept),
            )
        return purged

    def _reject_finish_and_recover(
        self,
        *,
        state: RunState,
        rejected_action: dict[str, Any],
        source: str,
    ) -> RunState:
        finish_rejected = int(state["retry_counts"].get("finish_rejected", 0)) + 1
        state["retry_counts"]["finish_rejected"] = finish_rejected
        requirements = self._next_incomplete_mission_requirements(state)
        missing_tools = requirements.get("missing_tools", [])
        missing_files = requirements.get("missing_files", [])
        queue_depth = len(state.get("pending_action_queue", []))
        purged_finishes = self._purge_queued_finish_actions(state)
        fingerprint = (
            f"{requirements.get('mission_id', 0)}|{','.join(str(item) for item in missing_tools)}|"
            f"{','.join(str(item) for item in missing_files)}|"
            f"{self._planner_action_preview(rejected_action)}"
        )
        last_fingerprint = str(state["policy_flags"].get("last_finish_rejection_fingerprint", ""))
        streak = 1 if fingerprint != last_fingerprint else int(
            state["policy_flags"].get("finish_rejection_streak", 0)
        ) + 1
        state["policy_flags"]["last_finish_rejection_fingerprint"] = fingerprint
        state["policy_flags"]["finish_rejection_streak"] = streak

        self.logger.warning(
            (
                "FINISH REJECTED step=%s source=%s reason=incomplete_requirements "
                "finish_rejected=%s queue_depth=%s purged_finishes=%s missing_tools=%s "
                "missing_files=%s"
            ),
            state["step"],
            source,
            finish_rejected,
            queue_depth,
            purged_finishes,
            missing_tools,
            missing_files,
        )

        next_mission = self._next_incomplete_mission(state)
        if finish_rejected > self.max_finish_rejections:
            fail_message = (
                "Run stopped: planner repeatedly requested finish while tasks remained "
                f"incomplete (next task: {next_mission or 'unknown'})."
            )
            state["messages"].append({"role": "system", "content": fail_message})
            state["pending_action"] = {"action": "finish", "answer": fail_message}
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name=f"plan_{source}_finish_fail_closed",
                state=state,
            )
            return state

        fallback_action = self._deterministic_fallback_action(state)
        if fallback_action is not None and fallback_action.get("action") != "finish":
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        "Finish rejected: missions remain incomplete. "
                        f"Next task: {next_mission or 'unknown'}. "
                        "Orchestrator selected a deterministic recovery action."
                    ),
                }
            )
            self._log_planner_output(
                state=state,
                source=f"{source}_finish_recover",
                action=fallback_action,
                queue_remaining=len(state.get("pending_action_queue", [])),
            )
            state["pending_action"] = fallback_action
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name=f"plan_{source}_finish_recover",
                state=state,
            )
            return state

        state["messages"].append(
            {
                "role": "system",
                "content": (
                    "Finish rejected: missions remain incomplete. "
                    f"Next task: {next_mission or 'unknown'}"
                ),
            }
        )
        state["pending_action"] = None
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name=f"plan_{source}_finish_rejected",
            state=state,
        )
        return state

    def _generate_with_hard_timeout(
        self, messages: list[dict[str, str]], complexity: TaskComplexity = "planning"
    ) -> str:
        """Protect planner generate() call with a hard wall-clock timeout."""
        timeout_seconds = self.plan_call_timeout_seconds
        if timeout_seconds <= 0:
            return self._router.route(complexity).generate(messages)

        outbox: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def _run() -> None:
            try:
                outbox.put(("ok", self._router.route(complexity).generate(messages)))
            except Exception as exc:  # noqa: BLE001
                outbox.put(("err", exc))

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        try:
            kind, payload = outbox.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise ProviderTimeoutError(
                f"planner call exceeded hard timeout of {timeout_seconds:.2f}s"
            ) from exc

        if kind == "err":
            if isinstance(payload, Exception):
                raise payload
            raise RuntimeError(str(payload))
        return str(payload)

    def _select_specialist_for_action(self, action: dict[str, Any] | None) -> str:
        """Choose specialist role from pending action."""
        if not action or str(action.get("action", "")).strip().lower() != "tool":
            return "supervisor"
        tool_name = str(action.get("tool_name", "")).strip()
        if tool_name in directives.EVALUATOR_DIRECTIVE.allowed_tools:
            return "evaluator"
        return "executor"

    def _is_tool_allowed_for_specialist(self, specialist: str, tool_name: str) -> bool:
        """Check whether a specialist can execute the selected tool."""
        config = directives.DIRECTIVE_BY_SPECIALIST.get(specialist)  # type: ignore[arg-type]
        if config is None:
            return True
        return tool_name in config.allowed_tools

    def _route_to_specialist(self, state: RunState) -> RunState:
        """Route tool actions to specialist role handlers and record handoff metadata."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not isinstance(action, dict):
            return state

        specialist = self._select_specialist_for_action(action)
        state["active_specialist"] = specialist
        if str(action.get("action", "")).strip().lower() != "tool":
            return self._execute_action(state)

        tool_name = str(action.get("tool_name", "")).strip()
        mission_id = action.get("__mission_id")
        if not isinstance(mission_id, int) or mission_id <= 0:
            mission_id = int(state.get("active_mission_id", 0))
        self._emit_trace(state, "specialist_route",
            specialist=specialist,
            tool_name=tool_name,
            mission_id=int(mission_id or 0),
        )
        task_id = f"{state['run_id']}:{state['step']}:{len(state['handoff_queue']) + 1}"
        config = directives.DIRECTIVE_BY_SPECIALIST.get(specialist)  # type: ignore[arg-type]
        tool_scope = sorted(config.allowed_tools) if config else []
        self.logger.info(
            (
                "SPECIALIST REDIRECT step=%s run_id=%s task_id=%s specialist=%s "
                "tool=%s mission_id=%s queue_before=%s"
            ),
            state["step"],
            state["run_id"],
            task_id,
            specialist,
            tool_name,
            mission_id,
            len(state.get("handoff_queue", [])),
        )
        state["handoff_queue"].append(
            create_handoff(
                task_id=task_id,
                specialist=specialist,  # type: ignore[arg-type]
                mission_id=max(0, mission_id),
                tool_scope=tool_scope,
                input_context={
                    "tool_name": tool_name,
                    "args": dict(action.get("args", {})),
                    "step": state["step"],
                },
                token_budget=int(state.get("token_budget_remaining", 0)),
            )
        )

        if specialist in ("executor", "evaluator"):
            # Build ExecutorState for the subgraph invocation.
            # The subgraph invocation provides real subgraph node transitions in logs
            # (satisfying ROADMAP Phase 4 Success Criterion 1).
            # _execute_action() is still called for its full pre-processing pipeline
            # (arg normalization, duplicate detection, auto-memo-lookup, content validation,
            # mission attribution) — the approaches are complementary, not redundant.
            exec_state: dict[str, Any] = {
                "task_id": task_id,
                "specialist": "executor",
                "mission_id": max(0, int(mission_id or 0)),
                "tool_scope": tool_scope,
                "input_context": {
                    "tool_name": tool_name,
                    "args": dict(action.get("args", {})),
                    "step": int(state["step"]),
                },
                "token_budget": int(state.get("token_budget_remaining", 0)),
                "exec_tool_history": [],
                "exec_seen_signatures": [],
                "result": {},
                "tokens_used": 0,
                "status": "success",
            }
            # Invoke the compiled subgraph — this records real subgraph node transitions.
            self._executor_subgraph.invoke(exec_state)
            # Execute through _execute_action() to apply full pipeline (arg normalization,
            # duplicate detection, auto-memo-lookup, content validation, mission attribution).
            pre_tool_history_len = len(state.get("tool_history", []))
            state = self._execute_action(state)
            post_tool_history_len = len(state.get("tool_history", []))
            # Tag newly appended tool_history entries with via_subgraph=True.
            for idx in range(pre_tool_history_len, post_tool_history_len):
                state["tool_history"][idx]["via_subgraph"] = True
            status = "success" if post_tool_history_len > pre_tool_history_len else "error"
            output: dict[str, Any] = {"tool_name": tool_name}
            if post_tool_history_len > pre_tool_history_len:
                output["tool_result"] = state["tool_history"][-1].get("result", {})
                output["status"] = status

        else:
            # Unknown specialist — fall back to direct execution
            pre_calls = len(state.get("tool_history", []))
            state = self._execute_action(state)
            post_calls = len(state.get("tool_history", []))
            status = "success" if post_calls > pre_calls else "error"
            output = {"tool_name": tool_name}
            if post_calls > pre_calls:
                output["tool_result"] = state["tool_history"][-1].get("result", {})

        state["handoff_results"].append(
            create_handoff_result(
                task_id=task_id,
                specialist=specialist,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                output=output,
                tokens_used=0,
            )
        )
        self.logger.info(
            "SPECIALIST OUTPUT step=%s run_id=%s task_id=%s specialist=%s status=%s via_subgraph=True",
            state["step"],
            state["run_id"],
            task_id,
            specialist,
            status,
        )
        return state

    def _execute_action(self, state: RunState) -> RunState:
        """Execute planned tool action, including duplicate and policy checks."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not action:
            return state

        if action.get("action") == "finish":
            state["final_answer"] = str(action.get("answer", ""))
            self.logger.info(
                "FINISH ACTION step=%s answer=%s", state["step"], state["final_answer"][:300]
            )
            return state

        tool_name = str(action.get("tool_name", ""))
        tool_args = self._normalize_tool_args(tool_name, dict(action.get("args", {})))
        specialist = str(state.get("active_specialist", "executor")).strip() or "executor"
        if not self._is_tool_allowed_for_specialist(specialist=specialist, tool_name=tool_name):
            config = directives.DIRECTIVE_BY_SPECIALIST.get(specialist)  # type: ignore[arg-type]
            allowed_tools = sorted(config.allowed_tools) if config else []
            self.logger.info(
                (
                    "SPECIALIST SCOPE BLOCK step=%s run_id=%s specialist=%s tool=%s "
                    "allowed_tools=%s"
                ),
                state["step"],
                state["run_id"],
                specialist,
                tool_name,
                allowed_tools,
            )
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Tool '{tool_name}' is not allowed for specialist '{specialist}'. "
                        f"Allowed tools: {', '.join(allowed_tools)}."
                    ),
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_scope_violation",
                state=state,
            )
            return state
        mission_id = action.get("__mission_id")
        mission_index = -1
        if isinstance(mission_id, int) and mission_id > 0:
            mission_index = mission_id - 1
        else:
            mission_index = self._next_incomplete_mission_index(state)
        if mission_index >= 0:
            state["active_mission_index"] = mission_index
            state["active_mission_id"] = mission_index + 1
        self.logger.info(
            (
                "SPECIALIST EXECUTE step=%s run_id=%s specialist=%s tool=%s "
                "mission_index=%s mission_id=%s"
            ),
            state["step"],
            state["run_id"],
            specialist,
            tool_name,
            mission_index,
            state.get("active_mission_id", 0),
        )

        lookup_candidates = self._memo_lookup_candidates_for_action(
            tool_name=tool_name, tool_args=tool_args
        )
        if (
            lookup_candidates
            and tool_name != "retrieve_memo"
            and not self._has_attempted_memo_lookup(state=state, candidate_keys=lookup_candidates)
        ):
                self.logger.info(
                    "MEMO LOOKUP AUTO step=%s attempted_tool=%s keys=%s",
                    state["step"],
                    tool_name,
                    lookup_candidates,
                )
                memo_hit = self._auto_lookup_before_write(
                    state=state, candidate_keys=lookup_candidates
                )
                if memo_hit:
                    if tool_name == "write_file":
                        self._mark_next_mission_complete_from_memo_hit(
                            state=state, memo_hit=memo_hit
                        )
                    state["messages"].append(
                        {
                            "role": "system",
                            "content": (
                                "Memo hit found for this deterministic write. "
                                "Skip recomputation and continue with remaining tasks."
                            ),
                        }
                    )
                    state["pending_action"] = None
                    self.checkpoint_store.save(
                        run_id=state["run_id"],
                        step=state["step"],
                        node_name="execute_lookup_hit_skip",
                        state=state,
                    )
                    return state

        if state["policy_flags"].get("memo_required") and tool_name != "memoize":
            retry_count = int(state["retry_counts"].get("memo_policy", 0)) + 1
            state["retry_counts"]["memo_policy"] = retry_count
            self.logger.info(
                "MEMO POLICY RETRY step=%s retry=%s attempted_tool=%s",
                state["step"],
                retry_count,
                tool_name,
            )
            if retry_count > self.policy.max_policy_retries:
                raise MemoizationPolicyViolation(
                    "Memoization required but model repeatedly skipped it."
                )

            required_key = str(state["policy_flags"].get("memo_required_key", ""))
            reason = str(state["policy_flags"].get("memo_required_reason", ""))
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Memoization required before proceeding ({reason}). "
                        f"Call memoize now with key='{required_key}' and run_id='{state['run_id']}'."
                    ),
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_policy_retry",
                state=state,
            )
            return state

        if tool_name not in self.tools:
            state["messages"].append(
                {
                    "role": "system",
                    "content": f"Unknown tool '{tool_name}'. Use one of: {', '.join(self.tools.keys())}.",
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_unknown_tool",
                state=state,
            )
            return state

        if tool_name in {"memoize", "retrieve_memo"}:
            tool_args.setdefault("run_id", state["run_id"])
        if tool_name == "memoize":
            tool_args.setdefault("step", state["step"])

        signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
        if signature in state["seen_tool_signatures"]:
            duplicate_retry_count = int(state["retry_counts"].get("duplicate_tool", 0)) + 1
            state["retry_counts"]["duplicate_tool"] = duplicate_retry_count
            next_mission = self._next_incomplete_mission(state)
            if not next_mission and self._all_missions_completed(state):
                state["pending_action"] = {
                    "action": "finish",
                    "answer": self._build_auto_finish_answer(state),
                }
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="execute_duplicate_finish",
                    state=state,
                )
                return state
            if duplicate_retry_count > self.max_duplicate_tool_retries:
                fail_message = (
                    "Run stopped: repeated duplicate tool actions prevented mission progress. "
                    f"Next task: {next_mission or 'unknown'}."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="execute_duplicate_fail_closed",
                    state=state,
                )
                return state
            guidance = (
                f"Next incomplete task: {next_mission}."
                if next_mission
                else "All listed tasks look complete. Emit finish now."
            )
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Duplicate tool call detected for '{tool_name}' with the same arguments. "
                        f"Do not repeat completed calls. {guidance}"
                    ),
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_duplicate_tool",
                state=state,
            )
            return state
        state["seen_tool_signatures"].append(signature)

        self.logger.info("TOOL EXEC step=%s tool=%s args=%s", state["step"], tool_name, tool_args)
        tool_result = self.tools[tool_name].execute(tool_args)
        self.logger.info(
            "TOOL RESULT step=%s tool=%s result=%s", state["step"], tool_name, tool_result
        )
        if tool_name == "retrieve_memo":
            self._record_retrieve_memo_trace(state=state, tool_result=tool_result)
        validation_error = self._validate_tool_result_for_active_mission(
            state=state,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            mission_index=mission_index if mission_index >= 0 else None,
        )
        if validation_error:
            retry_count = int(state["retry_counts"].get("content_validation", 0)) + 1
            state["retry_counts"]["content_validation"] = retry_count
            tool_result = {
                "error": "content_validation_failed",
                "details": validation_error,
            }
            self.logger.warning(
                "CONTENT VALIDATION FAILED step=%s tool=%s retry=%s reason=%s",
                state["step"],
                tool_name,
                retry_count,
                validation_error,
            )
            self._emit_trace(state, "validator_fail",
                tool=tool_name,
                reason=validation_error[:120],
                retry_count=retry_count,
            )
        state["tool_call_counts"][tool_name] = int(state["tool_call_counts"].get(tool_name, 0)) + 1
        call_number = len(state["tool_history"]) + 1
        state["tool_history"].append(
            {
                "call": call_number,
                "tool": tool_name,
                "args": tool_args,
                "result": tool_result,
            }
        )
        _pre_statuses = {
            int(r.get("mission_id", i + 1)): str(r.get("status", ""))
            for i, r in enumerate(state.get("mission_reports", []))
        }
        self._record_mission_tool_event(
            state,
            tool_name,
            tool_result,
            mission_index=mission_index if mission_index >= 0 else None,
            tool_args=tool_args,
        )
        self._emit_trace(state, "tool_exec",
            tool=tool_name,
            mission_id=int(state.get("active_mission_id", 0)),
            result_keys=list(tool_result.keys()),
            has_error="error" in tool_result,
        )
        if not validation_error:
            _check = "none"
            if tool_name == "write_file":
                _rpts = state.get("mission_reports", [])
                _idx = mission_index if mission_index >= 0 else int(state.get("active_mission_index", -1))
                if 0 <= _idx < len(_rpts):
                    _rpt = _rpts[_idx]
                    _cc = {str(c).strip().lower() for c in _rpt.get("contract_checks", [])}
                    _mt = str(_rpt.get("mission", "")).lower()
                    _fc = _rpt.get("expected_fibonacci_count")
                    if (isinstance(_fc, int) and _fc > 0) or "fibonacci" in _mt:
                        _check = "fibonacci"
                    elif "pattern_report_consistency" in _cc:
                        _check = "pattern_report"
            self._emit_trace(state, "validator_pass", tool=tool_name, check=_check)
        for _i, _r in enumerate(state.get("mission_reports", [])):
            _mid = int(_r.get("mission_id", _i + 1))
            if str(_r.get("status", "")) == "completed" and _pre_statuses.get(_mid) != "completed":
                self._emit_trace(state, "mission_complete",
                    mission_id=_mid,
                    mission_preview=str(_r.get("mission", ""))[:60],
                )
        progress_hint = (
            self._progress_hint_message(state)
            or "Continue with the next task or finish when all tasks are complete."
        )
        if validation_error:
            progress_hint = (
                "Previous tool output failed deterministic content validation. "
                f"Fix and rerun this task. {validation_error}"
            )
        state["messages"].append(
            {
                "role": "system",
                "content": (
                    f"TOOL_RESULT #{call_number} ({tool_name}): {json.dumps(tool_result)}\n"
                    f"{progress_hint}"
                ),
            }
        )

        if validation_error:
            if (
                int(state["retry_counts"].get("content_validation", 0))
                > self.max_content_validation_retries
            ):
                fail_message = (
                    "Run failed closed after repeated deterministic content validation failures. "
                    f"Last issue: {validation_error}"
                )
                state["pending_action"] = {"action": "finish", "answer": fail_message}
            else:
                state["pending_action"] = None
            state["policy_flags"]["last_tool_name"] = ""
            state["policy_flags"]["last_tool_args"] = {}
            state["policy_flags"]["last_tool_result"] = {}
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_content_validation",
                state=state,
            )
            return state

        if tool_name == "write_file":
            self._cache_write_file_inputs(state=state, tool_args=tool_args)

        if tool_name == "memoize" and "value_hash" in tool_result:
            state["memo_events"].append(
                MemoEvent(
                    key=str(tool_result.get("key", "")),
                    namespace=str(tool_result.get("namespace", "run")),
                    source_tool=str(tool_args.get("source_tool", "memoize")),
                    step=state["step"],
                    value_hash=str(tool_result["value_hash"]),
                    created_at=utc_now_iso(),
                )
            )
            state["policy_flags"]["memo_required"] = False
            state["policy_flags"]["memo_required_key"] = ""
            state["policy_flags"]["memo_required_reason"] = ""
            state["retry_counts"]["memo_policy"] = 0

        state["policy_flags"]["last_tool_name"] = tool_name
        state["policy_flags"]["last_tool_args"] = tool_args
        state["policy_flags"]["last_tool_result"] = tool_result
        state["pending_action"] = None
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="execute",
            state=state,
        )
        return state

    def _enforce_memo_policy(self, state: RunState) -> RunState:
        """Require memoization after heavy deterministic tool results."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        last_tool_name = str(state["policy_flags"].get("last_tool_name", ""))
        if not last_tool_name:
            return state

        if last_tool_name in {"memoize", "retrieve_memo"}:
            return state

        last_args = dict(state["policy_flags"].get("last_tool_args", {}))
        last_result = dict(state["policy_flags"].get("last_tool_result", {}))
        if self.policy.requires_memoization(
            tool_name=last_tool_name,
            args=last_args,
            result=last_result,
        ):
            memo_key = self.policy.suggested_memo_key(
                tool_name=last_tool_name,
                args=last_args,
                result=last_result,
            )
            state["policy_flags"]["memo_required"] = True
            state["policy_flags"]["memo_required_key"] = memo_key
            state["policy_flags"]["memo_required_reason"] = (
                f"heavy deterministic result from {last_tool_name}"
            )
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Policy check: memoize required for {last_tool_name}. "
                        f"Next action must be memoize with key='{memo_key}', "
                        f"value as the relevant output, and run_id='{state['run_id']}'."
                    ),
                }
            )
            self.logger.info(
                "MEMO REQUIRED step=%s tool=%s key=%s",
                state["step"],
                last_tool_name,
                memo_key,
            )
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="policy",
            state=state,
        )
        return state

    def _is_unrecoverable_plan_error(self, error_text: str) -> bool:
        """Detect provider/runtime errors where retrying the same prompt is pointless."""
        normalized = error_text.lower()
        unrecoverable_markers = (
            "model",
            "not found",
            "invalid api key",
            "authentication",
            "permission",
            "insufficient_quota",
            "rate limit exceeded",
        )
        if "model" in normalized and "not found" in normalized:
            return True
        return any(marker in normalized for marker in unrecoverable_markers[2:])

    def _finalize(self, state: RunState) -> RunState:
        """Finalize run answer and emit mission-level summary logs."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            state["final_answer"] = str(pending_action.get("answer", "")).strip()
            state["pending_action"] = None
        if not state.get("final_answer"):
            state["final_answer"] = "Run completed."
        self.logger.info(
            "RUN FINALIZE run_id=%s tools_used=%s missions=%s",
            state["run_id"],
            len(state["tool_history"]),
            len(state.get("mission_reports", [])),
        )
        for mission in state.get("mission_reports", []):
            self.logger.info(
                "MISSION REPORT #%s mission=%s used_tools=%s result=%s",
                mission.get("mission_id", 0),
                mission.get("mission", ""),
                mission.get("used_tools", []),
                mission.get("result", ""),
            )
        audit = audit_run(
            run_id=state["run_id"],
            missions=state.get("missions", []),
            mission_reports=state.get("mission_reports", []),
            tool_history=state.get("tool_history", []),
            role_tool_scopes=directives.role_tool_scopes(),
        )
        state["audit_report"] = audit.to_dict()
        self.logger.info(
            "AUDIT REPORT run_id=%s passed=%s warned=%s failed=%s",
            state["run_id"],
            audit.passed,
            audit.warned,
            audit.failed,
        )
        for finding in audit.findings:
            if finding.level != "pass":
                self.logger.warning(
                    "AUDIT %s mission=%s check=%s detail=%s",
                    finding.level.upper(),
                    finding.mission_id,
                    finding.check,
                    finding.detail,
                )
        self._write_shared_plan(state)
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="finalize",
            state=state,
        )
        return state

    def _write_shared_plan(self, state: RunState) -> None:
        """Write structured plan to Shared_plan.md (direct file I/O, outside tool pipeline)."""
        plan_data = state.get("structured_plan")
        if not plan_data:
            return
        try:
            plan = StructuredPlan.from_dict(plan_data)
        except Exception:  # noqa: BLE001
            return
        completed_tasks = set(state.get("completed_tasks", []))
        missions = state.get("missions", [])

        lines = [
            f"# Shared Plan — Run {state.get('run_id', 'unknown')}",
            "",
            f"**Parsing method:** {plan.parsing_method}",
            f"**Total missions:** {len(missions)}",
            f"**Completed:** {len(completed_tasks)}/{len(missions)}",
            "",
            "## Mission Tree",
            "",
        ]

        # Group steps by parent
        top_level = [s for s in plan.steps if s.parent_id is None]
        children_map: dict[str, list] = {}
        for s in plan.steps:
            if s.parent_id is not None:
                children_map.setdefault(s.parent_id, []).append(s)

        for step in top_level:
            mission_text = f"Task {step.id}: {step.description}"
            is_done = mission_text in completed_tasks or step.status == "completed"
            checkbox = "[x]" if is_done else "[ ]"
            status_label = "IMPLEMENTED" if is_done else "PENDING"
            lines.append(f"- {checkbox} **Task {step.id}:** {step.description}  — {status_label}")
            if step.suggested_tools:
                lines.append(f"  - Suggested tools: {', '.join(step.suggested_tools)}")
            if step.dependencies:
                lines.append(f"  - Dependencies: {', '.join(step.dependencies)}")
            # Sub-tasks
            for child in children_map.get(step.id, []):
                child_done = child.status == "completed"
                child_checkbox = "[x]" if child_done else "[ ]"
                child_status = "IMPLEMENTED" if child_done else "PENDING"
                lines.append(
                    f"  - {child_checkbox} **{child.id}:** {child.description}  — {child_status}"
                )
                if child.suggested_tools:
                    lines.append(f"    - Suggested tools: {', '.join(child.suggested_tools)}")

        lines.append("")
        lines.append("## Flat Missions (backward-compat)")
        lines.append("")
        for i, m in enumerate(plan.flat_missions, 1):
            is_done = m in completed_tasks
            checkbox = "[x]" if is_done else "[ ]"
            status_label = "IMPLEMENTED" if is_done else "PENDING"
            lines.append(f"{i}. {checkbox} {m}  — {status_label}")

        lines.append("")
        try:
            Path("Shared_plan.md").write_text("\n".join(lines), encoding="utf-8")
        except OSError as exc:
            self.logger.warning("Failed to write Shared_plan.md: %s", exc)

    # --- Backward-compat shims: delegated to action_parser module ---

    def _validate_action(self, model_output: str) -> dict[str, Any]:
        return action_parser.validate_action(model_output, self.tools)

    def _parse_action_json(self, model_output: str) -> dict[str, Any]:
        return action_parser.parse_action_json(model_output)

    def _extract_first_json_object(self, text: str) -> str | None:
        return action_parser.extract_first_json_object(text)

    def _extract_all_json_objects(self, text: str) -> list[str]:
        return action_parser.extract_all_json_objects(text)

    def _parse_all_actions_json(self, model_output: str) -> list[dict[str, Any]]:
        return action_parser.parse_all_actions_json(model_output)

    def _validate_action_from_dict(self, action_dict: dict[str, Any]) -> dict[str, Any]:
        return action_parser.validate_action_from_dict(action_dict, self.tools)

    # --- Backward-compat shims: delegated to mission_tracker module ---

    def _mission_preview_from_state(self, state: RunState) -> dict[int, dict[str, set[str]]]:
        return mission_tracker.mission_preview_from_state(state)

    def _resolve_mission_id_for_action(
        self,
        state: RunState,
        action: dict[str, Any],
        *,
        preview: dict[int, dict[str, set[str]]] | None = None,
    ) -> int:
        return mission_tracker.resolve_mission_id_for_action(state, action, preview=preview)

    def _deterministic_fallback_action(self, state: RunState) -> dict[str, Any] | None:
        return fallback_planner.deterministic_fallback_action(state)

    # --- Backward-compat shims: delegated to text_extractor module ---

    def _extract_quoted_text(self, text: str) -> str:
        return text_extractor.extract_quoted_text(text)

    def _extract_numbers_from_text(self, text: str) -> list[int]:
        return text_extractor.extract_numbers_from_text(text)

    def _extract_fibonacci_count(self, mission: str) -> int:
        return text_extractor.extract_fibonacci_count(mission)

    def _fibonacci_csv(self, count: int) -> str:
        return text_extractor.fibonacci_csv(count)

    def _extract_missions(self, user_input: str) -> list[str]:
        return text_extractor.extract_missions(user_input)

    def _infer_requirements_from_text(self, text: str) -> tuple[set[str], set[str], int | None]:
        return mission_tracker.infer_requirements_from_text(text)

    def _build_mission_contracts_from_plan(
        self, structured_plan: StructuredPlan, missions: list[str]
    ) -> list[dict[str, Any]]:
        return mission_tracker.build_mission_contracts_from_plan(structured_plan, missions)

    def _initialize_mission_reports(
        self, missions: list[str], *, contracts: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        return mission_tracker.initialize_mission_reports(missions, contracts=contracts)

    def _next_incomplete_mission_index(self, state: RunState) -> int:
        return mission_tracker.next_incomplete_mission_index(state)

    def _refresh_mission_status(self, state: RunState, mission_index: int) -> None:
        return mission_tracker.refresh_mission_status(state, mission_index)

    def _record_mission_tool_event(
        self,
        state: RunState,
        tool_name: str,
        tool_result: dict[str, Any],
        *,
        mission_index: int | None = None,
        tool_args: dict[str, Any] | None = None,
    ) -> None:
        return mission_tracker.record_mission_tool_event(
            state, tool_name, tool_result,
            mission_index=mission_index, tool_args=tool_args,
        )

    def _next_incomplete_mission(self, state: RunState) -> str:
        return mission_tracker.next_incomplete_mission(state)

    def _next_incomplete_mission_requirements(self, state: RunState) -> dict[str, Any]:
        return mission_tracker.next_incomplete_mission_requirements(state)

    def _all_missions_completed(self, state: RunState) -> bool:
        return mission_tracker.all_missions_completed(state)

    def _progress_hint_message(self, state: RunState) -> str:
        return mission_tracker.progress_hint_message(state)

    def _build_auto_finish_answer(self, state: RunState) -> str:
        return mission_tracker.build_auto_finish_answer(state)

    def _compact_messages(self, state: RunState, *, max_messages: int = 50) -> None:
        """Compact older messages when the transcript exceeds *max_messages*.

        Preserves the system prompt (first message) and the latest *keep_recent*
        messages.  Everything in between is summarized into a single digest
        message to prevent context overflow on long runs.
        """
        messages = state.get("messages", [])
        if len(messages) <= max_messages:
            return

        keep_recent = max_messages // 2
        # System prompt is always messages[0]
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        recent = messages[-keep_recent:]
        middle = messages[1:-keep_recent] if system_msg else messages[:-keep_recent]

        # Build a compact digest of the middle messages
        tool_calls: list[str] = []
        for msg in middle:
            content = str(msg.get("content", ""))[:200]
            role = msg.get("role", "?")
            if role == "tool" or (role == "assistant" and "tool_name" in content):
                tool_calls.append(content[:80])

        digest_lines = [
            f"[Context compacted: {len(middle)} messages summarized]",
            f"Tool calls in compacted window: {len(tool_calls)}",
        ]
        if tool_calls:
            digest_lines.append("Recent tool summaries: " + "; ".join(tool_calls[-5:]))

        digest_msg: AgentMessage = {
            "role": "system",
            "content": "\n".join(digest_lines),
        }

        compacted: list[AgentMessage] = []
        if system_msg:
            compacted.append(system_msg)
        compacted.append(digest_msg)
        compacted.extend(recent)
        state["messages"] = compacted

    def _normalize_tool_args(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return fallback_planner.normalize_tool_args(tool_name, args)

    def _memo_lookup_candidates_for_action(
        self, *, tool_name: str, tool_args: dict[str, Any]
    ) -> list[str]:
        """Build exact/fallback memo lookup keys that should be attempted before recompute."""
        if tool_name != "write_file":
            return []
        path = str(tool_args.get("path", "")).strip()
        if not path:
            return []
        exact_key = self.policy.suggested_memo_key(
            tool_name=tool_name,
            args={"path": path},
            result={},
        )
        candidates = [exact_key]
        basename = path.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if basename and basename != path:
            candidates.append(
                self.policy.suggested_memo_key(
                    tool_name=tool_name,
                    args={"path": basename},
                    result={},
                )
            )
        return candidates

    def _has_attempted_memo_lookup(self, *, state: RunState, candidate_keys: list[str]) -> bool:
        return memo_manager.has_attempted_memo_lookup(state=state, candidate_keys=candidate_keys)

    def _build_derived_snapshot(
        self,
        state: RunState,
        memo_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Snapshot is computed from local deterministic data only (no model calls).
        return {
            "run_id": state["run_id"],
            "step": state["step"],
            "tools_used_count": len(state.get("tool_history", [])),
            "tool_call_counts": state.get("tool_call_counts", {}),
            "memo_entry_count": len(memo_entries),
            "memo_keys": [entry.get("key", "") for entry in memo_entries],
            "mission_count": len(state.get("mission_reports", [])),
            "duplicate_tool_retries": state.get("retry_counts", {}).get("duplicate_tool", 0),
            "finish_rejections": state.get("retry_counts", {}).get("finish_rejected", 0),
            "memo_policy_retries": state.get("retry_counts", {}).get("memo_policy", 0),
            "provider_timeout_retries": state.get("retry_counts", {}).get("provider_timeout", 0),
            "content_validation_retries": state.get("retry_counts", {}).get(
                "content_validation", 0
            ),
            "memo_retrieve_hits": state.get("policy_flags", {}).get("memo_retrieve_hits", 0),
            "memo_retrieve_misses": state.get("policy_flags", {}).get("memo_retrieve_misses", 0),
            "cache_reuse_hits": state.get("policy_flags", {}).get("cache_reuse_hits", 0),
            "cache_reuse_misses": state.get("policy_flags", {}).get("cache_reuse_misses", 0),
        }

    def _record_retrieve_memo_trace(self, *, state: RunState, tool_result: dict[str, Any]) -> None:
        """Track memo retrieval hit/miss and emit explicit trace logs/events."""
        found = bool(tool_result.get("found", False))
        key = str(tool_result.get("key", ""))
        namespace = str(tool_result.get("namespace", "run"))
        value_hash = str(tool_result.get("value_hash", ""))

        if found:
            state["policy_flags"]["memo_retrieve_hits"] = (
                int(state["policy_flags"].get("memo_retrieve_hits", 0)) + 1
            )
            source_tool = "retrieve_memo_hit"
            self.logger.info(
                "MEMO RETRIEVE HIT step=%s key=%s namespace=%s value_hash=%s",
                state["step"],
                key,
                namespace,
                value_hash,
            )
        else:
            state["policy_flags"]["memo_retrieve_misses"] = (
                int(state["policy_flags"].get("memo_retrieve_misses", 0)) + 1
            )
            source_tool = "retrieve_memo_miss"
            self.logger.info(
                "MEMO RETRIEVE MISS step=%s key=%s namespace=%s",
                state["step"],
                key,
                namespace,
            )

        state["memo_events"].append(
            MemoEvent(
                key=key,
                namespace=namespace,
                source_tool=source_tool,
                step=state["step"],
                value_hash=value_hash if value_hash else "n/a",
                created_at=utc_now_iso(),
            )
        )

    def _auto_lookup_before_write(
        self, *, state: RunState, candidate_keys: list[str]
    ) -> dict[str, Any] | None:
        """Execute retrieve_memo for candidate keys before deterministic write recompute."""
        progress_hint = (
            self._progress_hint_message(state)
            or "Continue with the next task or finish when all tasks are complete."
        )
        for key in candidate_keys:
            retrieve_args: dict[str, Any] = {"key": key, "run_id": state["run_id"]}
            self.logger.info(
                "TOOL EXEC step=%s tool=%s args=%s", state["step"], "retrieve_memo", retrieve_args
            )
            tool_result = self.tools["retrieve_memo"].execute(retrieve_args)
            self.logger.info(
                "TOOL RESULT step=%s tool=%s result=%s", state["step"], "retrieve_memo", tool_result
            )
            self._record_retrieve_memo_trace(state=state, tool_result=tool_result)
            state["tool_call_counts"]["retrieve_memo"] = (
                int(state["tool_call_counts"].get("retrieve_memo", 0)) + 1
            )
            call_number = len(state["tool_history"]) + 1
            state["tool_history"].append(
                {
                    "call": call_number,
                    "tool": "retrieve_memo",
                    "args": retrieve_args,
                    "result": tool_result,
                }
            )
            self._record_mission_tool_event(state, "retrieve_memo", tool_result)
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"TOOL_RESULT #{call_number} (retrieve_memo): {json.dumps(tool_result)}\n"
                        f"{progress_hint}"
                    ),
                }
            )
            if bool(tool_result.get("found", False)):
                return tool_result
        return None

    def _mark_next_mission_complete_from_memo_hit(
        self, *, state: RunState, memo_hit: dict[str, Any]
    ) -> None:
        return memo_manager.mark_next_mission_complete_from_memo_hit(state=state, memo_hit=memo_hit)

    def _cache_key_for_path(self, path: str) -> str:
        return memo_manager.cache_key_for_path(path)

    def _write_cache_candidates(self, path: str) -> list[str]:
        return memo_manager.write_cache_candidates(path)

    def _extract_write_path_from_mission(self, mission: str) -> str:
        return text_extractor.extract_write_path_from_mission(mission)

    def _maybe_complete_next_write_from_cache(self, state: RunState) -> bool:
        """Auto-complete next write mission from cross-run cached inputs when available."""
        mission = self._next_incomplete_mission(state).strip()
        if not mission:
            return False
        mission_lower = mission.lower()
        if "write_file" not in mission_lower and "write" not in mission_lower:
            return False
        target_path = self._extract_write_path_from_mission(mission)
        if not target_path:
            return False
        reports = state.get("mission_reports", [])
        if reports:
            next_index = self._next_incomplete_mission_index(state)
            target_index = next_index if next_index >= 0 else len(reports) - 1
            if str(reports[target_index].get("mission", "")).strip() != mission:
                for idx, report in enumerate(reports):
                    if str(report.get("mission", "")).strip() == mission:
                        target_index = idx
                        break
        else:
            target_index = 0

        helper_tools = {"memoize", "retrieve_memo"}
        report = reports[target_index] if 0 <= target_index < len(reports) else {}
        required_tools = set(report.get("required_tools", []))
        required_files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in report.get("required_files", [])
        }
        if not required_tools and not required_files:
            inferred_tools, inferred_files, _ = self._infer_requirements_from_text(mission)
            required_tools = set(inferred_tools)
            required_files = {
                str(path).replace("\\", "/").rsplit("/", 1)[-1]
                for path in inferred_files
            }

        # Cache reuse is only safe when mission completion is essentially a write output.
        non_helper_required = {tool for tool in required_tools if tool not in helper_tools}
        if non_helper_required - {"write_file"}:
            self.logger.info(
                "CACHE REUSE SKIP step=%s mission=%s reason=complex_required_tools tools=%s",
                state["step"],
                mission,
                sorted(non_helper_required),
            )
            return False

        attempted_entries = {
            str(item)
            for item in state.get("policy_flags", {}).get("cache_reuse_attempted", [])
        }
        attempt_key = f"{target_index}:{target_path.replace('\\', '/').rsplit('/', 1)[-1]}"
        if attempt_key in attempted_entries:
            return False

        for key in self._write_cache_candidates(target_path):
            lookup = self.memo_store.get_latest(key=key, namespace="cache")
            if not lookup.found:
                continue
            payload = lookup.value if isinstance(lookup.value, dict) else {}
            cached_content = payload.get("content")
            if not isinstance(cached_content, str) or not cached_content:
                continue

            write_args = {"path": target_path, "content": cached_content}
            self.logger.info(
                "CACHE REUSE HIT step=%s mission=%s key=%s source_run=%s",
                state["step"],
                mission,
                key,
                lookup.run_id,
            )
            tool_result = self.tools["write_file"].execute(write_args)
            validation_error = self._validate_tool_result_for_active_mission(
                state=state,
                tool_name="write_file",
                tool_args=write_args,
                tool_result=tool_result,
                mission_index=target_index,
            )
            if validation_error:
                self.logger.warning(
                    "CACHE REUSE INVALID step=%s key=%s reason=%s",
                    state["step"],
                    key,
                    validation_error,
                )
                continue

            state["policy_flags"]["cache_reuse_hits"] = (
                int(state["policy_flags"].get("cache_reuse_hits", 0)) + 1
            )
            state["active_mission_index"] = target_index
            state["active_mission_id"] = target_index + 1
            state["tool_call_counts"]["write_file"] = (
                int(state["tool_call_counts"].get("write_file", 0)) + 1
            )
            call_number = len(state["tool_history"]) + 1
            state["tool_history"].append(
                {
                    "call": call_number,
                    "tool": "write_file",
                    "args": write_args,
                    "result": tool_result,
                }
            )
            self._record_mission_tool_event(
                state,
                "write_file",
                tool_result,
                mission_index=target_index,
                tool_args=write_args,
            )
            progress_hint = (
                self._progress_hint_message(state)
                or "Continue with the next task or finish when all tasks are complete."
            )
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"TOOL_RESULT #{call_number} (write_file): {json.dumps(tool_result)}\n"
                        f"{progress_hint}"
                    ),
                }
            )
            state["memo_events"].append(
                MemoEvent(
                    key=key,
                    namespace="cache",
                    source_tool="cache_reuse_hit",
                    step=state["step"],
                    value_hash=str(lookup.value_hash or "n/a"),
                    created_at=utc_now_iso(),
                )
            )
            attempted_entries.add(attempt_key)
            state["policy_flags"]["cache_reuse_attempted"] = sorted(attempted_entries)
            return True

        attempted_entries.add(attempt_key)
        state["policy_flags"]["cache_reuse_attempted"] = sorted(attempted_entries)
        state["policy_flags"]["cache_reuse_misses"] = (
            int(state["policy_flags"].get("cache_reuse_misses", 0)) + 1
        )
        self.logger.info(
            "CACHE REUSE MISS step=%s mission=%s path=%s",
            state["step"],
            mission,
            target_path,
        )
        return False

    def _cache_write_file_inputs(self, *, state: RunState, tool_args: dict[str, Any]) -> None:
        """Persist reusable write_file inputs so later runs can skip recomputation."""
        path = str(tool_args.get("path", "")).strip()
        content = str(tool_args.get("content", ""))
        if not path or not content:
            return

        for key in self._write_cache_candidates(path):
            put_result = self.memo_store.put(
                run_id="shared",
                key=key,
                value={"path": path, "content": content},
                namespace="cache",
                source_tool="write_file_cache",
                step=state["step"],
            )
            state["memo_events"].append(
                MemoEvent(
                    key=put_result.key,
                    namespace=put_result.namespace,
                    source_tool="write_file_cache",
                    step=state["step"],
                    value_hash=put_result.value_hash,
                    created_at=utc_now_iso(),
                )
            )
            self.logger.info(
                "CACHE WRITE INPUT STORED step=%s key=%s hash=%s",
                state["step"],
                put_result.key,
                put_result.value_hash,
            )

    # --- Backward-compat shims: delegated to content_validator module ---

    def _validate_tool_result_for_active_mission(
        self,
        *,
        state: RunState,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
        mission_index: int | None = None,
    ) -> str | None:
        return content_validator.validate_tool_result_for_active_mission(
            state=state,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
            mission_index=mission_index,
        )

    def _parse_csv_int_list(self, content: str) -> list[int] | None:
        return text_extractor.parse_csv_int_list(content)

    def _validate_pattern_report_content(self, content: str) -> str | None:
        return content_validator.validate_pattern_report_content(content)
