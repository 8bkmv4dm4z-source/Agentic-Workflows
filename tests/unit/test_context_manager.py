"""Unit tests for context_manager: MissionContext, ArtifactRecord, SubMissionContext, extract_artifacts, ContextManager."""

from __future__ import annotations

from agentic_workflows.orchestration.langgraph.context_manager import (
    ArtifactRecord,
    ContextManager,
    MissionContext,
    SubMissionContext,
    extract_artifacts,
    extract_summary_from_result,
)

# ── Model tests ──────────────────────────────────────────────────────


class TestMissionContextModel:
    def test_mission_context_model(self):
        ctx = MissionContext(mission_id=1, goal="Write fibonacci")
        assert ctx.mission_id == 1
        assert ctx.goal == "Write fibonacci"
        assert ctx.status == "pending"
        assert ctx.tools_used == []
        assert ctx.key_results == {}
        assert ctx.artifacts == []
        assert ctx.sub_missions == {}
        assert ctx.summary == ""
        assert ctx.step_range is None

        # Roundtrip serialization
        d = ctx.model_dump()
        assert isinstance(d, dict)
        assert d["mission_id"] == 1
        restored = MissionContext.model_validate(d)
        assert restored.mission_id == 1
        assert restored.goal == "Write fibonacci"

    def test_sub_mission_context(self):
        sub = SubMissionContext(sub_mission_id="1.1", goal="Generate numbers")
        ctx = MissionContext(
            mission_id=1,
            goal="Parent",
            sub_missions={"1.1": sub},
        )
        assert "1.1" in ctx.sub_missions
        assert ctx.sub_missions["1.1"].goal == "Generate numbers"

    def test_artifact_record(self):
        ar = ArtifactRecord(
            key="file_path",
            value="/tmp/fib.txt",
            source_tool="write_file",
            source_mission_id=1,
        )
        assert ar.key == "file_path"
        assert ar.value == "/tmp/fib.txt"
        assert ar.source_tool == "write_file"
        assert ar.source_mission_id == 1


# ── Summary tests ────────────────────────────────────────────────────


class TestBuildSummary:
    def test_mission_summary(self):
        ctx = MissionContext(
            mission_id=1,
            goal="Sort data",
            tools_used=["data_analysis", "sort_array"],
            key_results={"mean": "42.0"},
            artifacts=[
                ArtifactRecord(
                    key="sorted_result",
                    value="[1,2,3]",
                    source_tool="sort_array",
                    source_mission_id=1,
                )
            ],
        )
        summary = ctx.build_summary()
        assert "Mission 1" in summary
        assert "Sort data" in summary
        assert "data_analysis" in summary
        assert "sort_array" in summary
        assert "mean" in summary
        assert "42.0" in summary
        assert "sorted_result" in summary

    def test_mission_summary_empty(self):
        ctx = MissionContext(mission_id=2, goal="Empty mission")
        summary = ctx.build_summary()
        assert "Mission 2" in summary
        assert "Empty mission" in summary
        # Should not crash with empty lists/dicts


# ── Artifact extraction tests ────────────────────────────────────────


class TestExtractArtifacts:
    def test_artifact_extraction_write_file(self):
        result = {"result": "Successfully wrote 100 characters to /tmp/fib.txt"}
        args = {"path": "/tmp/fib.txt", "content": "1, 1, 2, 3"}
        artifacts = extract_artifacts("write_file", result, args, mission_id=1)
        assert len(artifacts) >= 1
        paths = {a.key: a.value for a in artifacts}
        assert "file_path" in paths
        assert paths["file_path"] == "/tmp/fib.txt"

    def test_artifact_extraction_data_analysis(self):
        result = {
            "mean": 5.0,
            "median": 4.0,
            "outliers": [100],
            "non_outliers": [1, 2, 3, 4, 5],
        }
        artifacts = extract_artifacts("data_analysis", result, {}, mission_id=2)
        keys = {a.key for a in artifacts}
        assert "mean" in keys

    def test_artifact_extraction_sort_array(self):
        result = {"sorted": [1, 2, 3], "original": [3, 1, 2]}
        artifacts = extract_artifacts("sort_array", result, {}, mission_id=3)
        keys = {a.key for a in artifacts}
        assert "sorted_result" in keys

    def test_artifact_extraction_error(self):
        result = {"error": "Something went wrong"}
        artifacts = extract_artifacts("write_file", result, {}, mission_id=1)
        assert artifacts == []

    def test_artifact_extraction_unknown_tool(self):
        result = {"foo": "bar"}
        artifacts = extract_artifacts("unknown_tool", result, {}, mission_id=1)
        assert len(artifacts) == 1
        assert artifacts[0].key == "result"
        assert artifacts[0].source_tool == "unknown_tool"


# ── extract_summary_from_result tests ────────────────────────────────


class TestExtractSummaryFromResult:
    def test_extract_summary_from_result_write_file(self):
        result = {"result": "Successfully wrote 50 characters to /tmp/out.txt"}
        summary = extract_summary_from_result("write_file", result)
        assert "outcome" in summary

    def test_extract_summary_from_result_data_analysis(self):
        result = {"mean": 5.0, "median": 4.0, "outliers": [100]}
        summary = extract_summary_from_result("data_analysis", result)
        assert "mean" in summary

    def test_extract_summary_from_result_generic(self):
        result = {"some_key": "x" * 300}
        summary = extract_summary_from_result("unknown_tool", result)
        # Should truncate to 200 chars
        assert len(list(summary.values())[0]) <= 200


# ── ContextManager tests ─────────────────────────────────────────────


class TestContextManager:
    def test_cross_mission_artifacts(self):
        cm = ContextManager()
        state = {
            "mission_contexts": {
                "1": MissionContext(
                    mission_id=1,
                    goal="First",
                    artifacts=[
                        ArtifactRecord(
                            key="file_path",
                            value="/tmp/a.txt",
                            source_tool="write_file",
                            source_mission_id=1,
                        )
                    ],
                ).model_dump(),
                "2": MissionContext(
                    mission_id=2,
                    goal="Second",
                    artifacts=[
                        ArtifactRecord(
                            key="sorted",
                            value="[1,2]",
                            source_tool="sort_array",
                            source_mission_id=2,
                        )
                    ],
                ).model_dump(),
                "3": MissionContext(mission_id=3, goal="Third").model_dump(),
            }
        }
        # Mission 3 should see artifacts from missions 1 and 2, not 3
        artifacts = cm.get_artifacts_for_mission(state, mission_id=3)
        assert len(artifacts) == 2
        sources = {a.source_mission_id for a in artifacts}
        assert sources == {1, 2}

        # Mission 2 should only see artifacts from mission 1
        artifacts_m2 = cm.get_artifacts_for_mission(state, mission_id=2)
        assert len(artifacts_m2) == 1
        assert artifacts_m2[0].source_mission_id == 1

        # Mission 1 should see no prior artifacts
        artifacts_m1 = cm.get_artifacts_for_mission(state, mission_id=1)
        assert artifacts_m1 == []


# ── Specialist enrichment tests ─────────────────────────────────────


class TestSpecialistEnrichment:
    """Tests for ContextManager.build_specialist_context() — specialist enrichment."""

    def _make_state(self, contexts: dict[str, dict]) -> dict:
        """Helper: build a minimal state dict with mission_contexts and missions."""
        missions = []
        for mid_str in sorted(contexts, key=lambda k: int(k)):
            missions.append(contexts[mid_str].get("goal", ""))
        return {"mission_contexts": contexts, "missions": missions}

    def test_specialist_enrichment(self):
        """build_specialist_context() returns dict with mission_goal and prior_results_summary."""
        cm = ContextManager()
        ctx1 = MissionContext(mission_id=1, goal="Sort an array").model_dump()
        state = self._make_state({"1": ctx1})
        result = cm.build_specialist_context(state, mission_id=1)
        assert "mission_goal" in result
        assert "prior_results_summary" in result
        assert result["mission_goal"] == "Sort an array"

    def test_specialist_enrichment_no_prior(self):
        """When no prior missions completed, prior_results_summary is empty string."""
        cm = ContextManager()
        ctx1 = MissionContext(mission_id=1, goal="First mission").model_dump()
        state = self._make_state({"1": ctx1})
        result = cm.build_specialist_context(state, mission_id=1)
        assert result["prior_results_summary"] == ""

    def test_specialist_enrichment_with_prior(self):
        """When missions 1,2 completed, context for mission 3 contains summaries of 1 and 2."""
        cm = ContextManager()
        ctx1 = MissionContext(
            mission_id=1, goal="Analyze data", status="completed",
            tools_used=["data_analysis"], key_results={"mean": "42.0"},
        ).model_dump()
        ctx2 = MissionContext(
            mission_id=2, goal="Sort results", status="completed",
            tools_used=["sort_array"], key_results={"sorted": "[1,2,3]"},
        ).model_dump()
        ctx3 = MissionContext(mission_id=3, goal="Write file").model_dump()
        state = self._make_state({"1": ctx1, "2": ctx2, "3": ctx3})

        result = cm.build_specialist_context(state, mission_id=3)
        assert "Mission 1" in result["prior_results_summary"]
        assert "Mission 2" in result["prior_results_summary"]
        assert "Analyze data" in result["prior_results_summary"]
        assert "Sort results" in result["prior_results_summary"]

    def test_specialist_enrichment_includes_artifacts(self):
        """prior_results_summary includes artifact information from prior missions."""
        cm = ContextManager()
        ctx1 = MissionContext(
            mission_id=1, goal="Write output", status="completed",
            tools_used=["write_file"],
            artifacts=[
                ArtifactRecord(
                    key="file_path", value="/tmp/out.txt",
                    source_tool="write_file", source_mission_id=1,
                )
            ],
        ).model_dump()
        ctx2 = MissionContext(mission_id=2, goal="Read output").model_dump()
        state = self._make_state({"1": ctx1, "2": ctx2})

        result = cm.build_specialist_context(state, mission_id=2)
        assert "file_path" in result["prior_results_summary"]
        assert "/tmp/out.txt" in result["prior_results_summary"]

    def test_specialist_enrichment_uses_same_summary_format(self):
        """prior_results_summary uses same format as MissionContext.build_summary()."""
        cm = ContextManager()
        ctx1 = MissionContext(
            mission_id=1, goal="Analyze data", status="completed",
            tools_used=["data_analysis"], key_results={"mean": "42.0"},
        )
        ctx1_dump = ctx1.model_dump()
        ctx2 = MissionContext(mission_id=2, goal="Next step").model_dump()
        state = self._make_state({"1": ctx1_dump, "2": ctx2})

        result = cm.build_specialist_context(state, mission_id=2)
        # The summary for mission 1 in prior_results_summary should match build_summary()
        expected_summary = ctx1.build_summary()
        assert expected_summary in result["prior_results_summary"]

    def test_specialist_enrichment_goal_fallback_to_missions(self):
        """When mission_contexts has no entry, fall back to state['missions'] list."""
        cm = ContextManager()
        state = {"mission_contexts": {}, "missions": ["First goal", "Second goal"]}
        result = cm.build_specialist_context(state, mission_id=2)
        assert result["mission_goal"] == "Second goal"

    def test_executor_state_has_enrichment_fields(self):
        """ExecutorState TypedDict includes mission_goal and prior_results_summary."""
        from agentic_workflows.orchestration.langgraph.specialist_executor import ExecutorState
        assert "mission_goal" in ExecutorState.__annotations__
        assert "prior_results_summary" in ExecutorState.__annotations__

    def test_evaluator_state_has_enrichment_fields(self):
        """EvaluatorState TypedDict includes mission_goal and prior_results_summary."""
        from agentic_workflows.orchestration.langgraph.specialist_evaluator import EvaluatorState
        assert "mission_goal" in EvaluatorState.__annotations__
        assert "prior_results_summary" in EvaluatorState.__annotations__


# ── Eviction tests (Plan 02) ────────────────────────────────────────


def _make_state(messages=None, mission_contexts=None, policy_flags=None, step=5):
    """Build a minimal state dict for eviction testing."""
    return {
        "messages": messages or [],
        "mission_contexts": mission_contexts or {},
        "policy_flags": policy_flags or {},
        "step": step,
    }


class TestEvictionMissionBoundary:
    """on_mission_complete() creates summary, evicts mission messages, injects summary."""

    def test_eviction_mission_boundary(self):
        cm = ContextManager()
        ctx = MissionContext(
            mission_id=1,
            goal="Sort the data",
            tools_used=["sort_array"],
            key_results={"sorted": "[1,2,3]"},
            step_range=(2, 4),
        )
        messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "user", "content": "Sort this data"},  # step 1 (before mission)
            {"role": "assistant", "content": "sorting..."},  # step 2 (in mission)
            {"role": "user", "content": "TOOL RESULT: sorted"},  # step 3 (in mission)
            {"role": "assistant", "content": "done sorting"},  # step 4 (in mission)
            {"role": "user", "content": "Next task"},  # step 5 (after mission)
        ]
        state = _make_state(
            messages=messages,
            mission_contexts={"1": ctx.model_dump()},
            step=5,
        )
        cm.on_mission_complete(state, mission_id=1)

        # Mission messages (indices 2-4) should be removed and replaced by summary
        remaining_contents = [m["content"] for m in state["messages"]]
        assert "sorting..." not in remaining_contents
        assert "TOOL RESULT: sorted" not in remaining_contents
        assert "done sorting" not in remaining_contents

        # Summary should be injected as role="user" with [Orchestrator] prefix
        summary_msgs = [m for m in state["messages"] if "[Orchestrator]" in m.get("content", "")]
        assert len(summary_msgs) >= 1
        assert summary_msgs[0]["role"] == "user"
        assert "Mission 1" in summary_msgs[0]["content"]

        # System prompt and non-mission messages preserved
        assert state["messages"][0]["role"] == "system"
        assert "Sort this data" in [m["content"] for m in state["messages"]]
        assert "Next task" in [m["content"] for m in state["messages"]]

        # MissionContext status updated
        updated_ctx = MissionContext.model_validate(state["mission_contexts"]["1"])
        assert updated_ctx.status == "completed"
        assert updated_ctx.summary != ""


class TestLargeResultEviction:
    """on_tool_result() replaces large results with compact placeholders."""

    def test_large_result_eviction(self):
        cm = ContextManager(large_result_threshold=100)
        large_result = {"data": "x" * 200}
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do something"},
            {"role": "user", "content": f"TOOL RESULT (big_tool):\n{{'data': '{'x' * 200}'}}"},
        ]
        ctx = MissionContext(mission_id=1, goal="test", step_range=(1, 3))
        state = _make_state(
            messages=messages,
            mission_contexts={"1": ctx.model_dump()},
        )
        cm.on_tool_result(state, tool_name="big_tool", result=large_result, args={}, mission_id=1)

        # The large tool result message should be replaced with a placeholder
        replaced = state["messages"][2]
        assert replaced["role"] == "user"
        assert "[Orchestrator]" in replaced["content"]
        assert "[tool_result: big_tool" in replaced["content"]
        assert "chars" in replaced["content"]

    def test_small_result_not_evicted(self):
        cm = ContextManager(large_result_threshold=4000)
        small_result = {"data": "ok"}
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "TOOL RESULT (small_tool):\n{\"data\": \"ok\"}"},
        ]
        ctx = MissionContext(mission_id=1, goal="test", step_range=(1, 2))
        state = _make_state(
            messages=messages,
            mission_contexts={"1": ctx.model_dump()},
        )
        cm.on_tool_result(state, tool_name="small_tool", result=small_result, args={}, mission_id=1)

        # Small result should NOT be replaced
        assert "TOOL RESULT" in state["messages"][1]["content"]


class TestSlidingWindowCap:
    """compact() enforces sliding_window_cap, dropping oldest non-system messages."""

    def test_sliding_window_cap(self):
        cm = ContextManager(sliding_window_cap=10)
        messages = [{"role": "system", "content": "sys"}]
        messages += [{"role": "user", "content": f"msg-{i}"} for i in range(20)]
        state = _make_state(messages=messages)
        cm.compact(state)

        # Should have system prompt + 9 newest = 10 total
        assert len(state["messages"]) == 10
        assert state["messages"][0]["role"] == "system"
        assert state["messages"][0]["content"] == "sys"
        # Last message should be the newest
        assert state["messages"][-1]["content"] == "msg-19"

    def test_under_cap_not_trimmed(self):
        cm = ContextManager(sliding_window_cap=30)
        messages = [{"role": "system", "content": "sys"}]
        messages += [{"role": "user", "content": f"msg-{i}"} for i in range(5)]
        state = _make_state(messages=messages)
        cm.compact(state)
        assert len(state["messages"]) == 6  # unchanged


class TestEvictionObservability:
    """Eviction events emit logger.info and policy_flags.pipeline_trace entries."""

    def test_eviction_observability(self):
        cm = ContextManager()
        state = _make_state(policy_flags={})
        cm._emit_eviction_event(
            state,
            trigger="mission_complete",
            mission_id=1,
            messages_removed=3,
            summary_injected="Mission 1 summary",
        )
        trace = state["policy_flags"].get("pipeline_trace", [])
        assert len(trace) == 1
        entry = trace[0]
        assert entry["stage"] == "context_eviction"
        assert entry["trigger"] == "mission_complete"
        assert entry["mission_id"] == 1
        assert entry["messages_removed"] == 3


class TestNoConsecutiveSystemMessages:
    """All injected messages use role='user' with [Orchestrator] prefix."""

    def test_no_consecutive_system_messages(self):
        cm = ContextManager()
        ctx = MissionContext(
            mission_id=1,
            goal="Test",
            tools_used=["sort_array"],
            step_range=(1, 3),
        )
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "assistant", "content": "working"},
            {"role": "user", "content": "result"},
        ]
        state = _make_state(
            messages=messages,
            mission_contexts={"1": ctx.model_dump()},
        )
        cm.on_mission_complete(state, mission_id=1)

        # No injected message should have role="system"
        for msg in state["messages"]:
            if "[Orchestrator]" in msg.get("content", ""):
                assert msg["role"] == "user", f"Injected message has role={msg['role']}, expected 'user'"


class TestFullMultiMissionLifecycle:
    """Integration-level test: multi-mission flow through ContextManager lifecycle."""

    def test_full_multi_mission_context_lifecycle(self):
        """End-to-end: 2 missions through ContextManager lifecycle."""
        cm = ContextManager(large_result_threshold=100, sliding_window_cap=30)

        # Setup: state with 2 missions
        ctx1 = MissionContext(
            mission_id=1,
            goal="Write fibonacci to file",
            step_range=(1, 4),
        )
        ctx2 = MissionContext(
            mission_id=2,
            goal="Read file and sort contents",
            step_range=(5, 8),
        )
        messages = [
            {"role": "system", "content": "You are an agent."},
            {"role": "assistant", "content": "I will write fibonacci."},  # step 1
            {"role": "user", "content": "TOOL RESULT (write_file):\n{\"result\": \"wrote 50 chars to /tmp/fib.txt\"}"},  # step 2
            {"role": "assistant", "content": "File written."},  # step 3
            {"role": "user", "content": "TOOL RESULT (memoize):\n{\"value_hash\": \"abc123\"}"},  # step 4
            {"role": "assistant", "content": "Now reading file."},  # step 5
            {"role": "user", "content": "TOOL RESULT (read_file):\n{\"content\": \"1,1,2,3,5\"}"},  # step 6
            {"role": "assistant", "content": "Sorting contents."},  # step 7
            {"role": "user", "content": "TOOL RESULT (sort_array):\n{\"sorted\": [1,1,2,3,5]}"},  # step 8
        ]
        state = _make_state(
            messages=messages,
            mission_contexts={
                "1": ctx1.model_dump(),
                "2": ctx2.model_dump(),
            },
            step=8,
        )

        # Mission 1: on_tool_result(write_file) -> on_mission_complete(1)
        write_result = {"result": "Successfully wrote 50 characters to /tmp/fib.txt"}
        write_args = {"path": "/tmp/fib.txt", "content": "1, 1, 2, 3, 5"}
        cm.on_tool_result(state, "write_file", write_result, write_args, mission_id=1)

        # Verify artifacts extracted for mission 1
        ctx1_updated = MissionContext.model_validate(state["mission_contexts"]["1"])
        assert len(ctx1_updated.artifacts) >= 1
        assert any(a.key == "file_path" for a in ctx1_updated.artifacts)
        assert "write_file" in ctx1_updated.tools_used

        # Complete mission 1
        cm.on_mission_complete(state, mission_id=1)

        # Verify: mission 1 summary injected, messages pruned
        ctx1_done = MissionContext.model_validate(state["mission_contexts"]["1"])
        assert ctx1_done.status == "completed"
        assert ctx1_done.summary != ""

        # Verify summary message injected with [Orchestrator] prefix
        orchestrator_msgs = [
            m for m in state["messages"]
            if "[Orchestrator]" in m.get("content", "") and "Mission 1" in m.get("content", "")
        ]
        assert len(orchestrator_msgs) >= 1
        assert orchestrator_msgs[0]["role"] == "user"

        # Mission 2: check artifacts from mission 1 available
        artifacts = cm.get_artifacts_for_mission(state, mission_id=2)
        assert len(artifacts) >= 1
        assert artifacts[0].key == "file_path"
        assert artifacts[0].value == "/tmp/fib.txt"

        # Verify: build_specialist_context for mission 2 includes mission 1 summary
        specialist_ctx = cm.build_specialist_context(state, mission_id=2)
        assert "Mission 1" in specialist_ctx["prior_results_summary"]
        assert "Write fibonacci" in specialist_ctx["prior_results_summary"]
        assert specialist_ctx["mission_goal"] == "Read file and sort contents"

        # Verify: compact() enforces sliding window
        cm.compact(state)
        assert len(state["messages"]) <= 30

        # Verify: no consecutive system messages in final state
        for i in range(1, len(state["messages"])):
            if state["messages"][i].get("role") == "system":
                assert state["messages"][i - 1].get("role") != "system", (
                    f"Consecutive system messages at index {i-1} and {i}"
                )

    def test_edge_case_empty_state(self):
        """ContextManager doesn't crash on empty state (no mission_contexts key)."""
        cm = ContextManager()
        state: dict = {"messages": [], "policy_flags": {}, "step": 0}

        # on_tool_result with no mission_contexts -- should not crash
        cm.on_tool_result(state, "write_file", {"result": "ok"}, {}, mission_id=1)
        # on_mission_complete with no mission_contexts -- should not crash
        cm.on_mission_complete(state, mission_id=1)
        # compact with empty messages -- should not crash
        cm.compact(state)
        # build_specialist_context with no mission_contexts -- should not crash
        result = cm.build_specialist_context(state, mission_id=1)
        assert result["mission_goal"] == ""
        assert result["prior_results_summary"] == ""

    def test_edge_case_mission_id_zero(self):
        """ContextManager handles mission_id=0 gracefully."""
        cm = ContextManager()
        state = _make_state(mission_contexts={})
        # Should not crash with mission_id=0
        cm.on_tool_result(state, "write_file", {"result": "ok"}, {}, mission_id=0)
        cm.on_mission_complete(state, mission_id=0)

    def test_edge_case_missing_mission_context(self):
        """ContextManager handles missing mission_context entry gracefully."""
        cm = ContextManager()
        state = _make_state(
            messages=[{"role": "system", "content": "sys"}],
            mission_contexts={"1": MissionContext(mission_id=1, goal="test").model_dump()},
        )
        # Mission 2 doesn't exist in mission_contexts -- should not crash
        cm.on_tool_result(state, "write_file", {"result": "ok"}, {}, mission_id=2)
        cm.on_mission_complete(state, mission_id=2)


class TestCompactReplacesOldEviction:
    """compact() calls on_tool_result for large results + enforces sliding window."""

    def test_compact_replaces_old_eviction(self):
        cm = ContextManager(large_result_threshold=100, sliding_window_cap=10)
        messages = [{"role": "system", "content": "sys"}]
        # Add a large tool result message
        messages.append({"role": "user", "content": "TOOL RESULT (big):\n" + "x" * 500})
        # Add more messages to exceed sliding window
        messages += [{"role": "user", "content": f"msg-{i}"} for i in range(15)]
        state = _make_state(messages=messages)
        cm.compact(state)

        # Should enforce sliding window cap
        assert len(state["messages"]) <= 10


class TestBuildPlannerContextInjection:
    """build_planner_context_injection returns formatted string with completed mission summaries."""

    def test_build_planner_context_injection(self):
        cm = ContextManager()
        ctx1 = MissionContext(
            mission_id=1,
            goal="Sort data",
            status="completed",
            summary="Mission 1: Sort data | Tools: sort_array",
            artifacts=[
                ArtifactRecord(
                    key="sorted_result",
                    value="[1,2,3]",
                    source_tool="sort_array",
                    source_mission_id=1,
                )
            ],
        )
        ctx2 = MissionContext(mission_id=2, goal="Write file", status="pending")
        state = _make_state(
            mission_contexts={
                "1": ctx1.model_dump(),
                "2": ctx2.model_dump(),
            }
        )
        result = cm.build_planner_context_injection(state)
        assert "[Orchestrator]" in result
        assert "Mission 1" in result or "Sort data" in result
        assert "sorted_result" in result

    def test_build_planner_context_injection_empty(self):
        cm = ContextManager()
        state = _make_state(mission_contexts={})
        result = cm.build_planner_context_injection(state)
        assert result == ""

    def test_build_planner_context_injection_no_completed(self):
        cm = ContextManager()
        ctx = MissionContext(mission_id=1, goal="Pending", status="pending")
        state = _make_state(mission_contexts={"1": ctx.model_dump()})
        result = cm.build_planner_context_injection(state)
        assert result == ""
