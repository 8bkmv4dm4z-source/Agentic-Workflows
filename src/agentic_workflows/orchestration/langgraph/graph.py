from __future__ import annotations

"""Phase 1 LangGraph orchestrator.

This module is the Layer-2 orchestration engine: it plans model actions,
executes deterministic tools, enforces memoization policy, and produces
run/mission reports using only local state for final snapshots.
"""

import json
import os
import queue
import re
import threading
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run
from agentic_workflows.orchestration.langgraph.mission_parser import StructuredPlan, parse_missions
from agentic_workflows.orchestration.langgraph.policy import MemoizationPolicy
from agentic_workflows.orchestration.langgraph.provider import (
    ChatProvider,
    ProviderTimeoutError,
    build_provider,
)
from agentic_workflows.orchestration.langgraph.state_schema import (
    AgentMessage,
    MemoEvent,
    RunState,
    ensure_state_defaults,
    new_run_state,
    utc_now_iso,
)
from agentic_workflows.orchestration.langgraph.tools_registry import build_tool_registry
from agentic_workflows.schemas import FinishAction, ToolAction
from agentic_workflows.tools.base import Tool

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    StateGraph = None


class MemoizationPolicyViolation(RuntimeError):
    """Raised when memoization policy retries are exhausted."""

    pass


class LangGraphOrchestrator:
    """State-graph orchestrator with memoization and checkpoint guardrails."""

    def __init__(
        self,
        *,
        provider: ChatProvider | None = None,
        memo_store: SQLiteMemoStore | None = None,
        checkpoint_store: SQLiteCheckpointStore | None = None,
        policy: MemoizationPolicy | None = None,
        max_steps: int = 40,
        max_invalid_plan_retries: int = 8,
        max_provider_timeout_retries: int = 3,
        plan_call_timeout_seconds: float | None = None,
        max_content_validation_retries: int = 2,
        max_duplicate_tool_retries: int = 6,
        max_finish_rejections: int = 6,
    ) -> None:
        self.provider = provider or build_provider()
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
        self.tools: dict[str, Tool] = build_tool_registry(self.memo_store)
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

    def _compile_graph(self):
        """Compile runtime graph topology: plan -> execute -> policy -> finalize."""
        if StateGraph is None:
            raise RuntimeError(
                "langgraph is not installed. Add langgraph to requirements and install dependencies."
            )

        builder = StateGraph(RunState)
        builder.add_node("plan", self._plan_next_action)
        builder.add_node("execute", self._execute_action)
        builder.add_node("policy", self._enforce_memo_policy)
        builder.add_node("finalize", self._finalize)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "plan": "plan",
                "execute": "execute",
                "finish": "finalize",
            },
        )
        builder.add_edge("execute", "policy")
        builder.add_edge("policy", "plan")
        builder.add_edge("finalize", END)
        return builder.compile()

    def run(self, user_input: str, run_id: str | None = None) -> dict[str, Any]:
        """Execute one end-to-end run and return audit-friendly artifacts."""
        state = new_run_state(self.system_prompt, user_input, run_id=run_id)
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        structured_plan = parse_missions(user_input)
        missions = structured_plan.flat_missions
        contracts = self._build_mission_contracts_from_plan(structured_plan, missions)
        state["missions"] = missions
        state["structured_plan"] = structured_plan.to_dict()
        state["mission_contracts"] = contracts
        state["mission_reports"] = self._initialize_mission_reports(missions, contracts=contracts)
        state["active_mission_index"] = -1
        state["active_mission_id"] = 0
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

    def _route_after_plan(self, state: RunState) -> str:
        """Route graph transitions based on the planner's pending action."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not action:
            return "plan"
        if action.get("action") == "finish":
            return "finish"
        return "execute"

    def _plan_next_action(self, state: RunState) -> RunState:
        """Call the model planner and parse one strict JSON action."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        self._compact_messages(state)
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            return state
        state["step"] = state.get("step", 0) + 1
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
        # --- Action queue: pop next queued action before calling provider ---
        queue = state.get("pending_action_queue", [])
        if queue and not state.get("policy_flags", {}).get("memo_required", False):
            next_action_raw = queue.pop(0)
            state["pending_action_queue"] = queue
            try:
                validated = self._validate_action_from_dict(next_action_raw)
                self.logger.info(
                    "PLAN QUEUE POP step=%s queue_remaining=%s action=%s",
                    state["step"],
                    len(queue),
                    validated,
                )
                if validated.get("action") == "finish" and not self._all_missions_completed(state):
                    finish_rejected = int(state["retry_counts"].get("finish_rejected", 0)) + 1
                    state["retry_counts"]["finish_rejected"] = finish_rejected
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
                            node_name="plan_queue_finish_fail_closed",
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
                        node_name="plan_queue_finish_rejected",
                        state=state,
                    )
                    return state
                state["pending_action"] = validated
                state["retry_counts"]["finish_rejected"] = 0
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
                self.logger.warning(
                    "PLAN TIMEOUT MODE step=%s action=%s",
                    state["step"],
                    fallback_action,
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

            action = self._validate_action_from_dict(tagged_actions[0])
            if len(all_actions) > 1:
                state["pending_action_queue"] = tagged_actions[1:]
                self.logger.info(
                    "PLAN QUEUED step=%s queued=%s",
                    state["step"],
                    len(tagged_actions) - 1,
                )
                state["retry_counts"]["provider_timeout"] = 0
            if action.get("action") == "finish" and not self._all_missions_completed(state):
                finish_rejected = int(state["retry_counts"].get("finish_rejected", 0)) + 1
                state["retry_counts"]["finish_rejected"] = finish_rejected
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
                        node_name="plan_finish_fail_closed",
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
                    node_name="plan_finish_rejected",
                    state=state,
                )
                return state
            self.logger.info("PLANNED ACTION step=%s action=%s", state["step"], action)
            state["pending_action"] = action
            state["retry_counts"]["finish_rejected"] = 0
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
                self.logger.warning(
                    "PLAN TIMEOUT FALLBACK step=%s action=%s",
                    state["step"],
                    fallback_action,
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

    def _generate_with_hard_timeout(self, messages: list[dict[str, str]]) -> str:
        """Protect planner generate() call with a hard wall-clock timeout."""
        timeout_seconds = self.plan_call_timeout_seconds
        if timeout_seconds <= 0:
            return self.provider.generate(messages)

        outbox: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def _run() -> None:
            try:
                outbox.put(("ok", self.provider.generate(messages)))
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

    def _route_to_specialist(self, state: RunState) -> RunState:
        """Route the pending action to the appropriate specialist.

        Currently a pass-through: all actions go to the executor (_execute_action).
        When multi-agent routing is active, this will inspect the action and
        delegate to supervisor/executor/evaluator based on task type.
        """
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        state["active_specialist"] = "executor"
        return self._execute_action(state)

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
        mission_id = action.get("__mission_id")
        mission_index = -1
        if isinstance(mission_id, int) and mission_id > 0:
            mission_index = mission_id - 1
        else:
            mission_index = self._next_incomplete_mission_index(state)
        if mission_index >= 0:
            state["active_mission_index"] = mission_index
            state["active_mission_id"] = mission_index + 1

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
        self._record_mission_tool_event(
            state,
            tool_name,
            tool_result,
            mission_index=mission_index if mission_index >= 0 else None,
            tool_args=tool_args,
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

    def _validate_action(self, model_output: str) -> dict[str, Any]:
        """Validate model output against strict ToolAction/FinishAction schema."""
        data = self._parse_action_json(model_output)
        action_alias = str(data.get("action", "")).strip().lower()
        if (
            "tool_name" not in data
            and isinstance(data.get("action"), str)
            and action_alias in self.tools
        ):
            data = {
                "action": "tool",
                "tool_name": action_alias,
                "args": dict(data.get("args", {})),
            }
        if (
            data.get("action") == "tool"
            and "tool_name" not in data
            and isinstance(data.get("name"), str)
        ):
            data["tool_name"] = data["name"]
        action = str(data.get("action", "")).strip().lower()
        if action in {"tool", "finish"}:
            data["action"] = action
        if action == "tool":
            try:
                parsed = ToolAction(**data)
                return parsed.model_dump()
            except ValidationError as exc:
                raise ValueError(f"tool schema error: {str(exc)}") from exc
        if action == "finish":
            try:
                parsed = FinishAction(**data)
                return parsed.model_dump()
            except ValidationError as exc:
                raise ValueError(f"finish schema error: {str(exc)}") from exc
        raise ValueError("action must be 'tool' or 'finish'")

    def _parse_action_json(self, model_output: str) -> dict[str, Any]:
        """Parse planner output, recovering first JSON object when extra data is emitted."""
        try:
            data = json.loads(model_output)
            if not isinstance(data, dict):
                raise ValueError("action payload must be a JSON object")
            return data
        except json.JSONDecodeError as exc:
            candidate = self._extract_first_json_object(model_output)
            if not candidate:
                raise ValueError(f"invalid json: {str(exc)}") from exc
            try:
                recovered = json.loads(candidate)
            except json.JSONDecodeError as recover_exc:
                raise ValueError(f"invalid json: {str(recover_exc)}") from recover_exc
            if not isinstance(recovered, dict):
                raise ValueError("action payload must be a JSON object") from None
            return recovered

    def _extract_first_json_object(self, text: str) -> str | None:
        """Return first balanced JSON object from text, ignoring surrounding noise."""
        start = text.find("{")
        if start < 0:
            return None
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == "{":
                depth += 1
                continue
            if char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        return None

    def _extract_all_json_objects(self, text: str) -> list[str]:
        """Extract all top-level balanced JSON objects from text."""
        objects: list[str] = []
        pos = 0
        while pos < len(text):
            start = text.find("{", pos)
            if start < 0:
                break
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(text)):
                char = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                    continue
                if char == "{":
                    depth += 1
                    continue
                if char == "}":
                    depth -= 1
                    if depth == 0:
                        objects.append(text[start : index + 1])
                        pos = index + 1
                        break
            else:
                break  # unbalanced — stop
        return objects

    def _parse_all_actions_json(self, model_output: str) -> list[dict[str, Any]]:
        """Parse all JSON action objects from planner output."""
        try:
            data = json.loads(model_output)
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        candidates = self._extract_all_json_objects(model_output)
        actions = []
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and "action" in parsed:
                    actions.append(parsed)
            except (json.JSONDecodeError, ValueError):
                continue
        return actions

    def _validate_action_from_dict(self, action_dict: dict[str, Any]) -> dict[str, Any]:
        """Validate a pre-parsed action dict against Pydantic schemas."""
        raw = dict(action_dict)
        mission_id = raw.get("__mission_id")
        sanitized = {key: value for key, value in raw.items() if not key.startswith("__")}
        validated = self._validate_action(json.dumps(sanitized))
        if isinstance(mission_id, int) and mission_id > 0:
            validated["__mission_id"] = mission_id
        return validated

    def _mission_preview_from_state(self, state: RunState) -> dict[int, dict[str, set[str]]]:
        """Build mutable mission usage preview for action tagging within one planner turn."""
        preview: dict[int, dict[str, set[str]]] = {}
        for report in state.get("mission_reports", []):
            mission_id = int(report.get("mission_id", 0))
            if mission_id <= 0:
                continue
            preview[mission_id] = {
                "used_tools": {str(tool) for tool in report.get("used_tools", [])},
                "written_files": {
                    str(path).replace("\\", "/").rsplit("/", 1)[-1]
                    for path in report.get("written_files", [])
                },
            }
        return preview

    def _resolve_mission_id_for_action(
        self,
        state: RunState,
        action: dict[str, Any],
        *,
        preview: dict[int, dict[str, set[str]]] | None = None,
    ) -> int:
        """Resolve which mission an action should be attributed to."""
        if str(action.get("action", "")).strip().lower() != "tool":
            return 0
        reports = state.get("mission_reports", [])
        if not reports:
            return 0
        tool_name = str(action.get("tool_name", "")).strip()
        args = dict(action.get("args", {}))
        helper_tools = {"memoize", "retrieve_memo"}

        def _requirements_for_report(report: dict[str, Any]) -> tuple[set[str], set[str]]:
            tools = set(report.get("required_tools", []))
            files = {
                str(path).replace("\\", "/").rsplit("/", 1)[-1]
                for path in report.get("required_files", [])
            }
            if not tools and not files:
                inferred_tools, inferred_files, _ = self._infer_requirements_from_text(
                    str(report.get("mission", ""))
                )
                tools = set(inferred_tools)
                files = {
                    str(path).replace("\\", "/").rsplit("/", 1)[-1]
                    for path in inferred_files
                }
            return tools, files

        # Path-based mapping for deterministic write-related actions.
        path_hint = ""
        if tool_name == "write_file":
            path_hint = str(args.get("path", "")).strip()
        elif tool_name == "memoize":
            key = str(args.get("key", "")).strip()
            if key.startswith("write_file:"):
                path_hint = key.split(":", 1)[1].strip()
        if path_hint:
            basename = path_hint.replace("\\", "/").rsplit("/", 1)[-1]
            for report in reports:
                required_files = _requirements_for_report(report)[1]
                if basename and basename in required_files:
                    return int(report.get("mission_id", 0))

        # Prefer missions where this required tool has not yet been observed.
        for report in reports:
            if str(report.get("status", "pending")) == "completed":
                continue
            required_tools = _requirements_for_report(report)[0]
            mission_id = int(report.get("mission_id", 0))
            already_used = set(report.get("used_tools", []))
            if preview and mission_id in preview:
                already_used = set(preview[mission_id].get("used_tools", set()))
            if tool_name in required_tools and tool_name not in already_used:
                return int(report.get("mission_id", 0))

        # Fallback: any incomplete mission that expects the tool.
        for report in reports:
            if str(report.get("status", "pending")) == "completed":
                continue
            required_tools = _requirements_for_report(report)[0]
            if tool_name in required_tools:
                return int(report.get("mission_id", 0))

        # Queue-aware fallback: assign to the next mission still incomplete in preview.
        for report in reports:
            if str(report.get("status", "pending")) == "completed":
                continue
            mission_id = int(report.get("mission_id", 0))
            required_tools, required_files = _requirements_for_report(report)
            already_used = set(report.get("used_tools", []))
            written_files = {
                str(path).replace("\\", "/").rsplit("/", 1)[-1]
                for path in report.get("written_files", [])
            }
            if preview and mission_id in preview:
                already_used = set(preview[mission_id].get("used_tools", set()))
                written_files = set(preview[mission_id].get("written_files", set()))

            observed_tools = set(already_used)
            observed_non_helper_tools = {tool for tool in already_used if tool not in helper_tools}
            if required_tools or required_files:
                missing_tools = required_tools - observed_tools
                missing_files = required_files - written_files
                if missing_tools or missing_files:
                    return mission_id
                continue

            # Generic mission: one non-helper tool call completes it.
            if not observed_non_helper_tools:
                return mission_id

        next_index = self._next_incomplete_mission_index(state)
        if 0 <= next_index < len(reports):
            return int(reports[next_index].get("mission_id", 0))
        return 0

    def _deterministic_fallback_action(self, state: RunState) -> dict[str, Any] | None:
        """Build a safe tool/finish action from local state when provider times out."""
        policy_flags = state.get("policy_flags", {})
        if policy_flags.get("memo_required"):
            key = str(policy_flags.get("memo_required_key", "")).strip()
            if key:
                source_tool = (
                    str(policy_flags.get("last_tool_name", "memoize")).strip() or "memoize"
                )
                last_result = dict(policy_flags.get("last_tool_result", {}))
                value: Any = last_result if last_result else {"status": "memoized_by_fallback"}
                return {
                    "action": "tool",
                    "tool_name": "memoize",
                    "args": {
                        "key": key,
                        "value": value,
                        "run_id": state["run_id"],
                        "source_tool": source_tool,
                    },
                }

        if self._all_missions_completed(state):
            return {"action": "finish", "answer": self._build_auto_finish_answer(state)}

        mission = self._next_incomplete_mission(state).strip()
        if not mission:
            return {"action": "finish", "answer": self._build_auto_finish_answer(state)}
        mission_lower = mission.lower()

        repeat_text = self._extract_quoted_text(mission)
        if "repeat" in mission_lower and repeat_text:
            return {
                "action": "tool",
                "tool_name": "repeat_message",
                "args": {"message": repeat_text},
            }

        if "sort" in mission_lower:
            numbers = self._extract_numbers_from_text(mission)
            if numbers:
                order = "desc" if "desc" in mission_lower else "asc"
                return {
                    "action": "tool",
                    "tool_name": "sort_array",
                    "args": {"items": numbers, "order": order},
                }

        if "uppercase" in mission_lower and repeat_text:
            return {
                "action": "tool",
                "tool_name": "string_ops",
                "args": {"text": repeat_text, "operation": "uppercase"},
            }
        if "lowercase" in mission_lower and repeat_text:
            return {
                "action": "tool",
                "tool_name": "string_ops",
                "args": {"text": repeat_text, "operation": "lowercase"},
            }
        if "reverse" in mission_lower and repeat_text:
            return {
                "action": "tool",
                "tool_name": "string_ops",
                "args": {"text": repeat_text, "operation": "reverse"},
            }

        if "fibonacci" in mission_lower and (
            "write" in mission_lower or "write_file" in mission_lower
        ):
            path = self._extract_write_path_from_mission(mission) or "fib.txt"
            count = self._extract_fibonacci_count(mission)
            mission_index = self._next_incomplete_mission_index(state)
            reports = state.get("mission_reports", [])
            if 0 <= mission_index < len(reports):
                expected = reports[mission_index].get("expected_fibonacci_count")
                if isinstance(expected, int) and expected > 0:
                    count = expected
            return {
                "action": "tool",
                "tool_name": "write_file",
                "args": {"path": path, "content": self._fibonacci_csv(count)},
            }

        return None

    def _extract_quoted_text(self, text: str) -> str:
        match = re.search(r"""["']([^"']+)["']""", text)
        if not match:
            return ""
        return match.group(1).strip()

    def _extract_numbers_from_text(self, text: str) -> list[int]:
        return [int(token) for token in re.findall(r"-?\d+", text)]

    def _extract_fibonacci_count(self, mission: str) -> int:
        patterns = (
            r"(\d+)(?:st|nd|rd|th)\s+number",
            r"first\s+(\d+)\s+(?:fibonacci\s+)?(?:numbers|terms)",
            r"first\s+(\d+)\s+fibonacci",
            r"until\s+the\s+(\d+)\s+(?:number|numbers|terms)",
            r"(\d+)\s+fibonacci\s+(?:numbers|terms)?",
            r"(\d+)\s+(?:numbers|terms)",
        )
        mission_lower = mission.lower()
        for pattern in patterns:
            match = re.search(pattern, mission_lower)
            if match:
                value = int(match.group(1))
                return max(2, value)
        return 100

    def _fibonacci_csv(self, count: int) -> str:
        numbers = [0, 1]
        while len(numbers) < count:
            numbers.append(numbers[-1] + numbers[-2])
        return ", ".join(str(value) for value in numbers[:count])

    def _extract_missions(self, user_input: str) -> list[str]:
        """Extract mission lines from user input for per-mission reporting."""
        lines = [line.strip() for line in user_input.splitlines() if line.strip()]
        task_lines: list[str] = []
        for line in lines:
            if re.match(r"^(task\s*\d+\s*:)", line, flags=re.IGNORECASE):
                task_lines.append(line)
                continue
            if re.match(r"^\d+[\)\.:\-\s]", line):
                task_lines.append(line)
        if task_lines:
            return task_lines
        return ["Primary mission"]

    def _infer_requirements_from_text(
        self, text: str
    ) -> tuple[set[str], set[str], int | None]:
        """Infer required tools/files from mission or sub-task text."""
        lower = text.lower()
        required_tools: set[str] = set()
        required_files: set[str] = set()

        if re.search(r"\b(uppercase|lowercase|reverse)\b", lower):
            required_tools.add("string_ops")
        if re.search(r"\b(repeat|confirmation)\b", lower):
            required_tools.add("repeat_message")
        if re.search(r"\bretrieve\b", lower) and re.search(r"\bmemo(?:ize)?\b", lower):
            required_tools.add("retrieve_memo")
        if re.search(r"\bmemoize\b", lower):
            required_tools.add("memoize")
        if re.search(r"\bjson\b", lower):
            required_tools.add("json_parser")
        if re.search(r"\b(regex|pattern)\b", lower):
            required_tools.add("regex_matcher")
        if re.search(r"\bextract\b", lower) and (
            re.search(r"\bname\b", lower) or re.search(r"\bnumbers?\b", lower)
        ):
            required_tools.add("regex_matcher")
        if (
            re.search(r"\bsort\b", lower)
            or re.search(r"\bascending\b", lower)
            or re.search(r"\bdescending\b", lower)
            or re.search(r"\balphabetic(?:ally)?\b", lower)
        ):
            required_tools.add("sort_array")
        if re.search(r"\b(mean|sum|median|average)\b", lower):
            required_tools.add("math_stats")
        if (
            re.search(r"\boutliers?\b", lower)
            or re.search(r"\bstatistics?\b", lower)
            or (re.search(r"\banaly(?:s|z)e\b", lower) and re.search(r"\bnumbers?\b", lower))
        ):
            required_tools.add("data_analysis")
        if re.search(r"\banaly(?:s|z)e\b", lower) and re.search(r"\btext\b", lower):
            required_tools.add("text_analysis")
        if (
            re.search(r"\bwrite(?:_file)?\b", lower)
            or "save to" in lower
            or "output to" in lower
        ):
            required_tools.add("write_file")
            path = self._extract_write_path_from_mission(text)
            if path:
                required_files.add(path.replace("\\", "/").rsplit("/", 1)[-1])

        expected_fibonacci_count: int | None = None
        if "fibonacci" in lower:
            required_tools.add("write_file")
            expected_fibonacci_count = self._extract_fibonacci_count(text)
            path = self._extract_write_path_from_mission(text)
            if path:
                required_files.add(path.replace("\\", "/").rsplit("/", 1)[-1])

        return required_tools, required_files, expected_fibonacci_count

    def _build_mission_contracts_from_plan(
        self, structured_plan: StructuredPlan, missions: list[str]
    ) -> list[dict[str, Any]]:
        """Derive per-mission completion contracts from structured plan data."""
        contracts: list[dict[str, Any]] = []
        children_by_parent: dict[str, list[Any]] = {}
        for step in structured_plan.steps:
            if step.parent_id is not None:
                children_by_parent.setdefault(step.parent_id, []).append(step)

        top_level = [step for step in structured_plan.steps if step.parent_id is None]
        for idx, mission in enumerate(missions):
            mission_id = idx + 1
            parent = next((step for step in top_level if step.id == str(mission_id)), None)
            if parent is None and idx < len(top_level):
                parent = top_level[idx]

            required_tools: set[str] = set()
            required_files: set[str] = set()
            expected_fibonacci_count: int | None = None
            checks: list[str] = []
            mission_texts: list[str] = [mission]

            base_tools, base_files, base_fib = self._infer_requirements_from_text(mission)
            required_tools.update(base_tools)
            required_files.update(base_files)
            if base_fib is not None:
                expected_fibonacci_count = base_fib

            if parent is not None:
                for child in children_by_parent.get(parent.id, []):
                    mission_texts.append(child.description)
                    tools, files, fib_count = self._infer_requirements_from_text(child.description)
                    # Child tool mentions are often alternative implementation hints.
                    # Keep completion contracts stable by only requiring write_file when
                    # child text expects an output artifact.
                    if files:
                        required_tools.add("write_file")
                    required_files.update(files)
                    if fib_count is not None:
                        required_tools.add("write_file")
                        expected_fibonacci_count = fib_count

            if expected_fibonacci_count is not None:
                checks.append(f"fibonacci_count={expected_fibonacci_count}")
            if required_files:
                checks.append("required_files")
            if required_tools:
                checks.append("required_tools")
            if any(
                "pattern" in text.lower()
                and ("sum" in text.lower() or "mean" in text.lower())
                for text in mission_texts
            ):
                checks.append("pattern_report_consistency")

            contracts.append(
                {
                    "mission_id": mission_id,
                    "required_tools": sorted(required_tools),
                    "required_files": sorted(required_files),
                    "expected_fibonacci_count": expected_fibonacci_count,
                    "contract_checks": checks,
                }
            )
        return contracts

    def _initialize_mission_reports(
        self, missions: list[str], *, contracts: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        """Build initial mission report objects before tool execution starts."""
        contracts = contracts or []
        reports: list[dict[str, Any]] = []
        for index, mission in enumerate(missions):
            contract = contracts[index] if index < len(contracts) else {}
            reports.append(
                {
                    "mission_id": index + 1,
                    "mission": mission,
                    "used_tools": [],
                    "tool_results": [],
                    "result": "",
                    "status": "pending",
                    "required_tools": list(contract.get("required_tools", [])),
                    "required_files": list(contract.get("required_files", [])),
                    "written_files": [],
                    "expected_fibonacci_count": contract.get("expected_fibonacci_count"),
                    "contract_checks": list(contract.get("contract_checks", [])),
                }
            )
        return reports

    def _next_incomplete_mission_index(self, state: RunState) -> int:
        reports = state.get("mission_reports", [])
        for index, report in enumerate(reports):
            if str(report.get("status", "pending")) != "completed":
                return index
        return -1

    def _refresh_mission_status(self, state: RunState, mission_index: int) -> None:
        """Recompute mission completion from required tools/files."""
        reports = state.get("mission_reports", [])
        if mission_index < 0 or mission_index >= len(reports):
            return
        report = reports[mission_index]
        required_tools = set(report.get("required_tools", []))
        required_files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in report.get("required_files", [])
        }
        if not required_tools and not required_files:
            inferred_tools, inferred_files, inferred_fib_count = self._infer_requirements_from_text(
                str(report.get("mission", ""))
            )
            required_tools = set(inferred_tools)
            required_files = {
                str(path).replace("\\", "/").rsplit("/", 1)[-1]
                for path in inferred_files
            }
            if inferred_tools and not report.get("required_tools"):
                report["required_tools"] = sorted(required_tools)
            if inferred_files and not report.get("required_files"):
                report["required_files"] = sorted(required_files)
            if (
                inferred_fib_count is not None
                and not isinstance(report.get("expected_fibonacci_count"), int)
            ):
                report["expected_fibonacci_count"] = inferred_fib_count
        observed_tools = {str(tool) for tool in report.get("used_tools", [])}
        observed_non_helper_tools = {
            tool for tool in observed_tools if tool not in {"memoize", "retrieve_memo"}
        }
        written_files = {
            str(path).replace("\\", "/").rsplit("/", 1)[-1]
            for path in report.get("written_files", [])
        }

        if required_tools or required_files:
            missing_tools = sorted(required_tools - observed_tools)
        else:
            missing_tools = [] if observed_non_helper_tools else ["<non_helper_tool>"]
        missing_files = sorted(required_files - written_files)

        latest_result: dict[str, Any] = {}
        tool_results = report.get("tool_results", [])
        if tool_results and isinstance(tool_results[-1], dict):
            candidate = tool_results[-1].get("result")
            if isinstance(candidate, dict):
                latest_result = candidate
        has_latest_error = "error" in latest_result

        if missing_tools or missing_files:
            if has_latest_error:
                report["status"] = "failed"
            else:
                report["status"] = "in_progress" if report.get("used_tools") else "pending"
        else:
            report["status"] = "failed" if has_latest_error else "completed"

        completed_tasks = state.get("completed_tasks", [])
        mission_text = str(report.get("mission", "")).strip()
        if report["status"] == "completed":
            if mission_text and mission_text not in completed_tasks:
                completed_tasks.append(mission_text)
        elif mission_text in completed_tasks:
            completed_tasks.remove(mission_text)

    def _record_mission_tool_event(
        self,
        state: RunState,
        tool_name: str,
        tool_result: dict[str, Any],
        *,
        mission_index: int | None = None,
        tool_args: dict[str, Any] | None = None,
    ) -> None:
        """Attach tool usage/results to the intended mission report."""
        reports = state.get("mission_reports", [])
        if not reports:
            contracts = state.get("mission_contracts", [])
            reports = self._initialize_mission_reports(["Primary mission"], contracts=contracts)
            state["mission_reports"] = reports
            state["missions"] = ["Primary mission"]
            state["active_mission_index"] = -1
            state["active_mission_id"] = 0

        pending = state.get("pending_action") or {}
        pending_mission_id = pending.get("__mission_id")
        if mission_index is None and isinstance(pending_mission_id, int):
            mission_index = pending_mission_id - 1
        if mission_index is None:
            active = int(state.get("active_mission_index", -1))
            if tool_name in {"memoize", "retrieve_memo"} and 0 <= active < len(reports):
                mission_index = active
            else:
                mission_index = self._next_incomplete_mission_index(state)
        index = min(max(mission_index if mission_index is not None else 0, 0), len(reports) - 1)

        state["active_mission_index"] = index
        state["active_mission_id"] = index + 1
        mission = reports[index]
        mission.setdefault("status", "pending")
        mission.setdefault("required_tools", [])
        mission.setdefault("required_files", [])
        mission.setdefault("written_files", [])
        mission.setdefault("expected_fibonacci_count", None)
        mission.setdefault("contract_checks", [])
        mission["used_tools"].append(tool_name)
        mission["tool_results"].append({"tool": tool_name, "result": tool_result})
        mission["result"] = str(tool_result)
        if (
            tool_name == "write_file"
            and isinstance(tool_args, dict)
            and "error" not in tool_result
        ):
            written_path = str(tool_args.get("path", "")).strip()
            if written_path:
                basename = written_path.replace("\\", "/").rsplit("/", 1)[-1]
                if basename and basename not in mission["written_files"]:
                    mission["written_files"].append(basename)
        self._refresh_mission_status(state, index)

    def _next_incomplete_mission(self, state: RunState) -> str:
        """Return next mission text with non-completed status."""
        reports = state.get("mission_reports", [])
        next_index = self._next_incomplete_mission_index(state)
        if 0 <= next_index < len(reports):
            return str(reports[next_index].get("mission", ""))
        return ""

    def _all_missions_completed(self, state: RunState) -> bool:
        """Whether every mission report status is completed."""
        reports = state.get("mission_reports", [])
        if not reports:
            return False
        return all(str(report.get("status", "pending")) == "completed" for report in reports)

    def _progress_hint_message(self, state: RunState) -> str:
        """Create a compact progress hint for the planner."""
        reports = state.get("mission_reports", [])
        if not reports:
            missions = state.get("missions", [])
            if not missions:
                return ""
            completed_count = len(state.get("completed_tasks", []))
            next_mission = self._next_incomplete_mission(state)
            if next_mission:
                return (
                    f"Progress: completed {completed_count}/{len(missions)} tasks. "
                    f"Next task: {next_mission}"
                )
            return f"Progress: completed {completed_count}/{len(missions)} tasks. Emit finish now."

        completed_count = sum(
            1 for report in reports if str(report.get("status", "pending")) == "completed"
        )
        next_mission = self._next_incomplete_mission(state)
        if next_mission:
            return (
                f"Progress: completed {completed_count}/{len(reports)} tasks. "
                f"Next task: {next_mission}"
            )
        return f"Progress: completed {completed_count}/{len(reports)} tasks. Emit finish now."

    def _build_auto_finish_answer(self, state: RunState) -> str:
        """Build deterministic summary when all missions are complete."""
        mission_reports = state.get("mission_reports", [])
        summary_parts = ["All tasks completed."]
        for report in mission_reports:
            mission = str(report.get("mission", "")).strip()
            result = str(report.get("result", "")).strip()
            status = str(report.get("status", "pending"))
            if mission and result and status == "completed":
                summary_parts.append(f"{mission} -> {result}")
        return " ".join(summary_parts)

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
        """Normalize common argument aliases before tool execution."""
        normalized = dict(args)
        if tool_name == "sort_array":
            if "items" not in normalized and isinstance(normalized.get("array"), list):
                normalized["items"] = normalized.pop("array")
            if "items" not in normalized and isinstance(normalized.get("values"), list):
                normalized["items"] = normalized.pop("values")
        elif tool_name == "repeat_message":
            if "message" not in normalized and isinstance(normalized.get("text"), str):
                normalized["message"] = normalized.pop("text")
        elif tool_name == "string_ops":
            if "operation" not in normalized and isinstance(normalized.get("op"), str):
                normalized["operation"] = normalized.pop("op")
        elif tool_name == "write_file":
            if "path" not in normalized and isinstance(normalized.get("file_path"), str):
                normalized["path"] = normalized.pop("file_path")
            if "path" not in normalized and isinstance(normalized.get("filename"), str):
                normalized["path"] = normalized.pop("filename")
            if "content" not in normalized and isinstance(normalized.get("text"), str):
                normalized["content"] = normalized.pop("text")
            if "content" not in normalized and isinstance(normalized.get("data"), str):
                normalized["content"] = normalized.pop("data")
        elif tool_name == "memoize":
            if "value" not in normalized and "data" in normalized:
                normalized["value"] = normalized.pop("data")
        elif tool_name == "text_analysis":
            if "operation" not in normalized and isinstance(normalized.get("op"), str):
                normalized["operation"] = normalized.pop("op")
        elif tool_name == "data_analysis":
            if "numbers" not in normalized and isinstance(normalized.get("data"), list):
                normalized["numbers"] = normalized.pop("data")
            if "numbers" not in normalized and isinstance(normalized.get("values"), list):
                normalized["numbers"] = normalized.pop("values")
        elif tool_name == "regex_matcher":
            if "pattern" not in normalized and isinstance(normalized.get("regex"), str):
                normalized["pattern"] = normalized.pop("regex")
        return normalized

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
        """Whether retrieve_memo has already been attempted for any candidate key in this run."""
        if not candidate_keys:
            return True
        for event in state.get("tool_history", []):
            if str(event.get("tool", "")) != "retrieve_memo":
                continue
            args = dict(event.get("args", {}))
            key = str(args.get("key", ""))
            if key in candidate_keys:
                return True
        return False

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
        """Treat memo hit as completion for the next deterministic write mission."""
        reports = state.get("mission_reports", [])
        if not reports:
            return
        index = self._next_incomplete_mission_index(state)
        if index < 0:
            return
        state["active_mission_index"] = index
        state["active_mission_id"] = index + 1
        reports[index]["result"] = str(memo_hit)
        reports[index]["status"] = "completed"
        mission_text = str(reports[index].get("mission", "")).strip()
        if mission_text and mission_text not in state.get("completed_tasks", []):
            state["completed_tasks"].append(mission_text)

    def _cache_key_for_path(self, path: str) -> str:
        """Build cache key for reusable write_file inputs."""
        return f"write_file_input:{path}"

    def _write_cache_candidates(self, path: str) -> list[str]:
        """Return exact and basename keys for reusable write inputs."""
        if not path.strip():
            return []
        keys = [self._cache_key_for_path(path)]
        basename = path.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if basename and basename != path:
            keys.append(self._cache_key_for_path(basename))
        return keys

    def _extract_write_path_from_mission(self, mission: str) -> str:
        """Extract target file path from mission text when present."""
        ext = r"[A-Za-z][A-Za-z0-9]{0,9}"
        quoted_matches = re.findall(rf"""["']([^"']+\.(?:{ext}))["']""", mission)
        if quoted_matches:
            return quoted_matches[-1].strip()
        for match in re.finditer(rf"(/?[A-Za-z0-9_./\\-]+\.(?:{ext}))", mission):
            candidate = match.group(1).strip().rstrip(".,;:")
            # Guard against decimal numbers being interpreted as file paths.
            if re.fullmatch(r"\d+\.\d+", candidate):
                continue
            return candidate
        return ""

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

    def _validate_tool_result_for_active_mission(
        self,
        *,
        state: RunState,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
        mission_index: int | None = None,
    ) -> str | None:
        """Apply deterministic content validation for mission-specific write constraints."""
        if tool_name != "write_file":
            return None
        if "error" in tool_result:
            return None

        reports = state.get("mission_reports", [])
        index = mission_index if mission_index is not None else int(state.get("active_mission_index", -1))
        mission_report = reports[index] if 0 <= index < len(reports) else {}
        mission_text = str(mission_report.get("mission", "")).lower()
        contract_checks = {
            str(check).strip().lower() for check in mission_report.get("contract_checks", [])
        }

        # Fibonacci-specific strict validation.
        fib_count = mission_report.get("expected_fibonacci_count")
        fib_contract_expected = isinstance(fib_count, int) and fib_count > 0
        is_fibonacci_mission = fib_contract_expected or ("fibonacci" in mission_text)
        if is_fibonacci_mission:
            expected_count = mission_report.get("expected_fibonacci_count")
            if not isinstance(expected_count, int) or expected_count <= 0:
                expected_count = self._extract_fibonacci_count(mission_text)

            content = str(tool_args.get("content", ""))
            numbers = self._parse_csv_int_list(content)
            if numbers is None:
                return "write_file content must be a comma-separated list of integers."
            if len(numbers) != expected_count:
                return (
                    f"fibonacci content must contain exactly {expected_count} integers, "
                    f"got {len(numbers)}."
                )
            if len(numbers) < 2 or numbers[0] != 0 or numbers[1] != 1:
                return "fibonacci content must start with 0, 1."

            for seq_index in range(2, len(numbers)):
                expected = numbers[seq_index - 1] + numbers[seq_index - 2]
                if numbers[seq_index] != expected:
                    return (
                        "fibonacci sequence mismatch at index "
                        f"{seq_index}: got {numbers[seq_index]}, expected {expected}."
                    )

        # Pattern report numeric consistency validation.
        should_validate_pattern_report = "pattern_report_consistency" in contract_checks
        # Legacy fallback when contract metadata is unavailable.
        if not contract_checks and "pattern" in mission_text:
            should_validate_pattern_report = (
                "sum" in mission_text or "mean" in mission_text
            )
        if should_validate_pattern_report:
            content = str(tool_args.get("content", ""))
            pattern_error = self._validate_pattern_report_content(content)
            if pattern_error:
                return pattern_error

        return None

    def _parse_csv_int_list(self, content: str) -> list[int] | None:
        """Parse a comma-separated integer list; return None on malformed tokens."""
        tokens = [token.strip() for token in content.split(",") if token.strip()]
        if not tokens:
            return []
        numbers: list[int] = []
        for token in tokens:
            if not re.match(r"^-?\d+$", token):
                return None
            numbers.append(int(token))
        return numbers

    def _validate_pattern_report_content(self, content: str) -> str | None:
        """Ensure pattern report contains numerically consistent sum/mean."""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        if len(lines) < 3:
            return "pattern report must include extracted numbers, sum, and mean lines."

        numbers_line = next((line for line in lines if line.lower().startswith("extracted numbers:")), "")
        sum_line = next((line for line in lines if line.lower().startswith("sum:")), "")
        mean_line = next((line for line in lines if line.lower().startswith("mean:")), "")
        if not numbers_line or not sum_line or not mean_line:
            return "pattern report must contain 'Extracted Numbers', 'Sum', and 'Mean' fields."

        raw_numbers = numbers_line.split(":", 1)[1] if ":" in numbers_line else ""
        number_tokens = [token.strip() for token in raw_numbers.split(",") if token.strip()]
        if not number_tokens:
            return "pattern report numbers list is empty."
        values: list[float] = []
        for token in number_tokens:
            try:
                values.append(float(token))
            except ValueError:
                return f"pattern report contains a non-numeric token: {token!r}."

        sum_match = re.search(r"-?\d+(?:\.\d+)?", sum_line)
        mean_match = re.search(r"-?\d+(?:\.\d+)?", mean_line)
        if not sum_match or not mean_match:
            return "pattern report sum/mean must contain numeric values."
        reported_sum = float(sum_match.group(0))
        reported_mean = float(mean_match.group(0))

        expected_sum = sum(values)
        expected_mean = expected_sum / len(values)
        if round(reported_sum, 2) != round(expected_sum, 2):
            return (
                f"pattern report sum mismatch: got {reported_sum}, "
                f"expected {round(expected_sum, 2)}."
            )
        if round(reported_mean, 3) != round(expected_mean, 3):
            return (
                f"pattern report mean mismatch: got {reported_mean}, "
                f"expected {round(expected_mean, 3)}."
            )
        return None
