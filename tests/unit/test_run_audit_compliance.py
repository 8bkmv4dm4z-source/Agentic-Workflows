"""Tests for compliance rate columns in run_audit.py cross-run dashboard."""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import redirect_stdout
from unittest.mock import patch

from agentic_workflows.orchestration.langgraph.run_audit import (
    RunSummary,
    _print_table,
    summarize_runs,
)


def test_run_summary_has_compliance_fields():
    """RunSummary with compliance fields is accessible."""
    summary = RunSummary(
        run_id="r1",
        status="SUCCESS",
        step_count=10,
        tools_used_count=5,
        tools_by_step="1:read_file",
        memo_entry_count=0,
        invalid_json_retries=0,
        duplicate_tool_retries=0,
        memo_policy_retries=0,
        provider_timeout_retries=0,
        content_validation_retries=0,
        memo_retrieve_hits=0,
        memo_retrieve_misses=0,
        cache_reuse_hits=0,
        cache_reuse_misses=0,
        issue_flags="",
        finalized_at="2026-01-01",
        schema_compliance_rate=0.85,
        json_parse_fallbacks=1,
        format_retries=1,
        cloud_fallback_count=0,
    )
    assert summary.schema_compliance_rate == 0.85
    assert summary.json_parse_fallbacks == 1
    assert summary.format_retries == 1
    assert summary.cloud_fallback_count == 0


def _make_checkpoint_db(state: dict) -> str:
    """Create an in-memory checkpoint DB with a single run state."""
    db_path = ":memory:"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE graph_checkpoints (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            step INTEGER,
            node_name TEXT,
            state_json TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO graph_checkpoints (run_id, step, node_name, state_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("test-run", 10, "finalize", json.dumps(state), "2026-01-01T00:00:00"),
    )
    conn.commit()
    return db_path


def test_summarize_runs_with_structural_health():
    """summarize_runs computes compliance_rate from structural_health."""
    state = {
        "step": 10,
        "final_answer": "Done",
        "tool_history": [],
        "retry_counts": {},
        "policy_flags": {},
        "structural_health": {
            "json_parse_fallback": 2,
            "format_retries": 1,
            "cloud_fallback_count": 3,
        },
    }
    # (10 - 2 - 1) / 10 = 0.7
    with patch(
        "agentic_workflows.orchestration.langgraph.run_audit._load_latest_states"
    ) as mock_load, patch(
        "agentic_workflows.orchestration.langgraph.run_audit._load_memo_counts",
        return_value={},
    ):
        mock_load.return_value = [
            {
                "run_id": "test-run",
                "node_name": "finalize",
                "step": 10,
                "state_json": json.dumps(state),
                "created_at": "2026-01-01T00:00:00",
            }
        ]
        rows = summarize_runs()

    assert len(rows) == 1
    assert rows[0].schema_compliance_rate == 0.7
    assert rows[0].json_parse_fallbacks == 2
    assert rows[0].format_retries == 1
    assert rows[0].cloud_fallback_count == 3


def test_summarize_runs_missing_structural_health_defaults():
    """When structural_health is missing, compliance_rate defaults to 1.0."""
    state = {
        "step": 5,
        "final_answer": "Done",
        "tool_history": [],
        "retry_counts": {},
        "policy_flags": {},
    }
    with patch(
        "agentic_workflows.orchestration.langgraph.run_audit._load_latest_states"
    ) as mock_load, patch(
        "agentic_workflows.orchestration.langgraph.run_audit._load_memo_counts",
        return_value={},
    ):
        mock_load.return_value = [
            {
                "run_id": "test-run",
                "node_name": "finalize",
                "step": 5,
                "state_json": json.dumps(state),
                "created_at": "2026-01-01T00:00:00",
            }
        ]
        rows = summarize_runs()

    assert len(rows) == 1
    assert rows[0].schema_compliance_rate == 1.0
    assert rows[0].json_parse_fallbacks == 0
    assert rows[0].format_retries == 0
    assert rows[0].cloud_fallback_count == 0


def test_print_table_includes_compliance_column():
    """_print_table output includes 'compliance' column header."""
    summary = RunSummary(
        run_id="r1",
        status="SUCCESS",
        step_count=10,
        tools_used_count=5,
        tools_by_step="1:read_file",
        memo_entry_count=0,
        invalid_json_retries=0,
        duplicate_tool_retries=0,
        memo_policy_retries=0,
        provider_timeout_retries=0,
        content_validation_retries=0,
        memo_retrieve_hits=0,
        memo_retrieve_misses=0,
        cache_reuse_hits=0,
        cache_reuse_misses=0,
        issue_flags="",
        finalized_at="2026-01-01",
        schema_compliance_rate=0.85,
        json_parse_fallbacks=1,
        format_retries=0,
        cloud_fallback_count=0,
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_table([summary])
    output = buf.getvalue()
    assert "compliance" in output.lower()
    assert "85%" in output
