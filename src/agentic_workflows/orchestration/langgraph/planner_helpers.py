from __future__ import annotations

"""Planner helper methods for LangGraphOrchestrator.

PlannerHelpersMixin provides:
- System-prompt and JSON-schema build methods
- Pipeline-trace emit helper
- Planner log helpers (_log_queue_mission_spacing, _log_parser_state, etc.)
- Environment config helpers (_env_float, _env_bool)
- Finish-rejection and rerun tracking helpers
- _generate_with_hard_timeout()

These are pure instance-method helpers that do not reference graph topology.
They are factored out of graph.py to keep each file under 600 lines.

Anti-pattern: do NOT import from graph.py or orchestrator.py here — circular.
Import from state_schema, provider, etc. directly.
"""

import os
import queue
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from agentic_workflows.logger import get_logger
from agentic_workflows.orchestration.langgraph.provider import (
    ChatProvider,
    ProviderTimeoutError,
)
from agentic_workflows.orchestration.langgraph.state_schema import RunState, ensure_state_defaults

if TYPE_CHECKING:
    pass


_LOG = get_logger("langgraph.orchestrator")

# Module-level: referenced by _emit_trace (imported from orchestrator constants)
_PIPELINE_TRACE_CAP_REF = 500  # mirrors orchestrator._PIPELINE_TRACE_CAP


class PlannerHelpersMixin:
    """Mixin providing prompt-building and planner-support helpers.

    Intended to be used with LangGraphOrchestrator via multiple inheritance.
    Methods here reference self attributes set in LangGraphOrchestrator.__init__.
    """

    # ------------------------------------------------------------------ #
    # Prompt / schema builders                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_codebase_context(cwd: str) -> str:
        """Return a compact codebase summary injected into the system prompt."""
        root = Path(cwd)
        lines: list[str] = []

        # Architecture section only from AGENTS.md — skip commands/style/git noise
        for candidate in ("AGENTS.md", "README.md"):
            doc = root / candidate
            if doc.exists():
                try:
                    text = doc.read_text(encoding="utf-8")
                    # Extract only lines between ## 2. Architecture and the next ## section
                    arch_lines: list[str] = []
                    in_arch = False
                    for line in text.splitlines():
                        if line.startswith("## 2.") or (not in_arch and "Architecture" in line and line.startswith("#")):
                            in_arch = True
                        elif in_arch and line.startswith("## "):
                            break
                        if in_arch and line.strip():
                            arch_lines.append(line.rstrip())
                    if arch_lines:
                        lines.extend(arch_lines[:12])
                    break
                except OSError:
                    pass

        # Key source dirs only (skip build/doc/config noise)
        src = root / "src"
        if src.is_dir():
            try:
                pkgs = sorted(p.name for p in src.iterdir() if p.is_dir() and not p.name.startswith("_"))[:5]
                if pkgs:
                    lines.append("src/: " + ", ".join(pkgs))
            except OSError:
                pass

        return "\n".join(lines)

    def _build_action_json_schema(self) -> dict:  # type: ignore[return]
        """Generate json_schema response_format from live tool registry.

        Produces an anyOf schema covering every registered tool (with required
        args as string properties) plus finish and clarify actions.
        Cached in self._action_json_schema at __init__ time.
        """
        tool_variants: list[dict] = []
        for name, tool in self.tools.items():  # type: ignore[attr-defined]
            schema = tool.args_schema if hasattr(tool, "args_schema") else {}
            args_props = {aname: {"type": meta.get("type", "string")} for aname, meta in schema.items()}
            req = [aname for aname, meta in schema.items() if meta.get("required") == "true"]
            variant: dict = {
                "type": "object",
                "properties": {
                    "action": {"const": "tool"},
                    "tool_name": {"const": name},
                    "args": {
                        "type": "object",
                        "properties": args_props,
                        **({"required": req} if req else {}),
                    },
                },
                "required": ["action", "tool_name", "args"],
            }
            tool_variants.append(variant)
        tool_variants += [
            {
                "type": "object",
                "properties": {
                    "action": {"const": "finish"},
                    "answer": {"type": "string"},
                },
                "required": ["action", "answer"],
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "clarify"},
                    "question": {"type": "string"},
                },
                "required": ["action", "question"],
            },
        ]
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "agent_action",
                "schema": {"anyOf": tool_variants},
                "strict": False,
            },
        }

    def _build_system_prompt(self) -> str:  # type: ignore[return]
        """Construct strict planner prompt and tool/memo policy contract."""
        from agentic_workflows.orchestration.langgraph import directives  # noqa: PLC0415

        cwd = os.getcwd()
        codebase_context = self._build_codebase_context(cwd)

        # Select prompt tier based on provider context window size
        prompt_tier: Literal["compact", "full"] = getattr(self, "_prompt_tier", "full")

        if prompt_tier == "compact":
            # Compact tier: read ## COMPACT section from supervisor.md
            compact_content = _read_directive_section("supervisor", "COMPACT")
            if compact_content:
                return compact_content

        # Full tier (default)
        agent_root = os.getenv("AGENT_ROOT", cwd)
        agent_workdir = os.getenv("AGENT_WORKDIR", os.getenv("P1_RUN_ARTIFACT_DIR", cwd))

        env_block_parts = [f"CWD: {agent_root}"]
        if agent_workdir != agent_root:
            env_block_parts.append(f"WRITE_DIR: {agent_workdir}")
        env_block_parts.append(f"RUN_ID: {{run_id_placeholder}}")
        env_block = "\n".join(env_block_parts)

        tools_section = directives.SUPERVISOR_DIRECTIVE.get_tools_section(
            self.tools,  # type: ignore[attr-defined]
            prompt_tier=prompt_tier,
        )
        memo_section = directives.SUPERVISOR_DIRECTIVE.get_memo_section()
        examples_section = ""
        if prompt_tier == "full":
            examples_section = _read_directive_section("supervisor", "Examples")
            if examples_section:
                examples_section = f"\n\n## Examples\n{examples_section}"

        parts = [
            env_block,
            "",
            codebase_context,
            "",
            tools_section,
            memo_section,
            examples_section,
        ]
        return "\n".join(p for p in parts if p is not None)

    def _invalidate_known_poisoned_cache_entries(self) -> None:
        """Purge known-bad cached write inputs discovered during run review."""
        poisoned = (
            ("write_file_input:fib50.txt", "9192a11413589198351eed65372ca8ced1b495337040e432d5a0cd806da4d41d"),
            ("write_file_input:pattern_report.txt", "c89dfcb4f7885053f1ae4d9326ffd2cdc95109dcfc10c7c6315cf33e39e1712f"),
        )
        for key, value_hash in poisoned:
            deleted = self.memo_store.delete(  # type: ignore[attr-defined]
                run_id="shared",
                key=key,
                namespace="cache",
                value_hash=value_hash,
            )
            if deleted:
                self.logger.info(  # type: ignore[attr-defined]
                    "CACHE INVALIDATION key=%s value_hash=%s deleted=%s",
                    key,
                    value_hash,
                    deleted,
                )

    # ------------------------------------------------------------------ #
    # Pipeline trace helper                                                #
    # ------------------------------------------------------------------ #

    def _emit_trace(self, state: RunState, stage: str, **fields: Any) -> None:
        """Append a pipeline trace event to policy_flags['pipeline_trace']."""
        from agentic_workflows.orchestration.langgraph.orchestrator import _PIPELINE_TRACE_CAP  # noqa: PLC0415

        policy_flags = state.get("policy_flags")
        if not isinstance(policy_flags, dict):
            return
        trace = policy_flags.setdefault("pipeline_trace", [])
        if isinstance(trace, list):
            trace.append({"stage": stage, "step": state.get("step", 0), **fields})
            if len(trace) > _PIPELINE_TRACE_CAP:
                del trace[: len(trace) - _PIPELINE_TRACE_CAP]

    # ------------------------------------------------------------------ #
    # Planner log helpers                                                  #
    # ------------------------------------------------------------------ #

    def _log_queue_mission_spacing(
        self, *, state: RunState, mission_id: int, source: str
    ) -> None:
        """Emit a visual separator when queued actions move to a different mission."""
        if mission_id <= 0:
            return
        flags = state.get("policy_flags", {})
        previous = int(flags.get("last_queue_mission_id", 0))
        if previous > 0 and previous != mission_id:
            self.logger.info("")  # type: ignore[attr-defined]
            self.logger.info(  # type: ignore[attr-defined]
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
        next_mission = self._next_incomplete_mission(state)  # type: ignore[attr-defined]
        next_preview = next_mission[:120] + "..." if len(next_mission) > 120 else next_mission
        self.logger.info(  # type: ignore[attr-defined]
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
        self.logger.info(  # type: ignore[attr-defined]
            "PLANNER OUTPUT step=%s source=%s queue_remaining=%s action=%s",
            state["step"],
            source,
            queue_remaining,
            self._planner_action_preview(action),
        )

    # ------------------------------------------------------------------ #
    # Route and clarify helpers                                            #
    # ------------------------------------------------------------------ #

    def _route_after_plan(self, state: RunState) -> str:
        """Route graph transitions based on the planner's pending action."""
        state = ensure_state_defaults(state, system_prompt=self.system_prompt)  # type: ignore[attr-defined]
        action = state.get("pending_action")
        if not action:
            return "plan"
        if action.get("action") == "finish":
            return "finish"
        if action.get("action") == "clarify":
            return "clarify"
        return "execute"

    def _clarify_node(self, state: RunState) -> RunState:
        """Handle clarify action: surface the question as the final answer."""
        action = state.get("pending_action") or {}
        question = str(action.get("question", "I need more information to proceed."))
        state["final_answer"] = f"__CLARIFY__: {question}"
        state["pending_action"] = {"action": "finish", "answer": state["final_answer"]}
        self.logger.info("CLARIFY_NODE question=%s", question[:100])  # type: ignore[attr-defined]
        return state

    def _diagnose_incomplete_missions(self, state: RunState) -> str:
        """Produce a specific diagnosis of which missions are incomplete and why."""
        lines = []
        for report in state.get("mission_reports", []):
            if not isinstance(report, dict):
                continue
            if report.get("status") != "completed":
                mid = report.get("mission_id", "?")
                desc = str(report.get("mission", ""))[:80]
                used = report.get("used_tools", [])
                status = report.get("status", "pending")
                lines.append(
                    f"Mission {mid} [{status}]: {desc!r} used_tools={used}"
                )
        if not lines:
            return ""
        return "Incomplete missions: " + "; ".join(lines) + ". "

    # ------------------------------------------------------------------ #
    # Environment config helpers                                           #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Finish-rejection and rerun tracking helpers                          #
    # ------------------------------------------------------------------ #

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
            return True
        for report in state.get("mission_reports", []):
            mid = int(report.get("mission_id", 0))
            if mid in targets and str(report.get("status", "")) == "completed":
                targets.discard(mid)
        return len(targets) == 0

    def _enforce_rerun_completion_guard(self, state: RunState) -> bool:
        """Return True and force-finish if all rerun targets are completed."""
        targets = self._rerun_target_mission_ids(state)
        if not targets:
            return False
        if self._rerun_targets_completed(state):
            diagnosis = self._diagnose_incomplete_missions(state)
            auto_answer = self._build_auto_finish_answer(state)  # type: ignore[attr-defined]
            if diagnosis:
                auto_answer = f"{auto_answer} {diagnosis}"
            self.logger.info(  # type: ignore[attr-defined]
                "RERUN GUARD COMPLETE targets=%s answer=%s", targets, auto_answer[:200]
            )
            state["pending_action"] = {"action": "finish", "answer": auto_answer}
            return True
        return False

    def _purge_queued_finish_actions(self, state: RunState) -> int:
        """Remove finish actions from the pending queue. Returns count removed."""
        queue_before = list(state.get("pending_action_queue", []))
        non_finish = [a for a in queue_before if not (
            isinstance(a, dict) and str(a.get("action", "")).strip().lower() == "finish"
        )]
        removed = len(queue_before) - len(non_finish)
        if removed:
            state["pending_action_queue"] = non_finish
            self.logger.info(  # type: ignore[attr-defined]
                "PURGE QUEUED FINISH removed=%s remaining=%s", removed, len(non_finish)
            )
        return removed

    def _reject_finish_and_recover(
        self,
        *,
        state: RunState,
        rejected_action: dict[str, Any],
        source: str,
    ) -> RunState:
        """Reject a premature finish action and set up recovery hints."""
        rejection_count = int(state["retry_counts"].get("finish_rejected", 0)) + 1
        state["retry_counts"]["finish_rejected"] = rejection_count
        streak = int(state["policy_flags"].get("finish_rejection_streak", 0)) + 1
        state["policy_flags"]["finish_rejection_streak"] = streak

        answer_preview = str(rejected_action.get("answer", ""))[:80]
        fingerprint = f"finish:{answer_preview}"
        last_fingerprint = str(state["policy_flags"].get("last_finish_rejection_fingerprint", ""))

        if fingerprint == last_fingerprint:
            # Identical consecutive rejection — escalate immediately
            streak = self.max_finish_rejections  # type: ignore[attr-defined]
            state["policy_flags"]["finish_rejection_streak"] = streak

        state["policy_flags"]["last_finish_rejection_fingerprint"] = fingerprint

        self.logger.info(  # type: ignore[attr-defined]
            "FINISH REJECTED step=%s source=%s rejection_count=%s streak=%s answer=%s",
            state["step"],
            source,
            rejection_count,
            streak,
            answer_preview,
        )
        self._emit_trace(state, "finish_rejected",
            source=source,
            rejection_count=rejection_count,
            streak=streak,
        )

        if streak >= self.max_finish_rejections:  # type: ignore[attr-defined]
            diagnosis = self._diagnose_incomplete_missions(state)
            fail_message = (
                f"Run forced to stop after {streak} premature finish rejections. "
                f"Incomplete missions remain. {diagnosis}"
            )
            self.logger.warning(  # type: ignore[attr-defined]
                "FINISH REJECTION ESCALATED step=%s streak=%s — forcing stop",
                state["step"],
                streak,
            )
            state["messages"].append({"role": "system", "content": fail_message})
            state["pending_action"] = {"action": "finish", "answer": fail_message}
            self._purge_queued_finish_actions(state)
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name="plan_finish_rejection_escalated",
                state=state,
            )
            return state

        incomplete = self._diagnose_incomplete_missions(state)
        next_mission = self._next_incomplete_mission(state)  # type: ignore[attr-defined]
        hint_parts = [
            "Incomplete missions remain — do not finish yet.",
            incomplete,
            f"Next task: {next_mission}" if next_mission else "",
        ]
        hint = " ".join(p for p in hint_parts if p)
        state["messages"].append(
            {"role": "user", "content": f"[Orchestrator] {hint}"}
        )
        state["pending_action"] = None
        self._purge_queued_finish_actions(state)
        self.checkpoint_store.save(  # type: ignore[attr-defined]
            run_id=state["run_id"],
            step=state["step"],
            node_name="plan_finish_rejected",
            state=state,
        )
        return state

    # ------------------------------------------------------------------ #
    # Provider call with hard timeout                                       #
    # ------------------------------------------------------------------ #

    def _generate_with_hard_timeout(
        self,
        messages: list[dict[str, str]],
        signals: Any,
        provider: ChatProvider | None = None,
    ) -> str:
        """Protect planner generate() call with a hard wall-clock timeout."""
        timeout_seconds = self.plan_call_timeout_seconds  # type: ignore[attr-defined]
        _active_provider = provider if provider is not None else self._router.route_by_signals(signals)  # type: ignore[attr-defined]
        if timeout_seconds <= 0:
            return _active_provider.generate(messages, response_schema=self._action_json_schema)  # type: ignore[attr-defined]

        outbox: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

        def _run() -> None:
            try:
                outbox.put(("ok", _active_provider.generate(messages, response_schema=self._action_json_schema)))  # type: ignore[attr-defined]
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


# ------------------------------------------------------------------ #
# Module-level pure helpers (no class context needed)                 #
# ------------------------------------------------------------------ #

def _select_prompt_tier(context_size: int) -> Literal["compact", "full"]:
    """Select prompt tier based on provider context window size.

    Models with context_size <= 10000 tokens get the compact prompt to avoid
    overflow. All others get the full prompt with detailed tool arg signatures.
    """
    return "compact" if context_size <= 10000 else "full"


def _read_directive_section(directive_name: str, section: str) -> str:
    """Read a named ## section from a directive .md file.

    Returns the section content stripped of leading/trailing whitespace,
    or "" if the file or section doesn't exist.
    """
    path = Path(__file__).resolve().parents[2] / "directives" / f"{directive_name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    in_section = False
    lines: list[str] = []
    marker = f"## {section}"
    for line in text.splitlines():
        if line.strip() == marker:
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            lines.append(line)
    return "\n".join(lines).strip()


def _estimate_prompt_tokens(text: str) -> int:
    """Estimate token count using len//4 heuristic."""
    return len(text) // 4
