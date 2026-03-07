"""Unit tests for context_manager: MissionContext, ArtifactRecord, SubMissionContext, extract_artifacts, ContextManager."""

from __future__ import annotations

import pytest

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
