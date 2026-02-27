from __future__ import annotations

"""Phase 1 LangGraph orchestrator.

This module is the Layer-2 orchestration engine: it plans model actions,
executes deterministic tools, enforces memoization policy, and produces
run/mission reports using only local state for final snapshots.
"""

import json
import re
from typing import Any

from pydantic import ValidationError

from execution.langgraph.checkpoint_store import SQLiteCheckpointStore
from execution.langgraph.memo_store import SQLiteMemoStore
from execution.langgraph.policy import MemoizationPolicy
from execution.langgraph.provider import ChatProvider, build_provider
from execution.langgraph.state_schema import (
    MemoEvent,
    RunState,
    ensure_state_defaults,
    new_run_state,
    utc_now_iso,
)
from execution.langgraph.tools_registry import build_tool_registry
from logger import get_logger
from schemas import FinishAction, ToolAction
from tools.base import Tool

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
        max_content_validation_retries: int = 2,
    ) -> None:
        self.provider = provider or build_provider()
        self.memo_store = memo_store or SQLiteMemoStore()
        self.checkpoint_store = checkpoint_store or SQLiteCheckpointStore()
        self.policy = policy or MemoizationPolicy()
        self.logger = get_logger("langgraph.orchestrator")
        self.max_steps = max_steps
        self.max_invalid_plan_retries = max_invalid_plan_retries
        self.max_content_validation_retries = max_content_validation_retries
        self.tools: dict[str, Tool] = build_tool_registry(self.memo_store)
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
            '- retrieve_memo: {"key":"<key>", "run_id":"<run_id>", "namespace":"run(optional)"}\n\n'
            "Memoization policy:\n"
            "- For heavy deterministic writes, memoize result before continuing.\n"
            '- Use tool "memoize" with args: key, value, run_id, optional namespace.\n'
            '- To lookup prior values, use "retrieve_memo" with args: key, run_id.\n'
            "Always obey system feedback messages."
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
        missions = self._extract_missions(user_input)
        state["missions"] = missions
        state["mission_reports"] = self._initialize_mission_reports(missions)
        state["active_mission_index"] = -1
        self.logger.info("RUN START run_id=%s missions=%s", state["run_id"], len(missions))
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="init",
            state=state,
        )
        final_state = self._compiled.invoke(state, config={"recursion_limit": self.max_steps})
        final_state = ensure_state_defaults(final_state, system_prompt=self.system_prompt)
        memo_entries = self.memo_store.list_entries(run_id=final_state["run_id"])
        derived_snapshot = self._build_derived_snapshot(final_state, memo_entries)
        self.logger.info("DERIVED SNAPSHOT run_id=%s snapshot=%s", final_state["run_id"], derived_snapshot)
        return {
            "answer": final_state.get("final_answer", ""),
            "tools_used": final_state.get("tool_history", []),
            "mission_report": final_state.get("mission_reports", []),
            "run_id": final_state.get("run_id"),
            "memo_events": final_state.get("memo_events", []),
            "memo_store_entries": memo_entries,
            "derived_snapshot": derived_snapshot,
            "checkpoints": self.checkpoint_store.list_checkpoints(final_state["run_id"]),
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
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            return state
        state["step"] = state.get("step", 0) + 1
        progress_message = self._progress_hint_message(state)
        if progress_message:
            state["messages"].append({"role": "system", "content": progress_message})

        try:
            model_output = self.provider.generate(state["messages"]).strip()
            self.logger.info("MODEL OUTPUT step=%s output=%s", state["step"], model_output[:500])
            state["messages"].append({"role": "assistant", "content": model_output})
            action = self._validate_action(model_output)
            self.logger.info("PLANNED ACTION step=%s action=%s", state["step"], action)
            state["pending_action"] = action
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan",
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
                    "Planner failed with unrecoverable provider error: "
                    f"{error_text}. Stopping."
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

    def _execute_action(self, state: RunState) -> RunState:
        """Execute planned tool action, including duplicate and policy checks."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not action:
            return state

        if action.get("action") == "finish":
            state["final_answer"] = str(action.get("answer", ""))
            self.logger.info("FINISH ACTION step=%s answer=%s", state["step"], state["final_answer"][:300])
            return state

        tool_name = str(action.get("tool_name", ""))
        tool_args = self._normalize_tool_args(tool_name, dict(action.get("args", {})))

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
            state["retry_counts"]["duplicate_tool"] = int(state["retry_counts"]["duplicate_tool"]) + 1
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
        self.logger.info("TOOL RESULT step=%s tool=%s result=%s", state["step"], tool_name, tool_result)
        validation_error = self._validate_tool_result_for_active_mission(
            state=state,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_result=tool_result,
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
        self._record_mission_tool_event(state, tool_name, tool_result)
        progress_hint = self._progress_hint_message(state) or "Continue with the next task or finish when all tasks are complete."
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
            if int(state["retry_counts"].get("content_validation", 0)) > self.max_content_validation_retries:
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
            state["policy_flags"]["memo_required_reason"] = f"heavy deterministic result from {last_tool_name}"
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
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="finalize",
            state=state,
        )
        return state

    def _validate_action(self, model_output: str) -> dict[str, Any]:
        """Validate model output against strict ToolAction/FinishAction schema."""
        data = self._parse_action_json(model_output)
        action = data.get("action")
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
                raise ValueError("action payload must be a JSON object")
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

    def _initialize_mission_reports(self, missions: list[str]) -> list[dict[str, Any]]:
        """Build initial mission report objects before tool execution starts."""
        return [
            {
                "mission_id": index + 1,
                "mission": mission,
                "used_tools": [],
                "tool_results": [],
                "result": "",
            }
            for index, mission in enumerate(missions)
        ]

    def _record_mission_tool_event(self, state: RunState, tool_name: str, tool_result: dict[str, Any]) -> None:
        """Attach tool usage/results to current mission report."""
        reports = state.get("mission_reports", [])
        if not reports:
            reports = self._initialize_mission_reports(["Primary mission"])
            state["mission_reports"] = reports
            state["missions"] = ["Primary mission"]
            state["active_mission_index"] = -1

        helper_tools = {"memoize", "retrieve_memo"}
        completed_tasks = state.get("completed_tasks", [])
        if tool_name in helper_tools:
            index = int(state.get("active_mission_index", -1))
            if index < 0:
                index = min(max(len(completed_tasks) - 1, 0), len(reports) - 1)
        else:
            index = min(len(completed_tasks), len(reports) - 1)

        state["active_mission_index"] = index
        mission = reports[index]
        mission["used_tools"].append(tool_name)
        mission["tool_results"].append({"tool": tool_name, "result": tool_result})
        mission["result"] = str(tool_result)
        if tool_name not in helper_tools and "error" not in tool_result:
            mission_text = str(mission.get("mission", "")).strip()
            if mission_text and mission_text not in completed_tasks:
                completed_tasks.append(mission_text)

    def _next_incomplete_mission(self, state: RunState) -> str:
        """Return the next mission string that has not been marked complete."""
        missions = state.get("missions", [])
        completed_count = len(state.get("completed_tasks", []))
        if completed_count < len(missions):
            return str(missions[completed_count])
        return ""

    def _all_missions_completed(self, state: RunState) -> bool:
        """Whether all extracted missions have been completed."""
        missions = state.get("missions", [])
        if not missions:
            return False
        return len(state.get("completed_tasks", [])) >= len(missions)

    def _progress_hint_message(self, state: RunState) -> str:
        """Create a compact progress hint for the planner."""
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

    def _build_auto_finish_answer(self, state: RunState) -> str:
        """Build deterministic summary when all missions are complete."""
        mission_reports = state.get("mission_reports", [])
        summary_parts = ["All tasks completed."]
        for report in mission_reports:
            mission = str(report.get("mission", "")).strip()
            result = str(report.get("result", "")).strip()
            if mission and result:
                summary_parts.append(f"{mission} -> {result}")
        return " ".join(summary_parts)

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
        return normalized

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
            "memo_policy_retries": state.get("retry_counts", {}).get("memo_policy", 0),
            "content_validation_retries": state.get("retry_counts", {}).get("content_validation", 0),
        }

    def _validate_tool_result_for_active_mission(
        self,
        *,
        state: RunState,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> str | None:
        """Apply deterministic content validation for mission-specific write constraints."""
        if tool_name != "write_file":
            return None
        if "error" in tool_result:
            return None

        mission_text = self._next_incomplete_mission(state).lower()
        if "fibonacci" not in mission_text:
            return None

        content = str(tool_args.get("content", ""))
        numbers = self._parse_csv_int_list(content)
        if numbers is None:
            return "write_file content must be a comma-separated list of integers."
        if len(numbers) != 100:
            return f"fibonacci content must contain exactly 100 integers, got {len(numbers)}."
        if numbers[0] != 0 or numbers[1] != 1:
            return "fibonacci content must start with 0, 1."

        for index in range(2, len(numbers)):
            expected = numbers[index - 1] + numbers[index - 2]
            if numbers[index] != expected:
                return (
                    "fibonacci sequence mismatch at index "
                    f"{index}: got {numbers[index]}, expected {expected}."
                )
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
