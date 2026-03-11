from __future__ import annotations

"""Lifecycle node methods and backward-compat shims for LangGraphOrchestrator.

LifecycleNodesMixin provides:
- _finalize(): End-of-run finalization with audit, partial persistence, Shared_plan.md
- _enforce_memo_policy(): Post-execute policy check for memoization requirements
- _write_shared_plan(): Write structured plan to Shared_plan.md
- _is_unrecoverable_plan_error(): Detect fatal provider errors
- Backward-compat shims delegating to action_parser, mission_tracker, text_extractor, etc.
- Memo/cache infrastructure helpers (lookup, derive-snapshot, auto-lookup-before-write, etc.)

Anti-pattern: do NOT import from graph.py or orchestrator.py here — circular.
"""

import json
from pathlib import Path
from typing import Any

from agentic_workflows.orchestration.langgraph import (
    action_parser,
    content_validator,
    directives,
    fallback_planner,
    memo_manager,
    mission_tracker,
    text_extractor,
)
from agentic_workflows.orchestration.langgraph.mission_auditor import audit_run
from agentic_workflows.orchestration.langgraph.mission_parser import StructuredPlan
from agentic_workflows.orchestration.langgraph.state_schema import (
    MemoEvent,
    RunState,
    ensure_state_defaults,
    utc_now_iso,
)


class LifecycleNodesMixin:
    """Mixin providing lifecycle node methods and backward-compat shims.

    Intended to be used with LangGraphOrchestrator via multiple inheritance.
    Methods here reference self attributes set in LangGraphOrchestrator.__init__.
    """

    # ------------------------------------------------------------------ #
    # Lifecycle nodes                                                      #
    # ------------------------------------------------------------------ #

    def _enforce_memo_policy(self, state: RunState) -> RunState:
        """Require memoization after heavy deterministic tool results."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
        last_tool_name = str(state["policy_flags"].get("last_tool_name", ""))
        if not last_tool_name:
            return state

        if last_tool_name in {"memoize", "retrieve_memo"}:
            return state

        last_args = dict(state["policy_flags"].get("last_tool_args", {}))
        last_result = dict(state["policy_flags"].get("last_tool_result", {}))
        if self.policy.requires_memoization(  # type: ignore[attr-defined]
            tool_name=last_tool_name,
            args=last_args,
            result=last_result,
        ):
            memo_key = self.policy.suggested_memo_key(  # type: ignore[attr-defined]
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
            self.logger.info(  # type: ignore[attr-defined]
                "MEMO REQUIRED step=%s tool=%s key=%s",
                state["step"],
                last_tool_name,
                memo_key,
            )
        self.checkpoint_store.save(  # type: ignore[attr-defined]
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
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            state["final_answer"] = str(pending_action.get("answer", "")).strip()
            state["pending_action"] = None
        if not state.get("final_answer"):
            state["final_answer"] = "Run completed."
        self.logger.info(  # type: ignore[attr-defined]
            "RUN FINALIZE run_id=%s tools_used=%s missions=%s",
            state["run_id"],
            len(state["tool_history"]),
            len(state.get("mission_reports", [])),
        )
        for mission in state.get("mission_reports", []):
            self.logger.info(  # type: ignore[attr-defined]
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
        # Attach structural health metrics to audit report
        state["audit_report"]["structural_health"] = state.get("structural_health", {
            "json_parse_fallback": 0,
            "schema_mismatch": 0,
        })
        self.logger.info(  # type: ignore[attr-defined]
            "AUDIT REPORT run_id=%s passed=%s warned=%s failed=%s",
            state["run_id"],
            audit.passed,
            audit.warned,
            audit.failed,
        )
        for finding in audit.findings:
            if finding.level != "pass":
                self.logger.warning(  # type: ignore[attr-defined]
                    "AUDIT %s mission=%s check=%s detail=%s",
                    finding.level.upper(),
                    finding.mission_id,
                    finding.check,
                    finding.detail,
                )
        # Persist partial mission results for cross-run continuity
        try:
            partial_count = self.context_manager.persist_partial_missions(state)  # type: ignore[attr-defined]
            if partial_count:
                self.logger.info(  # type: ignore[attr-defined]
                    "PARTIAL MISSIONS SAVED run_id=%s count=%s",
                    state["run_id"], partial_count,
                )
        except Exception:
            self.logger.debug(  # type: ignore[attr-defined]
                "persist_partial_missions failed (non-fatal)", exc_info=True
            )
        self._write_shared_plan(state)
        self.checkpoint_store.save(  # type: ignore[attr-defined]
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
            self.logger.warning("Failed to write Shared_plan.md: %s", exc)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Backward-compat shims: delegated to action_parser module             #
    # ------------------------------------------------------------------ #

    def _validate_action(self, model_output: str) -> tuple[dict[str, Any], bool]:
        return action_parser.validate_action(model_output, self.tools)  # type: ignore[attr-defined]

    def _parse_action_json(self, model_output: str, state: RunState | None = None) -> tuple[dict[str, Any], bool]:
        step = (state or {}).get("step", 0)
        return action_parser.parse_action_json(model_output, step=step)

    def _extract_first_json_object(self, text: str) -> str | None:
        return action_parser.extract_first_json_object(text)

    def _extract_all_json_objects(self, text: str) -> list[str]:
        return action_parser.extract_all_json_objects(text)

    def _parse_all_actions_json(self, model_output: str) -> tuple[list[dict[str, Any]], bool]:
        return action_parser.parse_all_actions_json(model_output)

    def _validate_action_from_dict(self, action_dict: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        return action_parser.validate_action_from_dict(action_dict, self.tools)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Backward-compat shims: delegated to mission_tracker module           #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Backward-compat shims: delegated to text_extractor module            #
    # ------------------------------------------------------------------ #

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
            state, tool_name, tool_result, mission_index=mission_index, tool_args=tool_args
        )

    def _next_incomplete_mission(self, state: RunState) -> str:
        return mission_tracker.next_incomplete_mission(state)

    def _next_incomplete_mission_requirements(self, state: RunState) -> dict[str, Any]:
        return mission_tracker.next_incomplete_mission_requirements(state)

    def _all_missions_completed(self, state: RunState) -> bool:
        return mission_tracker.all_missions_completed(state)

    def _progress_hint_message(self, state: RunState) -> str:
        return mission_tracker.progress_hint_message(state)

    def _mission_tool_hint(self, state: RunState) -> str:
        """Return a focused tool hint for the current incomplete mission step."""
        structured_plan = state.get("structured_plan")
        if not structured_plan:
            return ""
        next_idx = self._next_incomplete_mission_index(state)
        if next_idx < 0:
            return ""
        plan_obj = StructuredPlan.from_dict(structured_plan)
        top_level = [s for s in plan_obj.steps if s.parent_id is None]
        if next_idx >= len(top_level):
            return ""
        suggested = top_level[next_idx].suggested_tools
        if not suggested:
            return ""
        return f"Suggested tools for this task: {', '.join(suggested)}"

    def _build_auto_finish_answer(self, state: RunState) -> str:
        return mission_tracker.build_auto_finish_answer(state)

    def _normalize_tool_args(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        return fallback_planner.normalize_tool_args(tool_name, args)

    # ------------------------------------------------------------------ #
    # Memo lookup and cache helpers                                        #
    # ------------------------------------------------------------------ #

    def _memo_lookup_candidates_for_action(
        self, *, tool_name: str, tool_args: dict[str, Any]
    ) -> list[str]:
        """Build exact/fallback memo lookup keys that should be attempted before recompute."""
        if tool_name != "write_file":
            return []
        path = str(tool_args.get("path", "")).strip()
        if not path:
            return []
        exact_key = self.policy.suggested_memo_key(  # type: ignore[attr-defined]
            tool_name=tool_name,
            args={"path": path},
            result={},
        )
        candidates = [exact_key]
        basename = path.replace("\\", "/").rsplit("/", 1)[-1].strip()
        if basename and basename != path:
            candidates.append(
                self.policy.suggested_memo_key(  # type: ignore[attr-defined]
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
            self.logger.info(  # type: ignore[attr-defined]
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
            self.logger.info(  # type: ignore[attr-defined]
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
            self.logger.info(  # type: ignore[attr-defined]
                "TOOL EXEC step=%s tool=%s args=%s", state["step"], "retrieve_memo", retrieve_args
            )
            tool_result = self.tools["retrieve_memo"].execute(retrieve_args)  # type: ignore[attr-defined]
            self.logger.info(  # type: ignore[attr-defined]
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
            self.logger.info(  # type: ignore[attr-defined]
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
        attempt_key = f"{target_index}:{target_path.replace(chr(92), '/').rsplit('/', 1)[-1]}"
        if attempt_key in attempted_entries:
            return False

        for key in self._write_cache_candidates(target_path):
            lookup = self.memo_store.get_latest(key=key, namespace="cache")  # type: ignore[attr-defined]
            if not lookup.found:
                continue
            payload = lookup.value if isinstance(lookup.value, dict) else {}
            cached_content = payload.get("content")
            if not isinstance(cached_content, str) or not cached_content:
                continue

            write_args = {"path": target_path, "content": cached_content}
            self.logger.info(  # type: ignore[attr-defined]
                "CACHE REUSE HIT step=%s mission=%s key=%s source_run=%s",
                state["step"],
                mission,
                key,
                lookup.run_id,
            )
            tool_result = self.tools["write_file"].execute(write_args)  # type: ignore[attr-defined]
            validation_error = self._validate_tool_result_for_active_mission(  # type: ignore[attr-defined]
                state=state,
                tool_name="write_file",
                tool_args=write_args,
                tool_result=tool_result,
                mission_index=target_index,
            )
            if validation_error:
                self.logger.warning(  # type: ignore[attr-defined]
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
        self.logger.info(  # type: ignore[attr-defined]
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
            put_result = self.memo_store.put(  # type: ignore[attr-defined]
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
            self.logger.info(  # type: ignore[attr-defined]
                "CACHE WRITE INPUT STORED step=%s key=%s hash=%s",
                state["step"],
                put_result.key,
                put_result.value_hash,
            )

    # ------------------------------------------------------------------ #
    # Backward-compat shims: delegated to content_validator module         #
    # ------------------------------------------------------------------ #

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
