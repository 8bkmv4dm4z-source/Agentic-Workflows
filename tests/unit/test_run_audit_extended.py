"""Extended tests for run_audit.py — _print_table, _write_csv, _print_run_details, main, helpers."""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.run_audit import (
    RunSummary,
    _fibonacci_issue_from_state,
    _parse_csv_int_list,
    _print_run_details,
    _print_table,
    _status_from_state,
    _write_csv,
    main,
    summarize_runs,
)
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state


def _make_summary(**overrides) -> RunSummary:
    defaults = dict(
        run_id="run-1",
        status="SUCCESS",
        step_count=3,
        tools_used_count=2,
        tools_by_step="1:sort_array | 2:write_file",
        memo_entry_count=1,
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
        finalized_at="2024-01-01T00:00:00",
    )
    defaults.update(overrides)
    return RunSummary(**defaults)


class TestStatusFromState(unittest.TestCase):
    def test_non_finalize_node_is_failed(self) -> None:
        assert _status_from_state("plan", "some answer") == "FAILED"

    def test_empty_answer_is_failed(self) -> None:
        assert _status_from_state("finalize", "   ") == "FAILED"

    def test_planner_failed_answer_is_failed(self) -> None:
        assert _status_from_state("finalize", "Planner failed to produce JSON") == "FAILED"

    def test_run_failed_answer_is_failed(self) -> None:
        assert _status_from_state("finalize", "Run failed due to timeout") == "FAILED"

    def test_success(self) -> None:
        assert _status_from_state("finalize", "All tasks completed.") == "SUCCESS"


class TestParseCsvIntList(unittest.TestCase):
    def test_valid_list(self) -> None:
        assert _parse_csv_int_list("1, 2, 3") == [1, 2, 3]

    def test_empty_string(self) -> None:
        assert _parse_csv_int_list("") == []

    def test_non_integer_token_returns_none(self) -> None:
        assert _parse_csv_int_list("1, 2, abc, 4") is None

    def test_float_token_returns_none(self) -> None:
        assert _parse_csv_int_list("1.5, 2") is None

    def test_negative_numbers(self) -> None:
        result = _parse_csv_int_list("-1, 2, -3")
        assert result == [-1, 2, -3]


class TestFibonacciIssueFromState(unittest.TestCase):
    def _make_state(self, path: str, content: str) -> dict:
        return {
            "tool_history": [
                {
                    "call": 1,
                    "tool": "write_file",
                    "args": {"path": path, "content": content},
                    "result": {},
                }
            ]
        }

    def test_no_write_file_returns_empty(self) -> None:
        state = {"tool_history": [{"call": 1, "tool": "sort_array", "args": {}, "result": {}}]}
        assert _fibonacci_issue_from_state(state) == ""

    def test_no_fib_in_path_returns_empty(self) -> None:
        state = self._make_state("output.txt", "0, 1, 1, 2")
        assert _fibonacci_issue_from_state(state) == ""

    def test_non_integer_tokens_flag(self) -> None:
        state = self._make_state("fib.txt", "0, 1, abc")
        assert _fibonacci_issue_from_state(state) == "fib_non_integer_tokens"

    def test_wrong_length_flag(self) -> None:
        state = self._make_state("fib.txt", "0, 1, 1, 2, 3")
        assert _fibonacci_issue_from_state(state) == "fib_len_5"

    def test_bad_prefix_flag(self) -> None:
        # 100 numbers but starts with wrong values
        nums = [1] + [1] + [2] * 98  # wrong: starts with 1,1 not 0,1
        content = ", ".join(str(n) for n in nums)
        state = self._make_state("fib.txt", content)
        assert _fibonacci_issue_from_state(state) == "fib_bad_prefix"

    def test_fib_mismatch_flag(self) -> None:
        # 100 numbers, starts with 0,1 but breaks sequence
        nums = [0, 1]
        for i in range(2, 100):
            nums.append(nums[i - 1] + nums[i - 2])
        nums[50] = 99999  # corrupt one entry
        content = ", ".join(str(n) for n in nums)
        state = self._make_state("fib.txt", content)
        issue = _fibonacci_issue_from_state(state)
        assert issue.startswith("fib_mismatch_i")

    def test_valid_100_fib_returns_empty(self) -> None:
        nums = [0, 1]
        for i in range(2, 100):
            nums.append(nums[i - 1] + nums[i - 2])
        content = ", ".join(str(n) for n in nums)
        state = self._make_state("fib.txt", content)
        assert _fibonacci_issue_from_state(state) == ""


class TestPrintTable(unittest.TestCase):
    def test_empty_rows_prints_no_runs_message(self) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_table([])
        assert "No checkpointed runs found." in buf.getvalue()

    def test_single_row_renders(self) -> None:
        summary = _make_summary()
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_table([summary])
        output = buf.getvalue()
        assert "run-1" in output
        assert "SUCCESS" in output
        assert "sort_array" in output

    def test_multiple_rows_renders(self) -> None:
        rows = [
            _make_summary(run_id="r1", status="SUCCESS"),
            _make_summary(run_id="r2", status="FAILED", issue_flags="invalid_json_retry"),
        ]
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_table(rows)
        output = buf.getvalue()
        assert "r1" in output
        assert "r2" in output
        assert "FAILED" in output


class TestWriteCsv(unittest.TestCase):
    def test_write_csv_creates_file(self) -> None:
        summary = _make_summary()
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/subdir/output.csv"
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _write_csv([summary], csv_path)
            assert Path(csv_path).exists()
            content = Path(csv_path).read_text()
            assert "run_id" in content
            assert "run-1" in content
            assert "SUCCESS" in content

    def test_write_csv_header_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = f"{tmp}/out.csv"
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _write_csv([_make_summary()], csv_path)
            lines = Path(csv_path).read_text().splitlines()
            header = lines[0]
            assert "tools_used_count" in header
            assert "issue_flags" in header
            assert "finalized_at" in header


class TestPrintRunDetails(unittest.TestCase):
    def test_run_id_not_found(self) -> None:
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_run_details("nonexistent", [], ":memory:")
        assert "not found" in buf.getvalue()

    def test_run_details_printed_with_tool_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/cp.db"
            store = SQLiteCheckpointStore(db)
            state = new_run_state("sys", "user", run_id="run-x")
            state["tool_history"] = [
                {
                    "call": 1,
                    "tool": "sort_array",
                    "args": {"items": [3, 1]},
                    "result": {"sorted": [1, 3]},
                }
            ]
            state["final_answer"] = "done"
            store.save(run_id="run-x", step=1, node_name="finalize", state=state)

            rows = summarize_runs(checkpoint_db_path=db, memo_db_path=f"{tmp}/missing.db")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _print_run_details("run-x", rows, db)
            output = buf.getvalue()
            assert "run-x" in output
            assert "sort_array" in output

    def test_run_details_no_tool_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/cp.db"
            store = SQLiteCheckpointStore(db)
            state = new_run_state("sys", "user", run_id="run-y")
            state["tool_history"] = []
            state["final_answer"] = "done"
            store.save(run_id="run-y", step=1, node_name="finalize", state=state)

            rows = summarize_runs(checkpoint_db_path=db, memo_db_path=f"{tmp}/missing.db")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _print_run_details("run-y", rows, db)
            output = buf.getvalue()
            assert "No tool history" in output

    def test_run_details_with_error_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/cp.db"
            store = SQLiteCheckpointStore(db)
            state = new_run_state("sys", "user", run_id="run-z")
            state["tool_history"] = [
                {
                    "call": 1,
                    "tool": "sort_array",
                    "args": {},
                    "result": {"error": "items required"},
                }
            ]
            state["final_answer"] = "done"
            store.save(run_id="run-z", step=1, node_name="finalize", state=state)

            rows = summarize_runs(checkpoint_db_path=db, memo_db_path=f"{tmp}/missing.db")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                _print_run_details("run-z", rows, db)
            output = buf.getvalue()
            assert "error" in output


class TestSummarizeRunsIssueFlags(unittest.TestCase):
    def test_duplicate_tool_retry_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/cp.db"
            store = SQLiteCheckpointStore(db)
            state = new_run_state("sys", "user", run_id="run-dup")
            state["retry_counts"]["duplicate_tool"] = 2
            state["final_answer"] = "done"
            store.save(run_id="run-dup", step=1, node_name="finalize", state=state)

            rows = summarize_runs(checkpoint_db_path=db, memo_db_path=f"{tmp}/m.db")
            by_id = {r.run_id: r for r in rows}
            assert "duplicate_tool_retry" in by_id["run-dup"].issue_flags


class TestMain(unittest.TestCase):
    def test_main_with_missing_dbs(self) -> None:
        """main() should run without crashing when dbs don't exist."""
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/cp.db"
            memo = f"{tmp}/m.db"
            csv_out = f"{tmp}/summary.csv"
            argv = ["run_audit", f"--checkpoint-db={db}", f"--memo-db={memo}", f"--csv-path={csv_out}"]
            buf = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdout", buf):
                main()
            assert "No checkpointed runs found." in buf.getvalue()
            assert Path(csv_out).exists()

    def test_main_with_run_id_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/cp.db"
            memo = f"{tmp}/m.db"
            csv_out = f"{tmp}/summary.csv"
            store = SQLiteCheckpointStore(db)
            state = new_run_state("sys", "user", run_id="my-run")
            state["final_answer"] = "done"
            state["tool_history"] = []
            store.save(run_id="my-run", step=1, node_name="finalize", state=state)

            argv = [
                "run_audit",
                f"--checkpoint-db={db}",
                f"--memo-db={memo}",
                f"--csv-path={csv_out}",
                "--run-id=my-run",
            ]
            buf = io.StringIO()
            with patch("sys.argv", argv), patch("sys.stdout", buf):
                main()
            output = buf.getvalue()
            assert "my-run" in output


if __name__ == "__main__":
    unittest.main()
