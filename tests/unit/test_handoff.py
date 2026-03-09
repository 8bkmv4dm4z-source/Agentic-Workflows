"""Unit tests for handoff schema and routing logic."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_workflows.orchestration.langgraph.handoff import (
    TaskHandoff,
    create_handoff,
    create_handoff_result,
)
from agentic_workflows.orchestration.langgraph.state_schema import (
    ensure_state_defaults,
    new_run_state,
)


class TestTaskHandoff:
    def test_create_handoff_defaults(self) -> None:
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        assert h.task_id == "t1"
        assert h.specialist == "executor"
        assert h.mission_id == 1
        assert h.tool_scope == []
        assert h.input_context == {}
        assert h.token_budget == 4096

    def test_create_handoff_custom(self) -> None:
        h = create_handoff(
            task_id="t2",
            specialist="evaluator",
            mission_id=3,
            tool_scope=["text_analysis", "regex_matcher"],
            input_context={"mission_text": "Analyze text"},
            token_budget=2048,
        )
        assert h.specialist == "evaluator"
        assert h.tool_scope == ["text_analysis", "regex_matcher"]
        assert h.token_budget == 2048

    def test_handoff_is_pydantic_model(self) -> None:
        from pydantic import BaseModel

        h = create_handoff(task_id="t1", specialist="supervisor", mission_id=1)
        assert isinstance(h, BaseModel)
        assert h.task_id == "t1"

    def test_handoff_extra_field_raises(self) -> None:
        """Extra fields are rejected by ConfigDict(extra='forbid')."""
        with pytest.raises(ValidationError):
            TaskHandoff(
                task_id="t1",
                specialist="executor",
                mission_id=1,
                tool_scope=[],
                input_context={},
                token_budget=4096,
                unexpected_extra="x",
            )

    def test_handoff_model_dump_roundtrip(self) -> None:
        """model_dump() returns a plain dict with correct values."""
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        d = h.model_dump()
        assert isinstance(d, dict)
        assert d["task_id"] == "t1"
        assert d["specialist"] == "executor"
        assert d["mission_id"] == 1


class TestHandoffResult:
    def test_create_result_defaults(self) -> None:
        r = create_handoff_result(task_id="t1", specialist="executor")
        assert r.status == "success"
        assert r.output == {}
        assert r.tokens_used == 0

    def test_create_result_error(self) -> None:
        r = create_handoff_result(
            task_id="t1",
            specialist="executor",
            status="error",
            output={"error": "tool not found"},
            tokens_used=150,
        )
        assert r.status == "error"
        assert "error" in r.output
        assert r.tokens_used == 150

    def test_create_result_timeout(self) -> None:
        r = create_handoff_result(task_id="t1", specialist="supervisor", status="timeout")
        assert r.status == "timeout"

    def test_result_model_dump_roundtrip(self) -> None:
        """model_dump() returns a plain dict."""
        r = create_handoff_result(task_id="t1", specialist="executor")
        d = r.model_dump()
        assert isinstance(d, dict)
        assert d["status"] == "success"
        assert d["tokens_used"] == 0


class TestStateSchemaHandoffFields:
    def test_new_run_state_has_handoff_fields(self) -> None:
        state = new_run_state("sys", "user")
        assert state["handoff_queue"] == []
        assert state["handoff_results"] == []
        assert state["active_specialist"] == "supervisor"

    def test_new_run_state_has_token_budget(self) -> None:
        state = new_run_state("sys", "user")
        assert state["token_budget_remaining"] == 100_000
        assert state["token_budget_used"] == 0

    def test_ensure_defaults_backfills_handoff(self) -> None:
        state = {"run_id": "test", "messages": []}
        repaired = ensure_state_defaults(state)
        assert repaired["handoff_queue"] == []
        assert repaired["handoff_results"] == []
        assert repaired["active_specialist"] == "supervisor"
        assert repaired["token_budget_remaining"] == 100_000
        assert repaired["token_budget_used"] == 0

    def test_ensure_defaults_preserves_existing(self) -> None:
        state = {
            "run_id": "test",
            "messages": [],
            "handoff_queue": [{"task_id": "t1"}],
            "active_specialist": "evaluator",
            "token_budget_remaining": 5000,
            "token_budget_used": 95000,
        }
        repaired = ensure_state_defaults(state)
        assert len(repaired["handoff_queue"]) == 1
        assert repaired["active_specialist"] == "evaluator"
        assert repaired["token_budget_remaining"] == 5000
        assert repaired["token_budget_used"] == 95000


class TestHandoffRouting:
    def test_handoff_queue_serializable(self) -> None:
        """TaskHandoff.model_dump() can be stored in state handoff_queue."""
        state = new_run_state("sys", "user")
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        state["handoff_queue"].append(h.model_dump())
        assert len(state["handoff_queue"]) == 1
        assert state["handoff_queue"][0]["specialist"] == "executor"

    def test_handoff_result_stored(self) -> None:
        state = new_run_state("sys", "user")
        r = create_handoff_result(
            task_id="t1", specialist="executor", output={"sorted": [1, 2, 3]}
        )
        state["handoff_results"].append(r.model_dump())
        assert len(state["handoff_results"]) == 1
        assert state["handoff_results"][0]["status"] == "success"


if __name__ == "__main__":
    import unittest

    unittest.main()
