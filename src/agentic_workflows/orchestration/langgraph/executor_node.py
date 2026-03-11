from __future__ import annotations

"""Executor node for LangGraphOrchestrator.

ExecutorNodeMixin provides:
- _build_lc_tools(): Convert tool registry to LangChain StructuredTool instances
- _dedup_then_tool_node(): Deduplication wrapper for Anthropic ToolNode path
- _select_specialist_for_action(): Choose specialist role from action
- _is_tool_allowed_for_specialist(): Scope check
- _route_to_specialist(): Main execute node — routes action to specialist + calls _execute_action
- _execute_action(): Full tool execution pipeline with dedup, memo policy, content validation

Anti-pattern: do NOT import from graph.py or orchestrator.py here — circular.
"""

import contextlib
import json
from typing import Any

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph import directives
from agentic_workflows.orchestration.langgraph.context_manager import MissionContext
from agentic_workflows.orchestration.langgraph.handoff import create_handoff, create_handoff_result
from agentic_workflows.orchestration.langgraph.state_schema import (
    MemoEvent,
    RunState,
    ensure_state_defaults,
    utc_now_iso,
)

try:
    from langchain_core.tools import StructuredTool
    _STRUCTUREDTOOL_AVAILABLE = True
except ImportError:  # pragma: no cover
    StructuredTool = None  # type: ignore[assignment,misc]
    _STRUCTUREDTOOL_AVAILABLE = False

_LOG = get_logger("langgraph.orchestrator")


class ExecutorNodeMixin:
    """Mixin providing executor node methods for LangGraphOrchestrator.

    Intended to be used with LangGraphOrchestrator via multiple inheritance.
    Methods here reference self attributes set in LangGraphOrchestrator.__init__.
    """

    def _build_lc_tools(self) -> list[Any]:
        """Convert internal Tool registry to LangChain StructuredTool instances.

        This is used exclusively for the Anthropic ToolNode path. The standard
        ChatProvider path uses tools from self.tools (our Tool base class) directly.
        """
        from agentic_workflows.tools.base import Tool  # noqa: PLC0415

        if StructuredTool is None:  # pragma: no cover
            return []

        lc_tools = []
        for tool_name, tool_instance in self.tools.items():  # type: ignore[attr-defined]
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
            state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
            # Extract tool calls from the last AIMessage in messages (Anthropic format)
            messages = state.get("messages", [])
            last_msg = messages[-1] if messages else None
            tool_calls = getattr(last_msg, "tool_calls", []) if last_msg else []
            for tc in tool_calls or []:
                tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                tool_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                signature = f"{tool_name}:{json.dumps(tool_args, sort_keys=True, default=str)}"
                if signature in state.get("seen_tool_signatures", set()):
                    self.logger.info(  # type: ignore[attr-defined]
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

    # ------------------------------------------------------------------ #
    # Specialist routing                                                   #
    # ------------------------------------------------------------------ #

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
        from agentic_workflows.orchestration.langgraph.orchestrator import (  # noqa: PLC0415
            _HANDOFF_QUEUE_CAP,
            _HANDOFF_RESULTS_CAP,
        )

        state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
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
        if self._on_specialist_route is not None:  # type: ignore[attr-defined]
            with contextlib.suppress(Exception):
                self._on_specialist_route(  # type: ignore[attr-defined]
                    specialist=specialist,
                    tool=tool_name,
                    mission_id=int(mission_id or 0),
                )
        self._emit_trace(state, "specialist_route",  # type: ignore[attr-defined]
            specialist=specialist,
            tool_name=tool_name,
            mission_id=int(mission_id or 0),
        )
        task_id = f"{state['run_id']}:{state['step']}:{len(state['handoff_queue']) + 1}"
        config = directives.DIRECTIVE_BY_SPECIALIST.get(specialist)  # type: ignore[arg-type]
        tool_scope = sorted(config.allowed_tools) if config else []
        self.logger.info(  # type: ignore[attr-defined]
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
            ).model_dump()
        )
        if len(state["handoff_queue"]) > _HANDOFF_QUEUE_CAP:
            state["handoff_queue"] = state["handoff_queue"][-_HANDOFF_QUEUE_CAP:]

        if specialist in ("executor", "evaluator"):
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
            ).model_dump()
        )
        if len(state["handoff_results"]) > _HANDOFF_RESULTS_CAP:
            state["handoff_results"] = state["handoff_results"][-_HANDOFF_RESULTS_CAP:]
        self.logger.info(  # type: ignore[attr-defined]
            "SPECIALIST OUTPUT step=%s run_id=%s task_id=%s specialist=%s status=%s via_subgraph=True",
            state["step"],
            state["run_id"],
            task_id,
            specialist,
            status,
        )
        return state

    def _execute_action(self, state: RunState) -> RunState:  # noqa: C901  # method is intentionally large
        """Execute planned tool action, including duplicate and policy checks."""
        from agentic_workflows.orchestration.langgraph.orchestrator import MemoizationPolicyViolation  # noqa: PLC0415

        state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
        action = state.get("pending_action")
        if not action:
            return state

        if action.get("action") == "finish":
            state["final_answer"] = str(action.get("answer", ""))
            self.logger.info(  # type: ignore[attr-defined]
                "FINISH ACTION step=%s answer=%s", state["step"], state["final_answer"][:300]
            )
            return state

        tool_name = str(action.get("tool_name", ""))
        tool_args = self._normalize_tool_args(tool_name, dict(action.get("args", {})))  # type: ignore[attr-defined]
        specialist = str(state.get("active_specialist", "executor")).strip() or "executor"
        if not self._is_tool_allowed_for_specialist(specialist=specialist, tool_name=tool_name):
            config = directives.DIRECTIVE_BY_SPECIALIST.get(specialist)  # type: ignore[arg-type]
            allowed_tools = sorted(config.allowed_tools) if config else []
            self.logger.info(  # type: ignore[attr-defined]
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
            self.checkpoint_store.save(  # type: ignore[attr-defined]
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
            mission_index = self._next_incomplete_mission_index(state)  # type: ignore[attr-defined]
        if mission_index >= 0:
            state["active_mission_index"] = mission_index
            state["active_mission_id"] = mission_index + 1
            # Initialize MissionContext if not already present
            _mid = mission_index + 1
            _mid_str = str(_mid)
            _mctxs = state.get("mission_contexts")
            if isinstance(_mctxs, dict) and _mid_str not in _mctxs:
                _goal = ""
                _missions_list = state.get("missions", [])
                if mission_index < len(_missions_list):
                    _goal = _missions_list[mission_index]
                _mctx = MissionContext(
                    mission_id=_mid,
                    goal=_goal,
                    step_range=(state.get("step", 0), state.get("step", 0)),
                )
                _mctxs[_mid_str] = _mctx.model_dump()
        self.logger.info(  # type: ignore[attr-defined]
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

        lookup_candidates = self._memo_lookup_candidates_for_action(  # type: ignore[attr-defined]
            tool_name=tool_name, tool_args=tool_args
        )
        if (
            lookup_candidates
            and tool_name != "retrieve_memo"
            and not self._has_attempted_memo_lookup(state=state, candidate_keys=lookup_candidates)  # type: ignore[attr-defined]
        ):
                self.logger.info(  # type: ignore[attr-defined]
                    "MEMO LOOKUP AUTO step=%s attempted_tool=%s keys=%s",
                    state["step"],
                    tool_name,
                    lookup_candidates,
                )
                memo_hit = self._auto_lookup_before_write(  # type: ignore[attr-defined]
                    state=state, candidate_keys=lookup_candidates
                )
                if memo_hit:
                    if tool_name == "write_file":
                        self._mark_next_mission_complete_from_memo_hit(  # type: ignore[attr-defined]
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
                    self.checkpoint_store.save(  # type: ignore[attr-defined]
                        run_id=state["run_id"],
                        step=state["step"],
                        node_name="execute_lookup_hit_skip",
                        state=state,
                    )
                    return state

        if state["policy_flags"].get("memo_required") and tool_name != "memoize":
            retry_count = int(state["retry_counts"].get("memo_policy", 0)) + 1
            state["retry_counts"]["memo_policy"] = retry_count
            self.logger.info(  # type: ignore[attr-defined]
                "MEMO POLICY RETRY step=%s retry=%s attempted_tool=%s",
                state["step"],
                retry_count,
                tool_name,
            )
            if retry_count > self.policy.max_policy_retries:  # type: ignore[attr-defined]
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
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_policy_retry",
                state=state,
            )
            return state

        if tool_name not in self.tools:  # type: ignore[attr-defined]
            state["messages"].append(
                {
                    "role": "system",
                    "content": f"Unknown tool '{tool_name}'. Use one of: {', '.join(self.tools.keys())}.",  # type: ignore[attr-defined]
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(  # type: ignore[attr-defined]
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
        # Cursor-resumption actions bypass duplicate detection (narrowly scoped to read_file_chunk)
        _is_cursor_resume = (
            action.get("__cursor_resume") is True
            and tool_name == "read_file_chunk"
        )
        if not _is_cursor_resume and signature in state["seen_tool_signatures"]:
            duplicate_retry_count = int(state["retry_counts"].get("duplicate_tool", 0)) + 1
            state["retry_counts"]["duplicate_tool"] = duplicate_retry_count
            next_mission = self._next_incomplete_mission(state)  # type: ignore[attr-defined]
            if not next_mission and self._all_missions_completed(state):  # type: ignore[attr-defined]
                state["pending_action"] = {
                    "action": "finish",
                    "answer": self._build_auto_finish_answer(state),  # type: ignore[attr-defined]
                }
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="execute_duplicate_finish",
                    state=state,
                )
                return state
            if duplicate_retry_count > self.max_duplicate_tool_retries:  # type: ignore[attr-defined]
                fail_message = (
                    "Run stopped: repeated duplicate tool actions prevented mission progress. "
                    f"Next task: {next_mission or 'unknown'}."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(  # type: ignore[attr-defined]
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
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_duplicate_tool",
                state=state,
            )
            return state
        state["seen_tool_signatures"].add(signature)

        self.logger.info("TOOL EXEC step=%s tool=%s args=%s", state["step"], tool_name, tool_args)  # type: ignore[attr-defined]
        tool_result = self.tools[tool_name].execute(tool_args)  # type: ignore[attr-defined]
        self.logger.info(  # type: ignore[attr-defined]
            "TOOL RESULT step=%s tool=%s result=%s", state["step"], tool_name, tool_result
        )
        # Cursor tracking for chunked reads (Phase 07.6-03)
        if tool_name == "read_file_chunk" and isinstance(tool_result, dict):
            _store = getattr(getattr(self, "context_manager", None), "_store", None)
            if _store is not None:
                path_key = tool_args.get("path", tool_args.get("file_path", ""))
                run_id = state.get("run_id", "")
                mission_id = str(state.get("active_mission_id", ""))
                if tool_result.get("has_more"):
                    _store.upsert_cursor(
                        run_id=run_id,
                        plan_step_id=str(state.get("step", 0)),
                        mission_id=mission_id,
                        tool_name="read_file_chunk",
                        key=path_key,
                        cursor=tool_result.get("next_offset", 0),
                        total=tool_result.get("total_lines", 0),
                    )
                else:
                    # Chunk complete — clear cursor
                    cursor_key = f"{run_id}:{mission_id}:read_file_chunk:{path_key}"
                    if hasattr(_store, "_cursors"):
                        _store._cursors.pop(cursor_key, None)
        if tool_name == "retrieve_memo":
            self._record_retrieve_memo_trace(state=state, tool_result=tool_result)  # type: ignore[attr-defined]
        validation_error = self._validate_tool_result_for_active_mission(  # type: ignore[attr-defined]
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
            self.logger.warning(  # type: ignore[attr-defined]
                "CONTENT VALIDATION FAILED step=%s tool=%s retry=%s reason=%s",
                state["step"],
                tool_name,
                retry_count,
                validation_error,
            )
            self._emit_trace(state, "validator_fail",  # type: ignore[attr-defined]
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
        self._record_mission_tool_event(  # type: ignore[attr-defined]
            state,
            tool_name,
            tool_result,
            mission_index=mission_index if mission_index >= 0 else None,
            tool_args=tool_args,
        )
        self._emit_trace(state, "tool_exec",  # type: ignore[attr-defined]
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
            self._emit_trace(state, "validator_pass", tool=tool_name, check=_check)  # type: ignore[attr-defined]
        for _i, _r in enumerate(state.get("mission_reports", [])):
            _mid = int(_r.get("mission_id", _i + 1))
            if str(_r.get("status", "")) == "completed" and _pre_statuses.get(_mid) != "completed":
                self._emit_trace(state, "mission_complete",  # type: ignore[attr-defined]
                    mission_id=_mid,
                    mission_preview=str(_r.get("mission", ""))[:60],
                )
                # Evict mission messages and inject summary via ContextManager
                if isinstance(state.get("mission_contexts"), dict):
                    try:
                        self.context_manager.on_mission_complete(state, _mid)  # type: ignore[attr-defined]
                    except Exception:
                        self.logger.debug(  # type: ignore[attr-defined]
                            "ContextManager.on_mission_complete failed (non-fatal)",
                            exc_info=True,
                        )
        progress_hint = (
            self._progress_hint_message(state)  # type: ignore[attr-defined]
            or "Continue with the next task or finish when all tasks are complete."
        )
        if validation_error:
            progress_hint = (
                "Previous tool output failed deterministic content validation. "
                f"Fix and rerun this task. {validation_error}"
            )
        # Gate: truncate large tool results BEFORE they enter state["messages"].
        _tool_result_json = json.dumps(tool_result)
        _threshold = getattr(self.context_manager, "large_result_threshold", 800)  # type: ignore[attr-defined]
        if len(_tool_result_json) > _threshold:
            _tool_result_for_msg = (
                f"[tool_result: {tool_name}, {len(_tool_result_json)} chars, stored in context]"
            )
            self.logger.info(  # type: ignore[attr-defined]
                "TOOL RESULT TRUNCATED step=%s tool=%s original_len=%d threshold=%d",
                state["step"], tool_name, len(_tool_result_json), _threshold,
            )
        else:
            _tool_result_for_msg = _tool_result_json
        state["messages"].append(
            {
                "role": "system",
                "content": (
                    f"TOOL_RESULT #{call_number} ({tool_name}): {_tool_result_for_msg}\n"
                    f"{progress_hint}"
                ),
            }
        )

        # Update MissionContext with tool result via ContextManager
        _ctx_mission_id = int(state.get("active_mission_id", 0))
        if _ctx_mission_id > 0 and isinstance(state.get("mission_contexts"), dict):
            try:
                # Update step_range end to current step
                _ctx_mid_str = str(_ctx_mission_id)
                _ctx_entry = state["mission_contexts"].get(_ctx_mid_str)
                if isinstance(_ctx_entry, dict) and _ctx_entry.get("step_range"):
                    _sr = _ctx_entry["step_range"]
                    _ctx_entry["step_range"] = (_sr[0], state.get("step", _sr[1]))
                self.context_manager.on_tool_result(  # type: ignore[attr-defined]
                    state, tool_name, tool_result, tool_args, _ctx_mission_id
                )
            except Exception:
                self.logger.debug(  # type: ignore[attr-defined]
                    "ContextManager.on_tool_result failed (non-fatal)", exc_info=True
                )

        if validation_error:
            if (
                int(state["retry_counts"].get("content_validation", 0))
                > self.max_content_validation_retries  # type: ignore[attr-defined]
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
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="execute_content_validation",
                state=state,
            )
            return state

        if tool_name == "write_file":
            self._cache_write_file_inputs(state=state, tool_args=tool_args)  # type: ignore[attr-defined]

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

        # Auto-memoize write_file results that require it, so the model never needs to.
        if tool_name == "write_file" and self.policy.requires_memoization(  # type: ignore[attr-defined]
            tool_name=tool_name, args=tool_args, result=tool_result
        ):
            _auto_key = self.policy.suggested_memo_key(  # type: ignore[attr-defined]
                tool_name=tool_name, args=tool_args, result=tool_result
            )
            _auto_result = self.tools["memoize"].execute({  # type: ignore[attr-defined]
                "key": _auto_key,
                "value": tool_result,
                "run_id": state["run_id"],
                "step": state["step"],
                "source_tool": "write_file",
            })
            if "value_hash" in _auto_result:
                state["memo_events"].append(
                    MemoEvent(
                        key=str(_auto_result.get("key", _auto_key)),
                        namespace=str(_auto_result.get("namespace", "run")),
                        source_tool="write_file",
                        step=state["step"],
                        value_hash=str(_auto_result["value_hash"]),
                        created_at=utc_now_iso(),
                    )
                )
                state["policy_flags"]["last_tool_name"] = "memoize"
                self.logger.info(  # type: ignore[attr-defined]
                    "AUTO MEMOIZE step=%s tool=write_file key=%s", state["step"], _auto_key
                )

        self.checkpoint_store.save(  # type: ignore[attr-defined]
            run_id=state["run_id"],
            step=state["step"],
            node_name="execute",
            state=state,
        )
        return state
