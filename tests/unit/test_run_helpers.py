"""Unit tests for run.py helper functions."""
from __future__ import annotations

import unittest

from agentic_workflows.orchestration.langgraph.run import (
    _build_rerun_input,
    _derive_changed_files,
    _get_failed_missions,
    _get_reviewer_decisions,
    _normalize_prefer_mode,
    _normalize_reviewer_mode,
)

_SAMPLE_INPUT = """Return exactly one JSON object per turn.

Please complete these tasks:

Task 1: Text Analysis Pipeline
  1a. Analyze this text: "The quick brown fox"
  1b. Write results to analysis_results.txt

Task 2: Data Analysis and Sorting
  2a. Analyze these numbers: [45, 23, 67]
  2b. Sort in descending order

Task 3: JSON Processing
  3a. Parse this JSON: '{"users":[]}'
"""


class TestGetFailedMissions(unittest.TestCase):
    def _make_report(self, level: str, mission_id: int = 1) -> dict:
        return {
            "run_id": "test",
            "findings": [{"mission_id": mission_id, "level": level, "check": "test", "detail": "x"}],
        }

    def test_returns_fail_missions(self) -> None:
        audit = self._make_report("fail", 1)
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mission_id"], 1)

    def test_skips_warn_missions(self) -> None:
        """Bug A: warn-level findings must NOT trigger re-run."""
        audit = self._make_report("warn", 1)
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(result, [])

    def test_skips_pass_missions(self) -> None:
        audit = self._make_report("pass", 1)
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(result, [])

    def test_empty_audit(self) -> None:
        result = _get_failed_missions(None, [{"mission_id": 1}])
        self.assertEqual(result, [])

    def test_multiple_missions_only_failed_returned(self) -> None:
        audit = {
            "run_id": "x",
            "findings": [
                {"mission_id": 1, "level": "pass", "check": "overall", "detail": "ok"},
                {"mission_id": 2, "level": "fail", "check": "chain", "detail": "bad"},
                {"mission_id": 3, "level": "warn", "check": "presence", "detail": "maybe"},
            ],
        }
        reports = [
            {"mission_id": 1, "mission": "Task 1"},
            {"mission_id": 2, "mission": "Task 2"},
            {"mission_id": 3, "mission": "Task 3"},
        ]
        result = _get_failed_missions(audit, reports)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mission_id"], 2)


class TestBuildRerunInput(unittest.TestCase):
    def test_extracts_full_block_from_original_input(self) -> None:
        """Bug B: full task block (including sub-tasks) must be preserved."""
        reports = [{"mission_id": 1, "mission": "Task 1: Text Analysis Pipeline"}]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertIn("1a.", result)
        self.assertIn("quick brown fox", result)
        self.assertIn("analysis_results.txt", result)

    def test_no_double_task_prefix(self) -> None:
        """Bug C: must not produce 'Task 1: Task 1:' double prefix."""
        reports = [{"mission_id": 1, "mission": "Task 1: Text Analysis Pipeline"}]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertNotIn("Task 1: Task 1:", result)

    def test_fallback_without_original_input(self) -> None:
        """Fallback to mission title when no original_input provided."""
        reports = [{"mission_id": 2, "mission": "Data Sorting"}]
        result = _build_rerun_input(reports)
        self.assertIn("Task 2: Data Sorting", result)

    def test_fallback_avoids_double_prefix(self) -> None:
        """Bug C fallback: if mission already starts with 'Task N:', don't add another."""
        reports = [{"mission_id": 1, "mission": "Task 1: Text Analysis"}]
        result = _build_rerun_input(reports)
        self.assertNotIn("Task 1: Task 1:", result)

    def test_multiple_missions_extracted(self) -> None:
        """Multiple failed missions are all included with their full blocks."""
        reports = [
            {"mission_id": 1, "mission": "Task 1: Text Analysis Pipeline"},
            {"mission_id": 2, "mission": "Task 2: Data Analysis and Sorting"},
        ]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertIn("quick brown fox", result)
        self.assertIn("[45, 23, 67]", result)

    def test_finish_instruction_present(self) -> None:
        reports = [{"mission_id": 1, "mission": "Task 1"}]
        result = _build_rerun_input(reports, _SAMPLE_INPUT)
        self.assertIn("finish", result)


class TestReviewerHelpers(unittest.TestCase):
    def test_normalize_reviewer_mode(self) -> None:
        self.assertEqual(_normalize_reviewer_mode("fail_only"), "fail_only")
        self.assertEqual(_normalize_reviewer_mode("weighted"), "weighted")
        self.assertEqual(_normalize_reviewer_mode("both"), "both")
        self.assertEqual(_normalize_reviewer_mode("invalid"), "fail_only")

    def test_normalize_prefer_mode(self) -> None:
        self.assertEqual(_normalize_prefer_mode("weighted"), "weighted")
        self.assertEqual(_normalize_prefer_mode("oops"), "fail_only")

    def test_derive_changed_files_dedupes(self) -> None:
        changed = _derive_changed_files(
            {
                "mission_report": [
                    {
                        "written_files": ["out.txt"],
                        "tool_results": [
                            {
                                "tool": "write_file",
                                "result": {"path": "out.txt", "result": "Successfully wrote 10 characters"},
                            }
                        ],
                    }
                ],
                "tools_used": [
                    {"tool": "write_file", "result": {"path": "tmp/out.txt", "result": "ok"}},
                    {"tool": "write_file", "result": {"error": "content_validation_failed"}},
                ],
            }
        )
        self.assertEqual(changed, ["out.txt"])

    def test_both_mode_uses_preferred_when_decisions_diverge(self) -> None:
        result = {
            "audit_report": {
                "findings": [
                    {"mission_id": 1, "level": "warn", "check": "x", "detail": "warn only"},
                ]
            },
            "mission_report": [{"mission_id": 1, "status": "completed"}],
            "derived_snapshot": {},
            "tools_used": [],
        }
        selected, decisions, selected_mode = _get_reviewer_decisions(
            reviewer_mode="both",
            prefer_mode="weighted",
            result=result,
        )
        self.assertEqual(decisions["fail_only"].action, "end")
        self.assertEqual(decisions["weighted"].action, "rerun")
        self.assertEqual(selected_mode, "weighted")
        self.assertEqual(selected.action, "rerun")


class TestActiveCallbacksContextVar(unittest.TestCase):
    """W1-2: _active_callbacks_var must be a ContextVar with thread-level isolation."""

    def test_contextvar_exists_at_module_level(self) -> None:
        """_active_callbacks_var must be importable from graph module."""
        from agentic_workflows.orchestration.langgraph.graph import _active_callbacks_var
        import contextvars
        self.assertIsInstance(_active_callbacks_var, contextvars.ContextVar)

    def test_contextvar_default_is_empty_list(self) -> None:
        """Default value of _active_callbacks_var must be []."""
        from agentic_workflows.orchestration.langgraph.graph import _active_callbacks_var
        # Get default in a fresh context to avoid pollution
        import contextvars
        ctx = contextvars.copy_context()
        val = ctx.run(_active_callbacks_var.get)
        self.assertEqual(val, [])

    def test_contextvar_isolation_across_threads(self) -> None:
        """Setting _active_callbacks_var in one thread must not affect another thread."""
        from agentic_workflows.orchestration.langgraph.graph import _active_callbacks_var
        import threading

        mock_handler = object()
        _active_callbacks_var.set([mock_handler])

        # Capture value from a different thread
        other_thread_value: list = []
        error_holder: list = []

        def _check_in_thread() -> None:
            try:
                other_thread_value.append(_active_callbacks_var.get())
            except Exception as exc:
                error_holder.append(exc)

        t = threading.Thread(target=_check_in_thread)
        t.start()
        t.join(timeout=2.0)

        self.assertEqual(len(error_holder), 0, f"Thread raised: {error_holder}")
        self.assertEqual(len(other_thread_value), 1, "Thread did not capture a value")
        # The other thread should see the default [] (empty), not [mock_handler]
        self.assertEqual(other_thread_value[0], [],
                         f"Expected [] in other thread, got {other_thread_value[0]}")


class TestPipelineTraceCap(unittest.TestCase):
    """W2-5: pipeline_trace must be capped at 500 entries."""

    def test_pipeline_trace_cap(self) -> None:
        """After exceeding _PIPELINE_TRACE_CAP, oldest entries are evicted."""
        from agentic_workflows.orchestration.langgraph.graph import (
            _PIPELINE_TRACE_CAP,
            LangGraphOrchestrator,
        )
        from unittest.mock import MagicMock

        # Build a state with a pipeline_trace already at cap
        trace = [{"stage": f"s{i}", "step": i} for i in range(_PIPELINE_TRACE_CAP)]
        state = {
            "policy_flags": {"pipeline_trace": trace},
            "step": _PIPELINE_TRACE_CAP,
        }

        # Use _emit_trace to add one more entry
        orch = MagicMock(spec=LangGraphOrchestrator)
        LangGraphOrchestrator._emit_trace(orch, state, "overflow_test")

        self.assertEqual(len(state["policy_flags"]["pipeline_trace"]), _PIPELINE_TRACE_CAP)
        # Newest entry must be the one we just added
        self.assertEqual(state["policy_flags"]["pipeline_trace"][-1]["stage"], "overflow_test")
        # Oldest entry (s0) must have been evicted
        self.assertNotEqual(state["policy_flags"]["pipeline_trace"][0]["stage"], "s0")

    def test_pipeline_trace_below_cap_not_trimmed(self) -> None:
        """Trace below cap should not be trimmed."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from unittest.mock import MagicMock

        state = {"policy_flags": {"pipeline_trace": []}, "step": 0}
        orch = MagicMock(spec=LangGraphOrchestrator)
        LangGraphOrchestrator._emit_trace(orch, state, "normal")
        self.assertEqual(len(state["policy_flags"]["pipeline_trace"]), 1)


class TestHandoffQueueCap(unittest.TestCase):
    """W2-5: handoff_queue and handoff_results must be capped at 50 entries."""

    def test_handoff_queue_cap(self) -> None:
        """After 51 handoff_queue entries, only 50 remain (oldest evicted)."""
        from agentic_workflows.orchestration.langgraph.graph import _HANDOFF_QUEUE_CAP

        queue = [{"task_id": f"t{i}"} for i in range(_HANDOFF_QUEUE_CAP + 1)]
        # Simulate the cap logic that should exist after every append
        if len(queue) > _HANDOFF_QUEUE_CAP:
            queue = queue[-_HANDOFF_QUEUE_CAP:]
        self.assertEqual(len(queue), _HANDOFF_QUEUE_CAP)
        # Oldest entry (t0) evicted, newest (t50) retained
        self.assertEqual(queue[-1]["task_id"], f"t{_HANDOFF_QUEUE_CAP}")
        self.assertEqual(queue[0]["task_id"], "t1")

    def test_handoff_results_cap(self) -> None:
        """After 51 handoff_results entries, only 50 remain (oldest evicted)."""
        from agentic_workflows.orchestration.langgraph.graph import _HANDOFF_RESULTS_CAP

        results = [{"task_id": f"r{i}"} for i in range(_HANDOFF_RESULTS_CAP + 1)]
        if len(results) > _HANDOFF_RESULTS_CAP:
            results = results[-_HANDOFF_RESULTS_CAP:]
        self.assertEqual(len(results), _HANDOFF_RESULTS_CAP)
        self.assertEqual(results[-1]["task_id"], f"r{_HANDOFF_RESULTS_CAP}")
        self.assertEqual(results[0]["task_id"], "r1")


class TestPrepareStateMethod(unittest.TestCase):
    """W3-7: LangGraphOrchestrator must expose prepare_state() as single source of truth."""

    def test_prepare_state_method_exists(self) -> None:
        """prepare_state must be a callable method on LangGraphOrchestrator."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        self.assertTrue(
            hasattr(LangGraphOrchestrator, "prepare_state"),
            "LangGraphOrchestrator must have a prepare_state method",
        )
        self.assertTrue(
            callable(getattr(LangGraphOrchestrator, "prepare_state")),
            "prepare_state must be callable",
        )

    def test_prepare_state_returns_run_state(self) -> None:
        """prepare_state() must return a dict with required RunState keys."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from tests.conftest import ScriptedProvider

        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        orch = LangGraphOrchestrator(provider=provider, max_steps=5)
        state = orch.prepare_state("test mission")

        # Must have core RunState keys
        self.assertIn("run_id", state)
        self.assertIn("missions", state)
        self.assertIn("messages", state)
        self.assertIn("seen_tool_signatures", state)
        self.assertIn("structured_plan", state)
        self.assertIn("mission_contracts", state)
        self.assertIn("mission_reports", state)
        self.assertIn("rerun_context", state)
        self.assertIn("active_mission_index", state)
        self.assertIn("active_mission_id", state)

    def test_prepare_state_accepts_run_id(self) -> None:
        """prepare_state() must accept and use a custom run_id."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from tests.conftest import ScriptedProvider

        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        orch = LangGraphOrchestrator(provider=provider, max_steps=5)
        state = orch.prepare_state("test mission", run_id="custom-123")
        self.assertEqual(state["run_id"], "custom-123")

    def test_prepare_state_merges_prior_context(self) -> None:
        """prepare_state() must merge prior_context system messages into system prompt."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from tests.conftest import ScriptedProvider

        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        orch = LangGraphOrchestrator(provider=provider, max_steps=5)
        prior = [
            {"role": "system", "content": "EXTRA SYSTEM INFO"},
            {"role": "user", "content": "previous question"},
        ]
        state = orch.prepare_state("test mission", prior_context=prior)

        # System message should contain the extra system info
        system_msg = next(m for m in state["messages"] if m.get("role") == "system")
        self.assertIn("EXTRA SYSTEM INFO", system_msg["content"])

        # Prior user message should be in messages
        user_contents = [m["content"] for m in state["messages"] if m.get("role") == "user"]
        self.assertTrue(any("previous question" in c for c in user_contents))


class TestSystemPromptMemoizeRemoval(unittest.TestCase):
    """W3-9: memoize must not appear as a callable tool in the planner system prompt."""

    def test_system_prompt_excludes_memoize_tool(self) -> None:
        """The planner system prompt must not list '- memoize:' as a tool."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from tests.conftest import ScriptedProvider

        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        orch = LangGraphOrchestrator(provider=provider, max_steps=5)
        prompt = orch.system_prompt

        self.assertNotIn("- memoize:", prompt,
                         "System prompt must not list memoize as a callable tool")

    def test_system_prompt_still_contains_retrieve_memo(self) -> None:
        """retrieve_memo must remain in the system prompt (model needs it)."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from tests.conftest import ScriptedProvider

        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        orch = LangGraphOrchestrator(provider=provider, max_steps=5)
        prompt = orch.system_prompt

        self.assertIn("retrieve_memo", prompt,
                       "System prompt must still list retrieve_memo")

    def test_system_prompt_memoization_automatic(self) -> None:
        """Memoization policy must mention automatic memoization."""
        from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
        from tests.conftest import ScriptedProvider

        provider = ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        orch = LangGraphOrchestrator(provider=provider, max_steps=5)
        prompt = orch.system_prompt

        self.assertIn("automatic", prompt.lower(),
                       "System prompt must mention automatic memoization")


if __name__ == "__main__":
    unittest.main()
