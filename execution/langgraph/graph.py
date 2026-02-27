from __future__ import annotations

import json
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
from schemas import FinishAction, ToolAction
from tools.base import Tool

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover
    END = "__end__"
    START = "__start__"
    StateGraph = None


class MemoizationPolicyViolation(RuntimeError):
    pass


class LangGraphOrchestrator:
    def __init__(
        self,
        *,
        provider: ChatProvider | None = None,
        memo_store: SQLiteMemoStore | None = None,
        checkpoint_store: SQLiteCheckpointStore | None = None,
        policy: MemoizationPolicy | None = None,
        max_steps: int = 40,
    ) -> None:
        self.provider = provider or build_provider("openai")
        self.memo_store = memo_store or SQLiteMemoStore()
        self.checkpoint_store = checkpoint_store or SQLiteCheckpointStore()
        self.policy = policy or MemoizationPolicy()
        self.max_steps = max_steps
        self.tools: dict[str, Tool] = build_tool_registry(self.memo_store)
        self.system_prompt = self._build_system_prompt()
        self._compiled = self._compile_graph()

    def _build_system_prompt(self) -> str:
        tool_list = ", ".join(self.tools.keys())
        return (
            "You are a deterministic tool-using agent.\n"
            "Return exactly one JSON object per response.\n"
            f"Allowed tool_name values: {tool_list}\n\n"
            "Schema:\n"
            '{"action":"tool","tool_name":"<tool>","args":{...}}\n'
            '{"action":"finish","answer":"<summary>"}\n\n'
            "Memoization policy:\n"
            "- For heavy deterministic writes, memoize result before continuing.\n"
            '- Use tool "memoize" with args: key, value, run_id, optional namespace.\n'
            '- To lookup prior values, use "retrieve_memo" with args: key, run_id.\n'
            "Always obey system feedback messages."
        )

    def _compile_graph(self):
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
        state = new_run_state(self.system_prompt, user_input, run_id=run_id)
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="init",
            state=state,
        )
        final_state = self._compiled.invoke(state, config={"recursion_limit": self.max_steps})
        final_state = ensure_state_defaults(final_state, system_prompt=self.system_prompt)
        return {
            "answer": final_state.get("final_answer", ""),
            "tools_used": final_state.get("tool_history", []),
            "run_id": final_state.get("run_id"),
            "memo_events": final_state.get("memo_events", []),
            "checkpoints": self.checkpoint_store.list_checkpoints(final_state["run_id"]),
            "state": final_state,
        }

    def _route_after_plan(self, state: RunState) -> str:
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not action:
            return "plan"
        if action.get("action") == "finish":
            return "finish"
        return "execute"

    def _plan_next_action(self, state: RunState) -> RunState:
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        state["step"] = state.get("step", 0) + 1
        try:
            model_output = self.provider.generate(state["messages"]).strip()
            state["messages"].append({"role": "assistant", "content": model_output})
            action = self._validate_action(model_output)
            state["pending_action"] = action
            self.checkpoint_store.save(
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan",
                state=state,
            )
            return state
        except Exception as exc:
            invalid_count = int(state["retry_counts"].get("invalid_json", 0)) + 1
            state["retry_counts"]["invalid_json"] = invalid_count
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Invalid action ({str(exc)}). Return exactly one valid JSON object. "
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
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        action = state.get("pending_action")
        if not action:
            return state

        if action.get("action") == "finish":
            state["final_answer"] = str(action.get("answer", ""))
            return state

        tool_name = str(action.get("tool_name", ""))
        tool_args = dict(action.get("args", {}))

        if state["policy_flags"].get("memo_required") and tool_name != "memoize":
            retry_count = int(state["retry_counts"].get("memo_policy", 0)) + 1
            state["retry_counts"]["memo_policy"] = retry_count
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
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        f"Duplicate tool call detected for '{tool_name}' with the same arguments. "
                        "Do not repeat completed calls. Move to the next task or finish if done."
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

        tool_result = self.tools[tool_name].execute(tool_args)
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
        state["messages"].append(
            {
                "role": "system",
                "content": (
                    f"TOOL_RESULT #{call_number} ({tool_name}): {json.dumps(tool_result)}\n"
                    "Continue with the next task or finish when all tasks are complete."
                ),
            }
        )

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
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="policy",
            state=state,
        )
        return state

    def _finalize(self, state: RunState) -> RunState:
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)
        pending_action = state.get("pending_action") or {}
        if pending_action.get("action") == "finish":
            state["final_answer"] = str(pending_action.get("answer", "")).strip()
            state["pending_action"] = None
        if not state.get("final_answer"):
            state["final_answer"] = "Run completed."
        self.checkpoint_store.save(
            run_id=state["run_id"],
            step=state["step"],
            node_name="finalize",
            state=state,
        )
        return state

    def _validate_action(self, model_output: str) -> dict[str, Any]:
        try:
            data = json.loads(model_output)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json: {str(exc)}") from exc

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
