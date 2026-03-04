from __future__ import annotations

"""Persistent conversational session entrypoint for LangGraph orchestration.

Usage:
    python -m agentic_workflows.orchestration.langgraph.user_run

The session maintains rolling conversation history across runs, compresses
context after each run, and resets fully when the agent calls clear_context.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

# Allow running directly or via -m
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[4]
    src_root = repo_root / "src"
    for p in (str(repo_root), str(src_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph.langgraph_orchestrator import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.run_ui import (
    collect_retry_counts,
    render_clarification_panel,
    render_context_warning_panel,
    render_mission_status_panel,
    render_specialist_routing,
    render_stuck_indicator,
)
from agentic_workflows.orchestration.langgraph.state_schema import AgentMessage, RunResult

_LOG = get_logger("langgraph.user_run")
_MAX_TOOL_HISTORY_RETAINED = 20
_CLARIFY_PREFIX = "__CLARIFY__:"


@dataclass
class UserSession:
    """Stateful conversational session around LangGraphOrchestrator."""

    max_steps: int = 80
    token_budget: int = 200_000
    _orchestrator: LangGraphOrchestrator | None = field(default=None, init=False)
    _conversation_history: list[AgentMessage] = field(default_factory=list, init=False)
    _completed_summaries: list[dict[str, Any]] = field(default_factory=list, init=False)
    _last_run_failures: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._orchestrator = LangGraphOrchestrator(
            max_steps=self.max_steps,
            on_specialist_route=self._on_route,
        )

    def _on_route(self, *, specialist: str, tool: str, mission_id: int) -> None:
        """Live display callback — called by graph during each tool routing."""
        render_specialist_routing(
            specialist=specialist,
            tool=tool,
            mission_id=mission_id,
            status="executing",
        )

    def _format_user_input(self, text: str) -> str:
        """Pass user text to the orchestrator unchanged.

        The mission_parser handles free-form text naturally.  JSON contract
        enforcement is handled by the system prompt directives; embedding
        JSON schema templates in the user message confuses JSON-mode models.

        When ``P1_USER_INPUT_MAX_LENGTH`` is set to a positive integer, the
        input is silently truncated to that many characters.
        """
        max_len = int(os.getenv("P1_USER_INPUT_MAX_LENGTH", "0") or "0")
        if max_len > 0 and len(text) > max_len:
            text = text[:max_len]
        return text

    def _minimize_context(self, *, full_clear: bool = False) -> None:
        """Compress accumulated context to keep token usage manageable."""
        if full_clear:
            self._conversation_history = []
        # Keep only the most recent tool history entries (already in summaries)
        # _completed_summaries persist across clears for reference
        # Trim conversation history to a sliding window
        if len(self._conversation_history) > _MAX_TOOL_HISTORY_RETAINED:
            self._conversation_history = self._conversation_history[-_MAX_TOOL_HISTORY_RETAINED:]

    def _build_prior_context(self) -> list[AgentMessage] | None:
        """Build a compact prior-context block to inject into the next run.

        Returns None when there is no prior history (first turn). When history
        exists, returns a list of AgentMessage dicts:
          - A single system message summarising completed missions so far.
          - The last assistant answer (so the planner can refer to it directly).

        Kept deliberately small to avoid inflating prompt tokens. Only the
        most recent answer and a short mission summary are forwarded.
        """
        has_summaries = bool(self._completed_summaries)
        has_history = bool(self._conversation_history)
        if not has_summaries and not has_history:
            return None

        messages: list[AgentMessage] = []

        if has_summaries:
            # Build a short summary of completed missions (capped at last 5).
            recent = self._completed_summaries[-5:]
            summary_lines = [
                "Format: JSON only. Schema: tool|finish|clarify.",
                "Prior completed missions (most recent first):",
            ]
            if self._last_run_failures:
                failure_str = "; ".join(self._last_run_failures[:5])
                summary_lines.append(f"[Prior run failed] Last tool errors: {failure_str}")
            for entry in reversed(recent):
                mid = entry.get("mission_id", "?")
                status = entry.get("status", "unknown")
                result_snippet = str(entry.get("result", ""))[:120]
                tools = ", ".join(entry.get("used_tools", [])) or "none"
                summary_lines.append(
                    f"  Mission {mid} [{status}] tools=[{tools}] result={result_snippet!r}"
                )
            messages.append(
                AgentMessage(role="system", content="\n".join(summary_lines))
            )

        if has_history:
            # Include last user request and last assistant reply so the planner has
            # enough context to handle follow-ups like "re try" or "do the same again".
            last_user = next(
                (m for m in reversed(self._conversation_history) if m.get("role") == "user"),
                None,
            )
            last_assistant = next(
                (m for m in reversed(self._conversation_history) if m.get("role") == "assistant"),
                None,
            )
            if last_user is not None:
                messages.append(last_user)
            if last_assistant is not None:
                messages.append(last_assistant)

        return messages if messages else None

    def _collect_summary(self, result: dict[str, Any]) -> None:
        """Move completed mission data into _completed_summaries (drop verbose tool_results)."""
        mission_reports_raw = result.get("mission_report", [])
        mission_reports = mission_reports_raw if isinstance(mission_reports_raw, list) else []
        for report in mission_reports:
            if not isinstance(report, dict):
                continue
            summary = {
                "mission_id": report.get("mission_id"),
                "mission": report.get("mission", "")[:120],
                "used_tools": report.get("used_tools", []),
                "status": report.get("status", ""),
                "result": str(report.get("result", ""))[:200],
            }
            self._completed_summaries.append(summary)

    @staticmethod
    def _validate_result(result: dict[str, Any]) -> RunResult:
        """Return result with guaranteed keys; coerce bad types to safe defaults."""
        validated: dict[str, Any] = {
            "answer": "",
            "tools_used": [],
            "mission_report": [],
            "run_id": None,
            "state": {},
        }
        validated.update(result)
        if not isinstance(validated["tools_used"], list):
            validated["tools_used"] = []
        if not isinstance(validated["mission_report"], list):
            validated["mission_report"] = []
        if not isinstance(validated["state"], dict):
            validated["state"] = {}
        return cast(RunResult, validated)

    def run_once(
        self,
        user_input: str,
        _original_input: str | None = None,
        *,
        clarify_depth: int = 0,
    ) -> RunResult:
        """Execute one mission string and update session state."""
        assert self._orchestrator is not None  # set by __post_init__
        prior_context = self._build_prior_context()
        formatted_input = self._format_user_input(user_input)
        # Store formatted input in history so prior_context on next turn is consistent.
        self._conversation_history.append(AgentMessage(role="user", content=formatted_input))
        try:
            result = self._orchestrator.run(formatted_input, prior_context=prior_context)
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("Orchestrator execution failed")
            error_msg = f"Orchestrator error: {exc}"
            self._conversation_history.append(AgentMessage(role="assistant", content=error_msg))
            return cast(RunResult, {"answer": error_msg, "tools_used": [], "mission_report": [], "run_id": None, "state": {}})
        result = self._validate_result(result)

        # Append the agent's answer to rolling history
        answer = str(result.get("answer", ""))
        if answer:
            self._conversation_history.append(
                AgentMessage(role="assistant", content=answer)
            )

        # Collect per-mission summaries before minimizing
        self._collect_summary(result)

        # Check if clear_context tool was fired
        state_raw = result.get("state", {})
        state = state_raw if isinstance(state_raw, dict) else {}

        # Extract failed tool calls for next-turn prior context (Bug 7)
        self._last_run_failures = []
        tool_history = state.get("tool_history", [])
        if isinstance(tool_history, list):
            for entry in tool_history:
                if not isinstance(entry, dict):
                    continue
                res = entry.get("result")
                if isinstance(res, dict) and res.get("returncode", 0) != 0:
                    tool_name = entry.get("tool", "unknown")
                    stderr = str(res.get("stderr", ""))[:120]
                    self._last_run_failures.append(f"{tool_name} → {stderr or 'returncode!=0'}")
        context_clear = bool(state.get("context_clear_requested", False))

        self._minimize_context(full_clear=context_clear)

        # Show mission status panel
        mission_reports_raw = result.get("mission_report", [])
        mission_reports = mission_reports_raw if isinstance(mission_reports_raw, list) else []
        if mission_reports:
            print()
            print(render_mission_status_panel(mission_reports))

        # Context clear panel
        if context_clear:
            budget_used = int(state.get("token_budget_used", 0))
            budget_total = int(state.get("token_budget", self.token_budget))
            print(render_context_warning_panel("full", budget_used, budget_total))

        # Stuck-loop indicator
        retry_counts = collect_retry_counts(result)
        if retry_counts.get("finish_rejected", 0) >= 2:
            print(render_stuck_indicator(retry_counts["finish_rejected"], 6))

        # Clarify: re-prompt the user (with recursion depth guard)
        if answer.startswith(_CLARIFY_PREFIX):
            if clarify_depth > 2:
                raise RuntimeError(
                    f"Clarification loop depth exceeded (depth={clarify_depth}). "
                    "The agent repeatedly requested clarification without resolving. "
                    "Aborting to prevent infinite recursion."
                )
            question = answer[len(_CLARIFY_PREFIX):].strip()
            # Replace the __CLARIFY__: signal in history with the clean question so
            # prior_context on the next run is readable by the planner.
            if self._conversation_history and self._conversation_history[-1].get("content") == answer:
                self._conversation_history[-1] = AgentMessage(role="assistant", content=question)
            missing_raw = state.get("pending_action", {}) or {}
            missing = missing_raw.get("missing", []) if isinstance(missing_raw, dict) else []
            print()
            print(render_clarification_panel(question, missing if isinstance(missing, list) else []))
            try:
                clarification = input("Your answer: ").strip()
            except (EOFError, KeyboardInterrupt):
                return result
            original = _original_input if _original_input is not None else user_input
            return self.run_once(
                original + "\nUser clarification: " + clarification,
                _original_input=original,
                clarify_depth=clarify_depth + 1,
            )

        return result

    def run_loop(self) -> None:
        """Main conversation loop — reads from stdin, runs missions, prints answers."""
        _SEP = "=" * 60
        print(_SEP)
        print("  LangGraph Agent Session")
        print(_SEP)
        print("  Commands: quit/q  exit   clear  reset context")
        print(f"  Token budget: {self.token_budget // 1000}k")
        print(_SEP)
        print()
        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nSession ended.")
                break
            if not user_input:
                continue
            if user_input.lower() in {"quit", "exit", "q"}:
                print("Session ended.")
                break
            if user_input.lower() == "clear":
                self._minimize_context(full_clear=True)
                print("Context cleared.")
                continue
            print()
            result = self.run_once(user_input)
            answer = result.get("answer", "")
            print(f"\nAgent: {answer}")
            print()


if __name__ == "__main__":
    session = UserSession()
    session.run_loop()
