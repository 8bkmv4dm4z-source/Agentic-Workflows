from __future__ import annotations

"""Planner node for LangGraphOrchestrator.

PlannerNodeMixin provides:
- _plan_next_action(): the core planning loop that calls the model provider,
  parses JSON actions, handles queue pop, timeout mode, empty output escalation,
  format drift correction, cloud fallback, and error recovery.

This mixin is intended to be composed with LangGraphOrchestrator via multiple
inheritance. All self.* accesses are resolved on the orchestrator instance.

Anti-pattern: do NOT import from graph.py or orchestrator.py here — circular.
"""

import json
import os
import re
from typing import Any

from agentic_workflows.logger import get_logger
from agentic_workflows.observability import report_schema_compliance
from agentic_workflows.orchestration.langgraph.model_router import RoutingSignals
from agentic_workflows.orchestration.langgraph.provider import ProviderTimeoutError
from agentic_workflows.orchestration.langgraph.state_schema import RunState, ensure_state_defaults

_api_logger = get_logger("api_debug")


class PlannerNodeMixin:
    """Mixin providing _plan_next_action() for LangGraphOrchestrator.

    Intended to be used with LangGraphOrchestrator via multiple inheritance.
    Methods here reference self attributes set in LangGraphOrchestrator.__init__.
    """

    def _plan_next_action(self, state: RunState) -> RunState:  # noqa: C901  # method is intentionally large
        """Call the model planner and parse one strict JSON action."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
        self.context_manager.compact(state)  # type: ignore[attr-defined]
        # Proactive compaction against provider context limit
        try:
            ctx_limit = self.provider.context_size()  # type: ignore[attr-defined]
            self.context_manager.proactive_compact(state, ctx_limit)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass  # graceful degradation -- don't crash if proactive compact fails
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            return state
        state["step"] = state.get("step", 0) + 1
        self.logger.info(  # type: ignore[attr-defined]
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
        self._log_parser_state(state)  # type: ignore[attr-defined]
        self._emit_trace(state, "loop_state",  # type: ignore[attr-defined]
            step=state["step"],
            queue_depth=len(state.get("pending_action_queue", [])),
            completed_count=sum(
                1 for r in state.get("mission_reports", [])
                if str(r.get("status", "")) == "completed"
            ),
            total_count=len(state.get("mission_reports", [])),
            timeout_mode=bool(state.get("policy_flags", {}).get("planner_timeout_mode", False)),
        )
        if state["step"] > self.max_steps:  # type: ignore[attr-defined]
            fail_message = (
                "Run stopped: exceeded orchestrator step budget before mission completion. "
                "Review mission attribution and planner behavior."
            )
            state["messages"].append({"role": "system", "content": fail_message})
            state["pending_action"] = {"action": "finish", "answer": fail_message}
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_step_budget_fail_closed",
                state=state,
            )
            return state
        if self._maybe_complete_next_write_from_cache(state):  # type: ignore[attr-defined]
            if self._all_missions_completed(state):  # type: ignore[attr-defined]
                state["pending_action"] = {
                    "action": "finish",
                    "answer": self._build_auto_finish_answer(state),  # type: ignore[attr-defined]
                }
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_cache_reuse",
                state=state,
            )
            return state
        if self._enforce_rerun_completion_guard(state):  # type: ignore[attr-defined]
            return state
        # --- Action queue: pop next queued action before calling provider ---
        queue = state.get("pending_action_queue", [])
        if queue and not state.get("policy_flags", {}).get("memo_required", False):
            next_action_raw = queue.pop(0)
            state["pending_action_queue"] = queue
            try:
                validated, _used_fallback = self._validate_action_from_dict(next_action_raw)  # type: ignore[attr-defined]
                queued_mission_id = int(validated.get("__mission_id", 0))
                self._log_queue_mission_spacing(  # type: ignore[attr-defined]
                    state=state,
                    mission_id=queued_mission_id,
                    source="queue_pop",
                )
                self.logger.info(  # type: ignore[attr-defined]
                    "PLAN QUEUE POP step=%s queue_remaining=%s action=%s",
                    state["step"],
                    len(queue),
                    validated,
                )
                self._log_planner_output(  # type: ignore[attr-defined]
                    state=state,
                    source="queue_pop",
                    action=validated,
                    queue_remaining=len(queue),
                )
                self._emit_trace(state, "planner_output",  # type: ignore[attr-defined]
                    source="queue_pop",
                    action_type=str(validated.get("action", "")),
                    tool_name=str(validated.get("tool_name", "")),
                    mission_id=int(validated.get("__mission_id", 0) or 0),
                )
                if validated.get("action") == "finish" and not self._all_missions_completed(state):  # type: ignore[attr-defined]
                    _rpts = state.get("mission_reports", [])
                    _conversational = (
                        len(_rpts) == 1
                        and not _rpts[0].get("required_tools")
                        and not _rpts[0].get("required_files")
                    )
                    if not _conversational:
                        return self._reject_finish_and_recover(  # type: ignore[attr-defined]
                            state=state,
                            rejected_action=validated,
                            source="queue",
                        )
                state["pending_action"] = validated
                self._reset_finish_rejection_tracking(state)  # type: ignore[attr-defined]
                state["retry_counts"]["provider_timeout"] = 0
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_queue_pop",
                    state=state,
                )
                return state
            except (ValueError, Exception) as exc:
                self.logger.warning(  # type: ignore[attr-defined]
                    "PLAN QUEUE SKIP step=%s error=%s",
                    state["step"],
                    str(exc),
                )
                state["pending_action_queue"] = queue
        if bool(state.get("policy_flags", {}).get("planner_timeout_mode", False)):
            fallback_action = self._deterministic_fallback_action(state)  # type: ignore[attr-defined]
            if fallback_action is not None:
                fallback_requirements = self._next_incomplete_mission_requirements(state)  # type: ignore[attr-defined]
                self.logger.warning(  # type: ignore[attr-defined]
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
                self._log_planner_output(  # type: ignore[attr-defined]
                    state=state,
                    source="timeout_mode",
                    action=fallback_action,
                    queue_remaining=len(state.get("pending_action_queue", [])),
                )
                self._emit_trace(state, "planner_output",  # type: ignore[attr-defined]
                    source="timeout_mode",
                    action_type=str(fallback_action.get("action", "")),
                    tool_name=str(fallback_action.get("tool_name", "")),
                    mission_id=int(fallback_action.get("__mission_id", 0) or 0),
                )
                state["pending_action"] = fallback_action
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_timeout_mode",
                    state=state,
                )
                return state
        progress_message = self._progress_hint_message(state)  # type: ignore[attr-defined]
        if progress_message:
            state["messages"].append({"role": "user", "content": f"[Orchestrator] {progress_message}"})
        context_injection = self.context_manager.build_planner_context_injection(state)  # type: ignore[attr-defined]
        if context_injection:
            state["messages"].append({"role": "user", "content": context_injection})

        # Auto-inject context hint at step 1 to nudge query_context usage
        if (
            state["step"] == 1
            and self._mission_context_store is not None  # type: ignore[attr-defined]
            and "query_context" in self.tools  # type: ignore[attr-defined]
            and "[Cross-run]" not in (context_injection or "")
        ):
            try:
                goal_text = self.context_manager._get_current_goal_text(state)  # type: ignore[attr-defined]
                if goal_text:
                    cascade_hits = self._mission_context_store.query_cascade(  # type: ignore[attr-defined]
                        goal_text, top_k=1,
                    )
                    if cascade_hits and cascade_hits[0].get("score", 0) > 0.5:
                        state["messages"].append({
                            "role": "user",
                            "content": "[Context] Prior relevant missions found. Use query_context tool for details.",
                        })
                        self.logger.info(  # type: ignore[attr-defined]
                            "AUTO CONTEXT HINT step=1 score=%.2f goal=%s",
                            cascade_hits[0].get("score", 0),
                            goal_text[:60],
                        )
            except Exception:  # noqa: BLE001
                pass  # non-fatal — don't block planning if cascade fails

        tool_hint = self._mission_tool_hint(state)  # type: ignore[attr-defined]
        if tool_hint:
            state["messages"].append({"role": "user", "content": f"[Orchestrator] {tool_hint}"})

        # --- Token budget gate: switch to deterministic fallback when exhausted ---
        budget_remaining = state.get("token_budget_remaining", 100_000)
        if budget_remaining <= 0:
            self.logger.info(  # type: ignore[attr-defined]
                "TOKEN BUDGET EXHAUSTED step=%s used=%s — switching to deterministic fallback",
                state["step"],
                state.get("token_budget_used", 0),
            )
            state["policy_flags"]["planner_timeout_mode"] = True

        model_output = ""  # ensure binding for except-block retry-hint logic
        _signals: RoutingSignals = {}  # type: ignore[typeddict-item]
        try:
            self.logger.info(  # type: ignore[attr-defined]
                "PLAN PROVIDER CALL step=%s timeout_seconds=%.2f",
                state["step"],
                self.plan_call_timeout_seconds,  # type: ignore[attr-defined]
            )
            _intent = (state.get("structured_plan") or {}).get("intent_classification")
            _signals = {
                "token_budget_remaining": int(state.get("token_budget_remaining", 100000)),
                "mission_type": "multi_step",  # Always route planning to strong model
                "retry_count": int(state["retry_counts"].get("provider_timeout", 0)),
                "step": state["step"],
                "intent_classification": _intent,
            }
            # Track routing decision in structural_health
            _routed_provider = self._router.route_by_signals(_signals)  # type: ignore[attr-defined]
            _tier = "strong" if _routed_provider is self._router._strong else "fast"  # type: ignore[attr-defined]
            state["structural_health"]["routing_decisions"][_tier] = (
                state["structural_health"].get("routing_decisions", {}).get(_tier, 0) + 1
            )
            model_output = self._generate_with_hard_timeout(  # type: ignore[attr-defined]
                state["messages"],
                signals=_signals,
                provider=self._planner_provider,  # type: ignore[attr-defined]
            ).strip()
            self.logger.info("MODEL OUTPUT step=%s output=%s", state["step"], model_output[:500])  # type: ignore[attr-defined]
            _api_logger.info(
                "PLANNER_STEP step=%s model=%s provider=%s tier=%s "
                "routing_signals=%s tokens_est=%d output_preview=%s",
                state["step"],
                getattr(_routed_provider, "model", "unknown"),
                type(_routed_provider).__name__,
                _tier,
                _signals,
                len(model_output) // 4,
                model_output[:200],
            )

            # Treat a bare "{}" as semantically empty — the GBNF grammar allows
            # it syntactically but it carries no action information.  Normalising
            # it to "" here lets the empty-output escalation below inject a
            # targeted recovery hint instead of spinning in the PLAN INVALID loop.
            if model_output == "{}":
                self.logger.warning(  # type: ignore[attr-defined]
                    "PLAN EMPTY JSON OBJECT step=%s — treating as empty output",
                    state["step"],
                )
                model_output = ""

            # --- Empty-output escalation ---
            if not model_output:
                empty_count = int(state["retry_counts"].get("consecutive_empty", 0)) + 1
                state["retry_counts"]["consecutive_empty"] = empty_count
                self.logger.warning(  # type: ignore[attr-defined]
                    "PLAN EMPTY OUTPUT step=%s consecutive_empty=%s",
                    state["step"],
                    empty_count,
                )
                empty_threshold = max(self.max_invalid_plan_retries // 2, 1)  # type: ignore[attr-defined]
                if empty_count >= empty_threshold:
                    # Deterministic fallback — always clarify, never refuse
                    fallback = {
                        "action": "clarify",
                        "question": (
                            "I had difficulty processing your request. "
                            "Could you rephrase or provide more details about what you'd like me to do?"
                        ),
                    }
                    self.logger.warning(  # type: ignore[attr-defined]
                        "PLAN EMPTY FALLBACK step=%s action=%s",
                        state["step"],
                        fallback["action"],
                    )
                    state["messages"].append({"role": "assistant", "content": json.dumps(fallback)})
                    state["pending_action"] = fallback
                    self.checkpoint_store.save(  # type: ignore[attr-defined]
                        run_id=state["run_id"],
                        step=state["step"],
                        node_name="plan_empty_fallback",
                        state=state,
                    )
                    return state
                # Escalating hint
                if empty_count <= 2:
                    hint = (
                        "Your response was empty. You MUST return exactly one JSON object. "
                        'If no tool is needed, use: {"action":"finish","answer":"<your answer>"} '
                        'or {"action":"clarify","question":"<your question>"}'
                    )
                else:
                    user_text = ""
                    for m in state["messages"]:
                        if m.get("role") == "user":
                            user_text = m.get("content", "")
                            break
                    hint = (
                        "Your response was empty. The user asked: "
                        f'"{user_text[:200]}". '
                        "Respond with exactly this format (fill in the blank): "
                        '{"action":"finish","answer":"___"}'
                    )
                state["messages"].append({"role": "user", "content": f"[Orchestrator] {hint}"})
                state["pending_action"] = None
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_empty_retry",
                    state=state,
                )
                return state
            # Reset consecutive_empty on non-empty output
            state["retry_counts"]["consecutive_empty"] = 0

            if model_output:
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
            all_actions, _parse_used_fallback = self._parse_all_actions_json(model_output)  # type: ignore[attr-defined]
            report_schema_compliance(
                role=state.get("active_specialist", "supervisor"),
                first_attempt_success=not _parse_used_fallback,
                run_id=state.get("run_id"),
            )
            if _parse_used_fallback:
                state["structural_health"]["json_parse_fallback"] = (
                    state["structural_health"].get("json_parse_fallback", 0) + 1
                )
            if not all_actions:
                raise ValueError("no valid JSON action objects found in model output")
            tagged_actions: list[dict[str, Any]] = []
            mission_preview = self._mission_preview_from_state(state)  # type: ignore[attr-defined]
            for raw_action in all_actions:
                action_with_meta = dict(raw_action)
                mission_id = self._resolve_mission_id_for_action(  # type: ignore[attr-defined]
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
            previews = [self._planner_action_preview(a) for a in tagged_actions[:5]]  # type: ignore[attr-defined]
            self.logger.info(  # type: ignore[attr-defined]
                "PLANNER PARSED OUTPUT step=%s actions=%s previews=%s",
                state["step"],
                len(tagged_actions),
                previews,
            )

            action, _validate_used_fallback = self._validate_action_from_dict(tagged_actions[0])  # type: ignore[attr-defined]
            if _validate_used_fallback:
                state["structural_health"]["json_parse_fallback"] = (
                    state["structural_health"].get("json_parse_fallback", 0) + 1
                )
            _api_logger.info(
                "PLANNER_PARSE step=%s action=%s tool=%s fallback=%s",
                state["step"],
                action.get("action", "unknown") if isinstance(action, dict) else "unknown",
                action.get("tool_name", "none") if isinstance(action, dict) else "none",
                str(_parse_used_fallback or _validate_used_fallback),
            )
            # --- Format correction escalation chain ---
            # Targets parseable-but-non-canonical output (fallback recovered a valid action).
            # Step 1: free hint, Step 2: retry (costs 1 LLM call), Step 3+: accept.
            if _parse_used_fallback or _validate_used_fallback:
                drift_count = int(state["retry_counts"].get("consecutive_format_drift", 0)) + 1
                state["retry_counts"]["consecutive_format_drift"] = drift_count

                if drift_count == 1:
                    # Step 1: Free hint -- continue with the parsed action
                    state["structural_health"]["format_correction_hints"] = (
                        state["structural_health"].get("format_correction_hints", 0) + 1
                    )
                    state["messages"].append({
                        "role": "user",
                        "content": (
                            '[Orchestrator] Your JSON format was non-standard. Use exactly: '
                            '{"action":"tool","tool_name":"X","args":{...}} or '
                            '{"action":"finish","answer":"X"}'
                        ),
                    })
                elif drift_count == 2:
                    # Step 2: Retry with system correction (costs 1 LLM call)
                    state["structural_health"]["format_retries"] = (
                        state["structural_health"].get("format_retries", 0) + 1
                    )
                    state["messages"].append({
                        "role": "user",
                        "content": (
                            "[Orchestrator] CRITICAL: Your responses MUST use this exact format: "
                            '{"action":"tool","tool_name":"<name>","args":{...}} -- '
                            "nested args under the 'args' key, not flat."
                        ),
                    })
                    state["pending_action"] = None  # Force re-plan
                    return state
                else:
                    # drift_count >= 3: Accept and continue (already have valid parsed action)
                    self._consecutive_parse_failures += 1  # type: ignore[attr-defined]
                    self.logger.warning(  # type: ignore[attr-defined]
                        "FORMAT DRIFT ACCEPTED step=%s drift_count=%s consecutive_parse_failures=%s",
                        state["step"],
                        drift_count,
                        self._consecutive_parse_failures,  # type: ignore[attr-defined]
                    )
                    # Cloud fallback on 2+ consecutive parse failures
                    if self._consecutive_parse_failures >= 2 and self._fallback_provider is not None:  # type: ignore[attr-defined]
                        try:
                            self.logger.info(  # type: ignore[attr-defined]
                                "CLOUD FALLBACK ATTEMPT step=%s reason=parse_failures",
                                state["step"],
                            )
                            cloud_output = self._fallback_provider.generate(  # type: ignore[attr-defined]
                                state["messages"], response_schema=self._action_json_schema  # type: ignore[attr-defined]
                            ).strip()
                            state["structural_health"]["cloud_fallback_count"] = (
                                state["structural_health"].get("cloud_fallback_count", 0) + 1
                            )
                            state["structural_health"].setdefault("local_model_failures", {"timeout": 0, "parse": 0})
                            state["structural_health"]["local_model_failures"]["parse"] = (
                                state["structural_health"]["local_model_failures"].get("parse", 0) + 1
                            )
                            self._consecutive_parse_failures = 0  # type: ignore[attr-defined]
                            if cloud_output and cloud_output != "{}":
                                cloud_actions, _ = self._parse_all_actions_json(cloud_output)  # type: ignore[attr-defined]
                                if cloud_actions:
                                    action, _ = self._validate_action_from_dict(cloud_actions[0])  # type: ignore[attr-defined]
                                    # Replace the locally-parsed action with cloud-parsed one
                                    state["messages"][-1] = {"role": "assistant", "content": cloud_output}
                        except Exception:  # noqa: BLE001
                            self.logger.warning(  # type: ignore[attr-defined]
                                "CLOUD FALLBACK FAILED step=%s reason=parse — using locally parsed action",
                                state["step"],
                            )
            else:
                # Reset on clean parse
                self._consecutive_parse_failures = 0  # type: ignore[attr-defined]
                state["retry_counts"]["consecutive_format_drift"] = 0

            if len(all_actions) > 1:
                if self.strict_single_action_mode:  # type: ignore[attr-defined]
                    state["pending_action_queue"] = []
                    self.logger.info(  # type: ignore[attr-defined]
                        "PLAN STRICT SINGLE ACTION step=%s discarded=%s",
                        state["step"],
                        len(tagged_actions) - 1,
                    )
                else:
                    state["pending_action_queue"] = tagged_actions[1:]
                    self.logger.info(  # type: ignore[attr-defined]
                        "PLAN QUEUED step=%s queued=%s",
                        state["step"],
                        len(tagged_actions) - 1,
                    )
                state["retry_counts"]["provider_timeout"] = 0
            if action.get("action") == "finish" and not self._all_missions_completed(state):  # type: ignore[attr-defined]
                _rpts = state.get("mission_reports", [])
                _input_is_substantive = len(state.get("user_input", "")) > 30
                _conversational = (
                    len(_rpts) == 1
                    and not _rpts[0].get("required_tools")
                    and not _rpts[0].get("required_files")
                    and not _input_is_substantive
                )
                if not _conversational:
                    return self._reject_finish_and_recover(  # type: ignore[attr-defined]
                        state=state,
                        rejected_action=action,
                        source="provider",
                    )
            self.logger.info("PLANNED ACTION step=%s action=%s", state["step"], action)  # type: ignore[attr-defined]
            planned_mission_id = int(action.get("__mission_id", 0))
            self._log_queue_mission_spacing(  # type: ignore[attr-defined]
                state=state,
                mission_id=planned_mission_id,
                source="planned_action",
            )
            self._log_planner_output(  # type: ignore[attr-defined]
                state=state,
                source="provider",
                action=action,
                queue_remaining=len(state.get("pending_action_queue", [])),
            )
            self._emit_trace(state, "planner_output",  # type: ignore[attr-defined]
                source="provider",
                action_type=str(action.get("action", "")),
                tool_name=str(action.get("tool_name", "")),
                mission_id=int(action.get("__mission_id", 0) or 0),
            )
            state["pending_action"] = action
            self._reset_finish_rejection_tracking(state)  # type: ignore[attr-defined]
            self.checkpoint_store.save(  # type: ignore[attr-defined]
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
            self.logger.warning(  # type: ignore[attr-defined]
                "PLAN PROVIDER TIMEOUT step=%s timeout_count=%s error=%s",
                state["step"],
                timeout_count,
                error_text,
            )
            # Track local model timeout failure
            state["structural_health"].setdefault("local_model_failures", {"timeout": 0, "parse": 0})
            state["structural_health"]["local_model_failures"]["timeout"] = (
                state["structural_health"]["local_model_failures"].get("timeout", 0) + 1
            )

            # --- Cloud fallback on timeout: try fallback provider before deterministic ---
            if self._fallback_provider is not None:  # type: ignore[attr-defined]
                try:
                    self.logger.info(  # type: ignore[attr-defined]
                        "CLOUD FALLBACK ATTEMPT step=%s reason=timeout",
                        state["step"],
                    )
                    model_output = self._fallback_provider.generate(  # type: ignore[attr-defined]
                        state["messages"], response_schema=self._action_json_schema  # type: ignore[attr-defined]
                    ).strip()
                    state["structural_health"]["cloud_fallback_count"] = (
                        state["structural_health"].get("cloud_fallback_count", 0) + 1
                    )
                    self.logger.info(  # type: ignore[attr-defined]
                        "CLOUD FALLBACK SUCCESS step=%s output=%s",
                        state["step"],
                        model_output[:200],
                    )
                    # Feed cloud output into normal parsing path
                    if model_output and model_output != "{}":
                        state["messages"].append({"role": "assistant", "content": model_output})
                        state["policy_flags"]["planner_timeout_mode"] = False
                        all_actions, _pf = self._parse_all_actions_json(model_output)  # type: ignore[attr-defined]
                        report_schema_compliance(
                            role=state.get("active_specialist", "supervisor"),
                            first_attempt_success=not _pf,
                            run_id=state.get("run_id"),
                        )
                        if all_actions:
                            action, _ = self._validate_action_from_dict(all_actions[0])  # type: ignore[attr-defined]
                            state["pending_action"] = action
                            if len(all_actions) > 1 and not self.strict_single_action_mode:  # type: ignore[attr-defined]
                                state["pending_action_queue"] = all_actions[1:]
                            self.checkpoint_store.save(  # type: ignore[attr-defined]
                                run_id=state["run_id"],
                                step=state["step"],
                                node_name="plan_cloud_fallback",
                                state=state,
                            )
                            return state
                except Exception:  # noqa: BLE001
                    self.logger.warning(  # type: ignore[attr-defined]
                        "CLOUD FALLBACK FAILED step=%s — falling through to deterministic",
                        state["step"],
                    )

            fallback_action = self._deterministic_fallback_action(state)  # type: ignore[attr-defined]
            if fallback_action is not None:
                fallback_requirements = self._next_incomplete_mission_requirements(state)  # type: ignore[attr-defined]
                self.logger.warning(  # type: ignore[attr-defined]
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
                self._log_planner_output(  # type: ignore[attr-defined]
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
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_timeout_fallback",
                    state=state,
                )
                return state

            if timeout_count >= self.max_provider_timeout_retries:  # type: ignore[attr-defined]
                fail_message = (
                    f"Planner failed after provider timeout retries: {error_text}. Stopping."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_fail_provider_timeout",
                    state=state,
                )
                return state

            state["messages"].append(
                {
                    "role": "user",
                    "content": (
                        "[Orchestrator] Provider timeout while planning. Retry and return exactly one valid JSON object."
                    ),
                }
            )
            state["pending_action"] = None
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_provider_timeout",
                state=state,
            )
            return state
        except Exception as exc:
            error_text = str(exc)
            # --- Context overflow handling: compact and retry once ---
            if "exceed_context_size" in error_text.lower() or "context length" in error_text.lower():
                self.logger.warning(  # type: ignore[attr-defined]
                    "CONTEXT OVERFLOW step=%s -- triggering aggressive compaction and retry",
                    state["step"],
                )
                try:
                    self.context_manager.proactive_compact(state, self.provider.context_size())  # type: ignore[attr-defined]
                    model_output = self._generate_with_hard_timeout(  # type: ignore[attr-defined]
                        state["messages"], signals=_signals,
                    ).strip()
                    if model_output:
                        state["messages"].append({"role": "assistant", "content": model_output})
                        state["policy_flags"]["planner_timeout_mode"] = False
                        all_actions, _pf = self._parse_all_actions_json(model_output)  # type: ignore[attr-defined]
                        report_schema_compliance(
                            role=state.get("active_specialist", "supervisor"),
                            first_attempt_success=not _pf,
                            run_id=state.get("run_id"),
                        )
                        if all_actions:
                            action, _ = self._validate_action_from_dict(all_actions[0])  # type: ignore[attr-defined]
                            state["pending_action"] = action
                            self.checkpoint_store.save(  # type: ignore[attr-defined]
                                run_id=state["run_id"],
                                step=state["step"],
                                node_name="plan_context_overflow_retry",
                                state=state,
                            )
                            return state
                except Exception:  # noqa: BLE001
                    self.logger.warning(  # type: ignore[attr-defined]
                        "CONTEXT OVERFLOW RETRY FAILED step=%s -- falling through to deterministic fallback",
                        state["step"],
                    )
                # Fall through to deterministic fallback
                state["policy_flags"]["planner_timeout_mode"] = True
                fallback_action = self._deterministic_fallback_action(state)  # type: ignore[attr-defined]
                if fallback_action is not None:
                    state["pending_action"] = fallback_action
                    self.checkpoint_store.save(  # type: ignore[attr-defined]
                        run_id=state["run_id"],
                        step=state["step"],
                        node_name="plan_context_overflow_fallback",
                        state=state,
                    )
                    return state
            if "schema error" in error_text.lower() or "validation" in error_text.lower():
                state["structural_health"]["schema_mismatch"] = (
                    state["structural_health"].get("schema_mismatch", 0) + 1
                )
            invalid_count = int(state["retry_counts"].get("invalid_json", 0)) + 1
            state["retry_counts"]["invalid_json"] = invalid_count
            self._emit_trace(state, "planner_retry", reason="invalid_json", retry_count=invalid_count)  # type: ignore[attr-defined]
            self.logger.warning(  # type: ignore[attr-defined]
                "PLAN INVALID step=%s invalid_count=%s error=%s",
                state["step"],
                invalid_count,
                error_text,
            )

            if self._is_unrecoverable_plan_error(error_text):  # type: ignore[attr-defined]
                fail_message = (
                    f"Planner failed with unrecoverable provider error: {error_text}. Stopping."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_fail_unrecoverable",
                    state=state,
                )
                return state

            if invalid_count >= self.max_invalid_plan_retries:  # type: ignore[attr-defined]
                fail_message = (
                    "Planner failed to produce a valid JSON action after "
                    f"{invalid_count} attempts (last error: {error_text}). "
                    "Stopping to avoid recursion-limit failure."
                )
                state["messages"].append({"role": "system", "content": fail_message})
                state["pending_action"] = {"action": "finish", "answer": fail_message}
                self.checkpoint_store.save(  # type: ignore[attr-defined]
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="plan_fail_closed",
                    state=state,
                )
                return state

            # Try to identify what tool the model was attempting so the hint is specific.
            _tool_match = re.search(
                r'"tool_name"\s*:\s*"([^"]{1,60})"'
                r'|"action"\s*:\s*"([^"]{1,60})"'
                r'|"tool"\s*:\s*"([^"]{1,60})"',
                model_output,
            )
            _attempted = None
            if _tool_match:
                _attempted = (
                    _tool_match.group(1) or _tool_match.group(2) or _tool_match.group(3) or ""
                ).strip()
                if _attempted in {"tool", "finish", "clarify"}:
                    _attempted = None  # too generic to be useful

            # Detect wrong-key schema: model used "tool" instead of "action"+"tool_name"
            _used_tool_key = bool(
                re.search(r'"tool"\s*:\s*"', model_output)
                and '"action"' not in model_output
            )

            if invalid_count <= 2:
                if _used_tool_key and _attempted:
                    retry_hint = (
                        f'Wrong format: you used {{"tool":"{_attempted}",...}} but the required '
                        f'format is {{"action":"tool","tool_name":"{_attempted}","args":{{...}}}}. '
                        "Retry with the correct keys."
                    )
                elif _attempted:
                    retry_hint = (
                        f"Your JSON for '{_attempted}' was malformed ({error_text}). "
                        f"Fix the JSON syntax and retry '{_attempted}' with a valid JSON object. "
                        "Ensure all strings are properly closed and escaped."
                    )
                else:
                    retry_hint = (
                        f"Invalid action ({error_text}). You MUST return one of:\n"
                        '{"action":"tool","tool_name":"<tool>","args":{...}}\n'
                        '{"action":"finish","answer":"<summary>"}'
                    )
            elif invalid_count <= 4:
                retry_hint = (
                    f"Invalid action ({error_text}). You MUST return one of these JSON formats:\n"
                    '{"action":"tool","tool_name":"<tool>","args":{...}}\n'
                    '{"action":"finish","answer":"<summary>"}\n'
                    '{"action":"clarify","question":"<question>"}\n'
                    "If no tool is needed, use finish."
                )
            else:
                user_text = ""
                for m in state["messages"]:
                    if m.get("role") == "user":
                        user_text = m.get("content", "")
                        break
                retry_hint = (
                    f"Invalid action ({error_text}). The user asked: "
                    f'"{user_text[:200]}". '
                    "Respond with exactly: "
                    '{"action":"finish","answer":"___"} (fill in the blank)'
                )
            state["messages"].append(
                {"role": "user", "content": f"[Orchestrator] {retry_hint}"}
            )
            state["pending_action"] = None
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_error",
                state=state,
            )
            return state
