"""Tests for structural_health in RunState and audit_report.

Covers:
- structural_health key present in audit_report after every run
- json_parse_fallback counter increments when fallback parser is used
- schema_mismatch counter present (even at 0 for clean runs)
"""
from __future__ import annotations

import tempfile

import pytest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from tests.conftest import ScriptedProvider


class _RawStringProvider:
    """Provider that returns raw (potentially non-JSON) strings for fallback testing."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._index = 0

    def context_size(self) -> int:
        return 32768

    def generate(self, messages, response_schema=None):  # noqa: ANN001
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]


def _make_orchestrator(provider, tmp_dir: str) -> LangGraphOrchestrator:
    return LangGraphOrchestrator(
        provider=provider,
        memo_store=SQLiteMemoStore(f"{tmp_dir}/memo.db"),
        checkpoint_store=SQLiteCheckpointStore(f"{tmp_dir}/checkpoints.db"),
        max_steps=5,
    )


class TestStructuralHealthKey:
    def test_audit_report_has_structural_health_key(self) -> None:
        """RunResult audit_report contains 'structural_health' key after a clean run."""
        provider = ScriptedProvider([
            {"action": "finish", "answer": "done"},
        ])
        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = _make_orchestrator(provider, tmp_dir)
            result = orchestrator.run("Say hello.")
        audit = result["audit_report"]
        assert audit is not None, "audit_report must not be None"
        assert "structural_health" in audit, (
            f"audit_report missing 'structural_health' key; got keys: {list(audit.keys())}"
        )

    def test_schema_mismatch_counter_present(self) -> None:
        """audit_report['structural_health']['schema_mismatch'] exists and is int."""
        provider = ScriptedProvider([
            {"action": "finish", "answer": "done"},
        ])
        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = _make_orchestrator(provider, tmp_dir)
            result = orchestrator.run("Say hello.")
        sh = result["audit_report"]["structural_health"]
        assert "schema_mismatch" in sh, (
            f"structural_health missing 'schema_mismatch'; got: {sh}"
        )
        assert isinstance(sh["schema_mismatch"], int), (
            f"schema_mismatch must be int; got {type(sh['schema_mismatch'])}"
        )

    def test_clean_run_has_zero_counters(self) -> None:
        """A clean run (no fallback) produces structural_health with both counters at 0."""
        provider = ScriptedProvider([
            {"action": "finish", "answer": "done"},
        ])
        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = _make_orchestrator(provider, tmp_dir)
            result = orchestrator.run("Say hello.")
        sh = result["audit_report"]["structural_health"]
        assert sh == {"json_parse_fallback": 0, "schema_mismatch": 0}, (
            f"Expected zero counters for clean run; got: {sh}"
        )


class TestFallbackCounter:
    def test_json_parse_fallback_counter_increments(self) -> None:
        """A run with malformed JSON increments the json_parse_fallback counter.

        The provider returns a string with prose before a valid JSON object.
        json.loads() fails on the full string, triggering the fallback
        extract-all-json-objects path in parse_all_actions_json().
        """
        # Prose prefix makes json.loads(whole_output) fail → fallback path fires
        fallback_response = 'Here is my action: {"action": "finish", "answer": "recovered"}'
        provider = _RawStringProvider([fallback_response])

        with tempfile.TemporaryDirectory() as tmp_dir:
            orchestrator = _make_orchestrator(provider, tmp_dir)
            result = orchestrator.run("Say hello.")
        sh = result["audit_report"]["structural_health"]
        assert sh["json_parse_fallback"] > 0, (
            f"Expected json_parse_fallback > 0 after fallback parse; got: {sh}"
        )
