"""Unit tests for Phase 7.3 ContextManager extensions.

Tests the new optional params (mission_context_store, embedding_provider),
_persist_mission_context() behavior, and cross-run injection in
build_planner_context_injection().

Does NOT test Postgres -- uses MagicMock for the store.
"""
from unittest.mock import MagicMock

from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
from agentic_workflows.storage.mission_context_store import MissionContextResult


def _make_result(goal: str, summary: str) -> MissionContextResult:
    return MissionContextResult(
        id=1,
        run_id="prev-run",
        mission_id="m-1",
        goal=goal,
        summary=summary,
        tools_used=["write_file"],
        score=0.9,
        source_layer="L0",   # was missing — caused attribution log to emit "?"
    )


class TestContextManagerBackwardCompat:
    def test_zero_args_instantiation(self):
        cm = ContextManager()
        assert cm is not None
        assert cm._store is None
        assert cm._embedding_provider is None

    def test_none_params_equivalent_to_zero_args(self):
        cm = ContextManager(mission_context_store=None, embedding_provider=None)
        assert cm._store is None
        assert cm._embedding_provider is None

    def test_build_injection_no_store(self):
        cm = ContextManager()
        # Should not raise; returns str (possibly empty)
        state: dict = {"missions": [], "mission_contexts": {}, "messages": []}
        result = cm.build_planner_context_injection(state)
        assert isinstance(result, str)


class TestPersistMissionContext:
    def test_no_op_when_store_is_none(self):
        cm = ContextManager(mission_context_store=None)
        # Should not raise
        cm._persist_mission_context({
            "goal": "test goal",
            "summary": "test summary",
            "used_tools": ["write_file"],
            "key_results": {},
            "run_id": "r1",
            "mission_id": "m1",
        })

    def test_calls_store_upsert_when_store_provided(self):
        mock_store = MagicMock()
        cm = ContextManager(mission_context_store=mock_store)
        cm._persist_mission_context({
            "goal": "Compute fibonacci",
            "summary": "Computed fib(50)",
            "used_tools": ["math_stats"],
            "key_results": {"result": 12586269025},
            "run_id": "run-abc",
            "mission_id": "mission-1",
        })
        mock_store.upsert.assert_called_once()
        call_kwargs = mock_store.upsert.call_args.kwargs
        assert call_kwargs["goal"] == "Compute fibonacci"
        assert call_kwargs["run_id"] == "run-abc"

    def test_embed_sync_called_when_provider_provided(self):
        mock_store = MagicMock()
        mock_provider = MagicMock()
        mock_provider.embed_sync.return_value = [0.1] * 384
        cm = ContextManager(
            mission_context_store=mock_store,
            embedding_provider=mock_provider,
        )
        cm._persist_mission_context({
            "goal": "test goal",
            "summary": "summary",
            "used_tools": [],
            "key_results": {},
            "run_id": "r1",
            "mission_id": "m1",
        })
        mock_provider.embed_sync.assert_called_once_with("test goal")

    def test_graceful_on_store_exception(self):
        mock_store = MagicMock()
        mock_store.upsert.side_effect = RuntimeError("DB connection failed")
        cm = ContextManager(mission_context_store=mock_store)
        # Must not raise -- graceful degradation
        cm._persist_mission_context({
            "goal": "test",
            "summary": "s",
            "used_tools": [],
            "key_results": {},
            "run_id": "r1",
            "mission_id": "m1",
        })


class TestCrossRunInjection:
    def test_cross_run_hits_formatted_correctly(self):
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = [
            _make_result("Sort numbers ascending", "Sorted 100 numbers using sort_array"),
        ]
        cm = ContextManager(mission_context_store=mock_store)
        state: dict = {"missions": ["Sort the array"], "mission_contexts": {}, "messages": [], "step": 1}
        result = cm.build_planner_context_injection(state)
        assert "[Cross-run] Similar:" in result

    def test_output_capped_at_1500_chars(self):
        mock_store = MagicMock()
        # Return hits with very long summaries
        long_summary = "x" * 600
        mock_store.query_cascade.return_value = [
            _make_result(f"goal {i}", long_summary) for i in range(3)
        ]
        cm = ContextManager(mission_context_store=mock_store)
        state: dict = {"missions": ["test mission"], "mission_contexts": {}, "messages": [], "step": 1}
        result = cm.build_planner_context_injection(state)
        assert len(result) <= 1500

    def test_no_cross_run_when_store_none(self):
        cm = ContextManager(mission_context_store=None)
        state: dict = {"missions": ["test"], "mission_contexts": {}, "messages": [], "step": 1}
        result = cm.build_planner_context_injection(state)
        assert "[Cross-run] Similar:" not in result

    def test_graceful_on_store_query_exception(self):
        mock_store = MagicMock()
        mock_store.query_cascade.side_effect = RuntimeError("connection refused")
        cm = ContextManager(mission_context_store=mock_store)
        state: dict = {"missions": ["test"], "mission_contexts": {}, "messages": [], "step": 1}
        # Must not raise
        result = cm.build_planner_context_injection(state)
        assert isinstance(result, str)

    def test_attribution_shows_real_source_layer(self, caplog):
        import logging
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = [
            _make_result("Sort numbers ascending", "Sorted 100 numbers using sort_array"),
        ]
        cm = ContextManager(mission_context_store=mock_store)
        state: dict = {
            "missions": ["Sort the array"], "mission_contexts": {}, "messages": [],
            "run_id": "run-attr-test", "step": 1,
        }
        with caplog.at_level(logging.INFO, logger="context_manager"):
            result = cm.build_planner_context_injection(state)
        # Result must contain [Cross-run] (confirms hit was processed)
        assert "[Cross-run] Similar:" in result
        # Attribution in log must show real layer (L0:0.90), not placeholder (?)
        assert "L0:0.90" in caplog.text, f"Attribution not found in log: {caplog.text}"
        assert "?:0.90" not in caplog.text, "Source_layer missing — attribution shows '?'"


class TestGoalCache:
    """Cache correctness: embedding and cascade called once per unique goal per run."""

    def _make_state(self, goal: str, run_id: str = "run-1") -> dict:
        return {
            "missions": [goal],
            "mission_contexts": {},
            "messages": [],
            "run_id": run_id,
            "step": 1,  # step > 0 so cascade guard allows injection
        }

    def test_embed_sync_called_once_for_repeated_goal(self):
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []
        mock_provider = MagicMock()
        mock_provider.embed_sync.return_value = [0.1] * 384

        cm = ContextManager(mission_context_store=mock_store, embedding_provider=mock_provider)
        state = self._make_state("Sort the array", run_id="run-abc")

        # Call 5 times with the same goal and run_id
        for _ in range(5):
            cm.build_planner_context_injection(state)

        # embed_sync must be called exactly once (cached after first call)
        assert mock_provider.embed_sync.call_count == 1

    def test_cascade_query_called_once_for_repeated_goal(self):
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []
        mock_provider = MagicMock()
        mock_provider.embed_sync.return_value = [0.1] * 384

        cm = ContextManager(mission_context_store=mock_store, embedding_provider=mock_provider)
        state = self._make_state("Compute fibonacci", run_id="run-xyz")

        for _ in range(5):
            cm.build_planner_context_injection(state)

        assert mock_store.query_cascade.call_count == 1

    def test_empty_goal_skips_cascade_entirely(self):
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []

        cm = ContextManager(mission_context_store=mock_store)
        # State with no missions → goal_text = "", step=1 so only empty-goal guard fires
        state: dict = {"missions": [], "mission_contexts": {}, "messages": [], "run_id": "run-1", "step": 1}

        cm.build_planner_context_injection(state)

        # query_cascade must never be called for empty goal
        mock_store.query_cascade.assert_not_called()

    def test_different_run_ids_produce_separate_cache_entries(self):
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []
        mock_provider = MagicMock()
        mock_provider.embed_sync.return_value = [0.1] * 384

        cm = ContextManager(mission_context_store=mock_store, embedding_provider=mock_provider)
        goal = "Analyze data"

        # Call twice with different run_ids
        cm.build_planner_context_injection(self._make_state(goal, run_id="run-1"))
        cm.build_planner_context_injection(self._make_state(goal, run_id="run-2"))

        # Each unique run_id:goal pair → separate cache entry → embed_sync called twice
        assert mock_provider.embed_sync.call_count == 2
        assert mock_store.query_cascade.call_count == 2

    def test_same_run_different_goals_separate_cache_entries(self):
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []
        mock_provider = MagicMock()
        mock_provider.embed_sync.return_value = [0.1] * 384

        cm = ContextManager(mission_context_store=mock_store, embedding_provider=mock_provider)

        cm.build_planner_context_injection(self._make_state("Goal A", run_id="run-1"))
        cm.build_planner_context_injection(self._make_state("Goal B", run_id="run-1"))

        # Different goals → different cache entries
        assert mock_provider.embed_sync.call_count == 2

    def test_step_zero_suppresses_cross_run_injection(self):
        """Bug 4 regression: cascade query must NOT fire on step=0."""
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []

        cm = ContextManager(mission_context_store=mock_store)
        state = self._make_state("Sort numbers and write to file", run_id="run-1")
        state["step"] = 0

        cm.build_planner_context_injection(state)

        mock_store.query_cascade.assert_not_called()

    def test_step_nonzero_allows_cross_run_injection(self):
        """Cascade query fires when step > 0."""
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []

        cm = ContextManager(mission_context_store=mock_store)
        state = self._make_state("Sort numbers and write to file", run_id="run-1")
        state["step"] = 1

        cm.build_planner_context_injection(state)

        mock_store.query_cascade.assert_called_once()

    def test_active_mission_goal_used_for_multi_task_state(self):
        """Bug 3 regression: _get_current_goal_text must use current_mission_id, not missions[0]."""
        mock_store = MagicMock()
        mock_store.query_cascade.return_value = []
        mock_provider = MagicMock()
        mock_provider.embed_sync.return_value = [0.1] * 384

        cm = ContextManager(mission_context_store=mock_store, embedding_provider=mock_provider)

        state: dict = {
            "missions": ["Task 1: sort numbers", "Task 2: analyze data", "Task 3: write report"],
            "mission_contexts": {
                "1": {"mission_id": 1, "goal": "sort numbers", "status": "completed", "summary": "done", "artifacts": [], "tools_used": [], "key_results": {}, "step_range": [0, 2]},
                "2": {"mission_id": 2, "goal": "analyze data", "status": "active", "summary": "", "artifacts": [], "tools_used": [], "key_results": {}, "step_range": None},
                "3": {"mission_id": 3, "goal": "write report", "status": "pending", "summary": "", "artifacts": [], "tools_used": [], "key_results": {}, "step_range": None},
            },
            "messages": [],
            "run_id": "run-multi",
            "current_mission_id": 2,
            "step": 1,
        }

        cm.build_planner_context_injection(state)

        # The cascade query must be called with "analyze data" (mission 2), not "sort numbers" (mission 1)
        call_args = mock_store.query_cascade.call_args
        assert call_args is not None
        goal_used = call_args[0][0] if call_args[0] else call_args[1].get("goal_text", "")
        assert goal_used == "analyze data", f"Expected 'analyze data', got '{goal_used}'"
