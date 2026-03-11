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
        """Construct strict planner prompt and tool/memo policy contract.

        Two tiers:
        - compact: for providers with context_size <= 10000 (e.g. phi4/llama-cpp 8192).
          Contains COMPACT directive from supervisor.md, tool names only (no arg signatures),
          and env block. Avoids context overflow on small-window models.
        - full: existing behavior with detailed tool arg signatures + env block prepended.
        """
        # AGENT_ROOT = readable project root (source/docs); AGENT_WORKDIR = writable output dir
        readable_root = os.environ.get("AGENT_ROOT") or os.environ.get("AGENT_WORKDIR") or os.getcwd()
        writable_root = os.environ.get("AGENT_WORKDIR") or os.getcwd()

        env_block = (
            "<env>\n"
            "python3 is available (not python)\n"
            f"Working dir: {writable_root}\n"
            "</env>\n"
        )

        prompt_tier: Literal["compact", "full"] = getattr(self, "_prompt_tier", "full")  # type: ignore[attr-defined]

        if prompt_tier == "compact":
            # Read only the ## COMPACT section from supervisor.md
            compact_directive = _read_directive_section("supervisor", "COMPACT")
            if not compact_directive:
                compact_directive = "You emit exactly one JSON action per response. Pure JSON only."

            def _tool_sig(name: str, tool: object) -> str:
                schema = tool.args_schema if hasattr(tool, "args_schema") else {}  # type: ignore[union-attr]
                arg_names = list(schema.keys())
                return f"{name}({', '.join(arg_names)})" if arg_names else name

            tool_names_line = ", ".join(_tool_sig(n, t) for n, t in self.tools.items())  # type: ignore[attr-defined]
            return (
                env_block
                + compact_directive + "\n"
                + f"Available tools: {tool_names_line}\n"
            )

        # Full tier: prepend env_block to existing prompt
        tool_list = ", ".join(self.tools.keys())  # type: ignore[attr-defined]
        codebase_ctx = self._build_codebase_context(readable_root)
        workspace_line = (
            f"Project root (read): {readable_root}\nWrite workspace: {writable_root}\n"
            if readable_root != writable_root
            else f"Working directory: {readable_root}\n"
        )
        tool_args_block = (
            "Tool args (each \"operation\" takes exactly ONE value, never comma-separated):\n"
            '- text_analysis: {"text":"...", "operation":"word_count"} (one of: word_count|sentence_count|char_count|key_terms|full_report|complexity_score|paragraph_count|avg_word_length|unique_words)\n'
            '- string_ops: {"text":"...", "operation":"uppercase"} (one of: uppercase|lowercase|reverse|length|trim|replace|split|count_words|startswith|endswith|contains)\n'
            '- data_analysis: {"numbers":[...], "operation":"summary_stats"} (one of: summary_stats|outliers|percentiles|distribution|correlation|normalize|z_scores)\n'
            '- math_stats: {"operation":"add", "a":1, "b":2} or {"operation":"mean", "numbers":[...]}\n'
            '- sort_array: {"items":[...], "order":"asc"}\n'
            '- write_file: {"path":"...", "content":"..."}\n'
            '- read_file: {"path":"..."} — reads entire file; only use for small files\n'
            '- read_file_chunk: {"path":"...", "offset":0, "limit":150} — read large files in 150-line chunks; use next_offset from result to continue\n'
            '- retrieve_tool_result: {"key":"<hash>", "offset":0, "limit":3000} — fetch stored large result; use has_more+offset to page\n'
            '- outline_code: {"path":"..."} — show functions/classes/imports with line numbers; use before reading a large code file\n'
            '- json_parser: {"text":"...", "operation":"parse"} (one of: parse|validate|extract_keys|flatten|get_path|pretty_print|count_elements)\n'
            '- regex_matcher: {"text":"...", "pattern":"...", "operation":"find_all"} (one of: find_all|find_first|split|replace|match|count_matches|extract_groups)\n'
            '- repeat_message: {"message":"..."}\n'
            '- run_bash: {"command":"..."}\n'
            f'- search_files: {{"pattern":"*.py", "path":"{readable_root}"}} — exclude .venv, __pycache__, .git, node_modules paths from results\n'
            "- Other tools: see tool name for usage.\n\n"
        )

        # Build few-shot section (full tier only)
        few_shot_text = _read_directive_section("supervisor", "FEW_SHOT")
        few_shot_block = f"\n\n## Examples\n{few_shot_text}\n" if few_shot_text else ""

        prompt = (
            env_block
            + "You are a deterministic tool-using agent.\n"
            + workspace_line
            + (f"Codebase context:\n{codebase_ctx}\n\n" if codebase_ctx else "")
            + "Return exactly one JSON object per response. No XML, markdown, or prose outside JSON.\n"
            f"Available tools: {tool_list}\n\n"
            "Response schema:\n"
            '{"action":"tool","tool_name":"<name>","args":{...}}\n'
            '{"action":"finish","answer":"<summary>"}\n'
            '{"action":"clarify","question":"<question>"}\n\n'
            + tool_args_block
            + "Rules:\n"
            "- One tool call per response.\n"
            "- Memoization is automatic. Do not emit extra planning subtasks.\n"
            "- Obey system feedback messages. If a tool returns an error, fix the args.\n"
            '- On unrecoverable failure: {"action":"finish","answer":"FAILED: <reason>"}\n'
            "- Never claim success if tool results show errors.\n"
            "Context management rules (critical — violating these causes context overflow):\n"
            "- NEVER call read_file on a code file without checking its size first. Use outline_code to inspect structure, then read_file_chunk for sections you need.\n"
            "- For any file likely over 200 lines, always use read_file_chunk (offset=0, limit=150) and loop using next_offset until has_more is false.\n"
            "- After reading a chunk and writing partial output, continue with the next chunk — do not stop after one chunk.\n"
            "- When a compact pointer appears with [Result truncated], call retrieve_tool_result(key=\"<key>\", offset=0, limit=3000) to fetch the full result. Page using has_more and offset.\n"
            "- Message history is windowed automatically — completed mission summaries are preserved, raw history is evicted. Focus on the current task.\n"
            "Context injections prefixed [Cross-run] show HISTORICAL similar missions from past runs.\n"
            "They are reference examples only — they do NOT mean your current tasks are done.\n"
            "Always execute tools to complete every task in your current mission list.\n"
            + few_shot_block
        )

        # Per-role token budget enforcement
        from agentic_workflows.orchestration.langgraph.orchestrator import (
            _ROLE_TOKEN_BUDGETS,  # noqa: PLC0415
        )
        budget = _ROLE_TOKEN_BUDGETS.get("planner", 1000)
        estimated = _estimate_prompt_tokens(prompt)
        if estimated > budget:
            logger = _LOG

            # Step 1: Truncate tool descriptions to just name + required args
            def _short_tool_desc(name: str, tool: object) -> str:
                schema = tool.args_schema if hasattr(tool, "args_schema") else {}  # type: ignore[union-attr]
                req_args = [k for k, v in schema.items() if v.get("required") == "true"]
                return f"- {name}({', '.join(req_args)})" if req_args else f"- {name}"

            short_tools = "\n".join(
                _short_tool_desc(n, t) for n, t in self.tools.items()  # type: ignore[attr-defined]
            )
            prompt = prompt.replace(tool_args_block, f"Tool args:\n{short_tools}\n\n")
            logger.warning(
                "Prompt exceeded planner budget (%d > %d tokens), truncated tool descriptions",
                estimated,
                budget,
            )
            # Step 2: If still over, drop few-shot
            if few_shot_block and _estimate_prompt_tokens(prompt) > budget:
                prompt = prompt.replace(few_shot_block, "")
                logger.warning("Prompt still over budget, dropped few-shot examples")

        prompt += "/no_think"
        return prompt

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
        from agentic_workflows.orchestration.langgraph.orchestrator import (
            _PIPELINE_TRACE_CAP,  # noqa: PLC0415
        )

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
        finish_rejected = int(state["retry_counts"].get("finish_rejected", 0)) + 1
        state["retry_counts"]["finish_rejected"] = finish_rejected
        requirements = self._next_incomplete_mission_requirements(state)  # type: ignore[attr-defined]
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

        self.logger.warning(  # type: ignore[attr-defined]
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

        next_mission = self._next_incomplete_mission(state)  # type: ignore[attr-defined]
        if finish_rejected > self.max_finish_rejections:  # type: ignore[attr-defined]
            fail_message = (
                "Run stopped: planner repeatedly requested finish while tasks remained "
                f"incomplete (next task: {next_mission or 'unknown'})."
            )
            state["messages"].append({"role": "system", "content": fail_message})
            state["pending_action"] = {"action": "finish", "answer": fail_message}
            self.checkpoint_store.save(  # type: ignore[attr-defined]
                run_id=state["run_id"],
                step=state["step"],
                node_name=f"plan_{source}_finish_fail_closed",
                state=state,
            )
            return state

        fallback_action = self._deterministic_fallback_action(state)  # type: ignore[attr-defined]
        if fallback_action is not None and fallback_action.get("action") != "finish":
            state["messages"].append(
                {
                    "role": "system",
                    "content": (
                        "Finish rejected: missions remain incomplete. "
                        + self._diagnose_incomplete_missions(state)
                        + f" Next task: {next_mission or 'unknown'}. "
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
            self.checkpoint_store.save(  # type: ignore[attr-defined]
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
                    + self._diagnose_incomplete_missions(state)
                    + f" Next task: {next_mission or 'unknown'}"
                ),
            }
        )
        state["pending_action"] = None
        self.checkpoint_store.save(  # type: ignore[attr-defined]
            run_id=state["run_id"],
            step=state["step"],
            node_name=f"plan_{source}_finish_rejected",
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
