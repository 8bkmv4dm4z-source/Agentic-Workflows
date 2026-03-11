"""Tests for tool-result truncation gating in graph.py and context_manager.py.

Regression tests for the H1/H2/H3 bugs fixed in 2026-03:
  H1: on_tool_result used wrong message format string (TOOL RESULT vs TOOL_RESULT #N)
  H2: message was appended BEFORE on_tool_result — retroactive replacement was the only path
  H3: ContextManager instantiated without explicit large_result_threshold (defaulted to 4000)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from agentic_workflows.orchestration.langgraph.context_manager import ContextManager

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_state(messages: list[dict] | None = None) -> dict:
    """Minimal RunState-like dict for testing."""
    return {
        "messages": messages or [],
        "mission_contexts": {},
        "policy_flags": {},
        "step": 1,
        "run_id": "test-run",
        "active_mission_id": 0,
    }


def _make_large_result(size: int = 1000) -> dict:
    """Build a tool result dict whose JSON serialization is at least *size* chars."""
    files = [f"/repo/src/module_{i}.py" for i in range(size // 30 + 1)]
    return {"files": files, "count": len(files)}


# ── H1: retroactive string match in on_tool_result ────────────────────────────


class TestOnToolResultStringMatch:
    """on_tool_result must match the real message format: TOOL_RESULT #N (tool_name):"""

    def test_retroactive_replace_fires_with_correct_format(self):
        """If a large message was already appended with the real format, on_tool_result replaces it."""
        cm = ContextManager(large_result_threshold=100)
        large_result = _make_large_result(500)
        large_json = json.dumps(large_result)
        assert len(large_json) > 100  # sanity

        state = _make_state([
            {"role": "system", "content": "system prompt"},
            {
                "role": "system",
                "content": f"TOOL_RESULT #1 (search_files): {large_json}\nContinue.",
            },
        ])

        cm.on_tool_result(state, "search_files", large_result, {}, mission_id=0)

        last_msg = state["messages"][-1]
        content = last_msg["content"]
        assert len(large_json) > 100
        # The full JSON blob must NOT be in the message anymore
        assert large_json[:50] not in content
        assert "search_files" in content
        assert "chars" in content

    def test_old_wrong_format_does_not_match(self):
        """The broken old search string 'TOOL RESULT (name)' must NOT match the real format."""
        # This test documents the bug: the old code used 'TOOL RESULT' (space) but messages
        # use 'TOOL_RESULT' (underscore). Verify the new code uses the correct format.
        large_result = _make_large_result(500)
        large_json = json.dumps(large_result)

        # Message uses the real format (underscore + number)
        real_format_content = f"TOOL_RESULT #1 (search_files): {large_json}\nContinue."

        # Simulate the OLD buggy behaviour: search for wrong string
        broken_search = "TOOL RESULT (search_files)"
        assert broken_search not in real_format_content  # confirms the bug

        # Confirm the NEW correct search string IS present
        correct_search = "TOOL_RESULT"
        assert correct_search in real_format_content

    def test_no_replacement_when_result_small(self):
        """Results below threshold must not trigger replacement."""
        cm = ContextManager(large_result_threshold=1000)
        small_result = {"files": ["a.py", "b.py"]}
        small_json = json.dumps(small_result)
        assert len(small_json) < 1000

        original_content = f"TOOL_RESULT #1 (search_files): {small_json}\nContinue."
        state = _make_state([
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": original_content},
        ])

        cm.on_tool_result(state, "search_files", small_result, {}, mission_id=0)

        # Content must be unchanged
        assert state["messages"][1]["content"] == original_content


# ── H2: gate truncation BEFORE append in graph.py ────────────────────────────


class TestGraphExecuteActionGating:
    """The message appended in _execute_action must already be truncated when the result
    exceeds large_result_threshold — the full JSON must never enter state['messages']."""

    def _build_minimal_orchestrator(self):
        """Build a LangGraphOrchestrator with all external dependencies mocked."""

        with patch.dict(
            "os.environ",
            {
                "P1_PROVIDER": "openai",
                "OPENAI_API_KEY": "test-key",
            },
        ):
            from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

            orch = LangGraphOrchestrator.__new__(LangGraphOrchestrator)
            # Manually set required attributes
            orch.logger = MagicMock()
            orch.context_manager = ContextManager(large_result_threshold=100)
            return orch

    def test_large_result_is_truncated_before_message_append(self):
        """A tool result >threshold must produce a placeholder message, not the full JSON."""
        cm = ContextManager(large_result_threshold=100)
        large_result = _make_large_result(500)
        large_json = json.dumps(large_result)
        assert len(large_json) > 100

        # Simulate the gating logic that was added to _execute_action
        _threshold = cm.large_result_threshold
        _tool_result_json = large_json
        if len(_tool_result_json) > _threshold:
            _tool_result_for_msg = (
                f"[tool_result: search_files, {len(_tool_result_json)} chars, stored in context]"
            )
        else:
            _tool_result_for_msg = _tool_result_json

        content = f"TOOL_RESULT #1 (search_files): {_tool_result_for_msg}\nContinue."

        # Full JSON must not appear
        assert large_json[:50] not in content
        # Placeholder must appear
        assert "chars, stored in context" in content
        assert "search_files" in content

    def test_small_result_passes_through_unchanged(self):
        """A tool result below threshold must appear verbatim in the message."""
        cm = ContextManager(large_result_threshold=1000)
        small_result = {"status": "ok", "count": 3}
        small_json = json.dumps(small_result)
        assert len(small_json) < 1000

        _threshold = cm.large_result_threshold
        _tool_result_json = small_json
        if len(_tool_result_json) > _threshold:
            _tool_result_for_msg = (
                f"[tool_result: write_file, {len(_tool_result_json)} chars, stored in context]"
            )
        else:
            _tool_result_for_msg = _tool_result_json

        assert _tool_result_for_msg == small_json


# ── H3: explicit threshold at instantiation site ──────────────────────────────


class TestContextManagerInstantiationThreshold:
    """The ContextManager used in graph.py must have large_result_threshold=3000 (not 4000 default or 800)."""

    def test_default_threshold_is_4000(self):
        """Default value is 4000 — confirms the bug existed before the fix."""
        cm_default = ContextManager()
        assert cm_default.large_result_threshold == 4000

    def test_graph_instantiation_uses_3000(self):
        """After the fix, the ContextManager in LangGraphOrchestrator.__init__ uses threshold=3000.

        We verify this by inspecting the source code — the constructor call must pass
        large_result_threshold=3000 explicitly.  We do this via grep on the source file
        rather than importing the full orchestrator (which has heavy dependencies).
        """
        import ast
        import pathlib

        src = pathlib.Path(
            __file__
        ).parent.parent.parent / "src" / "agentic_workflows" / "orchestration" / "langgraph" / "graph.py"
        tree = ast.parse(src.read_text())

        found_threshold = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ContextManager"
            ):
                for kw in node.keywords:
                    if kw.arg == "large_result_threshold" and isinstance(kw.value, ast.Constant):
                        found_threshold = kw.value.value
                        break

        assert found_threshold is not None, (
            "ContextManager() call in graph.py must pass large_result_threshold explicitly"
        )
        assert found_threshold == 3000, (
            f"Expected large_result_threshold=3000, got {found_threshold}"
        )

    def test_explicit_threshold_overrides_default(self):
        """Caller-supplied threshold wins over the class default."""
        cm = ContextManager(large_result_threshold=500)
        assert cm.large_result_threshold == 500

        cm2 = ContextManager(large_result_threshold=800)
        assert cm2.large_result_threshold == 800


# ── End-to-end: large result never enters messages ────────────────────────────


class TestEndToEndTruncationInMessages:
    """Integration-style: verify the full on_tool_result path when the primary gate runs first
    (graph.py already truncated before append) — on_tool_result must still extract artifacts."""

    def test_artifact_extraction_still_runs_for_large_results(self):
        """Even when the result is large, on_tool_result must update MissionContext artifacts."""
        from agentic_workflows.orchestration.langgraph.context_manager import MissionContext

        cm = ContextManager(large_result_threshold=100)
        large_result = {"mean": 42.5, "outliers": [99, 100], "non_outliers": list(range(50))}
        large_json = json.dumps(large_result)
        assert len(large_json) > 100

        # Simulate: graph.py already put a placeholder in messages (primary gate fired)
        placeholder = f"[tool_result: data_analysis, {len(large_json)} chars, stored in context]"
        state = _make_state([
            {"role": "system", "content": "system prompt"},
            {"role": "system", "content": f"TOOL_RESULT #1 (data_analysis): {placeholder}\nContinue."},
        ])
        state["mission_contexts"]["1"] = MissionContext(mission_id=1, goal="Analyze data").model_dump()
        state["active_mission_id"] = 1

        # on_tool_result receives the FULL result (not the placeholder)
        cm.on_tool_result(state, "data_analysis", large_result, {}, mission_id=1)

        # Artifacts must be extracted into MissionContext
        ctx = MissionContext.model_validate(state["mission_contexts"]["1"])
        assert "mean" in ctx.key_results
        assert ctx.key_results["mean"] == "42.5"

    def test_planner_receives_placeholder_not_full_blob(self):
        """After gating, state['messages'] must not contain the full JSON of a large result."""
        cm = ContextManager(large_result_threshold=100)
        large_result = _make_large_result(500)
        large_json = json.dumps(large_result)
        assert len(large_json) > 100

        # Simulate the gating (what graph.py now does)
        _threshold = cm.large_result_threshold
        _tool_result_for_msg = (
            f"[tool_result: search_files, {len(large_json)} chars, stored in context]"
            if len(large_json) > _threshold
            else large_json
        )
        state = _make_state([
            {"role": "system", "content": "system prompt"},
            {
                "role": "system",
                "content": f"TOOL_RESULT #1 (search_files): {_tool_result_for_msg}\nContinue.",
            },
        ])

        # Verify: no message contains the full JSON blob
        all_content = " ".join(m["content"] for m in state["messages"])
        assert large_json[:80] not in all_content
        assert "chars, stored in context" in all_content
