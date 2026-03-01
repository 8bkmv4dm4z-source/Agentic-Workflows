import tempfile
import unittest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.run_audit import summarize_runs
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state


class RunAuditTests(unittest.TestCase):
    def test_summarize_runs_success_and_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_db = f"{temp_dir}/checkpoints.db"
            memo_db = f"{temp_dir}/memo.db"
            checkpoints = SQLiteCheckpointStore(checkpoint_db)
            memos = SQLiteMemoStore(memo_db)

            success = new_run_state("sys", "user", run_id="run-success")
            success["step"] = 3
            success["tool_history"] = [
                {
                    "call": 1,
                    "tool": "repeat_message",
                    "args": {"message": "ok"},
                    "result": {"echo": "ok"},
                },
                {
                    "call": 2,
                    "tool": "sort_array",
                    "args": {"items": [2, 1]},
                    "result": {"sorted": [1, 2]},
                },
            ]
            success["retry_counts"]["invalid_json"] = 0
            success["retry_counts"]["duplicate_tool"] = 0
            success["retry_counts"]["memo_policy"] = 0
            success["final_answer"] = "done"
            checkpoints.save(run_id="run-success", step=0, node_name="init", state=success)
            checkpoints.save(run_id="run-success", step=3, node_name="finalize", state=success)
            memos.put(run_id="run-success", key="k1", value={"v": 1})

            failed = new_run_state("sys", "user", run_id="run-failed")
            failed["step"] = 2
            failed["retry_counts"]["invalid_json"] = 3
            failed["retry_counts"]["provider_timeout"] = 2
            failed["final_answer"] = "Planner failed to produce a valid JSON action."
            checkpoints.save(
                run_id="run-failed", step=2, node_name="plan_fail_closed", state=failed
            )

            rows = summarize_runs(checkpoint_db_path=checkpoint_db, memo_db_path=memo_db)
            by_id = {row.run_id: row for row in rows}

            self.assertEqual(by_id["run-success"].status, "SUCCESS")
            self.assertEqual(by_id["run-success"].memo_entry_count, 1)
            self.assertEqual(by_id["run-success"].tools_by_step, "1:repeat_message | 2:sort_array")
            self.assertEqual(by_id["run-success"].cache_reuse_hits, 0)
            self.assertEqual(by_id["run-failed"].status, "FAILED")
            self.assertGreaterEqual(by_id["run-failed"].invalid_json_retries, 1)
            self.assertEqual(by_id["run-failed"].provider_timeout_retries, 2)
            self.assertIn("provider_timeout_retry", by_id["run-failed"].issue_flags)

    def test_summarize_runs_flags_fib_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_db = f"{temp_dir}/checkpoints.db"
            checkpoints = SQLiteCheckpointStore(checkpoint_db)

            state = new_run_state("sys", "user", run_id="run-fib")
            state["step"] = 4
            state["tool_history"] = [
                {
                    "call": 1,
                    "tool": "write_file",
                    "args": {"path": "fib.txt", "content": "0, 1, 1, 2, 3, 5, 110, 114"},
                    "result": {"result": "wrote"},
                }
            ]
            state["final_answer"] = "done"
            checkpoints.save(run_id="run-fib", step=4, node_name="finalize", state=state)

            rows = summarize_runs(
                checkpoint_db_path=checkpoint_db, memo_db_path=f"{temp_dir}/missing_memo.db"
            )
            self.assertEqual(len(rows), 1)
            self.assertIn("fib_len_", rows[0].issue_flags)


if __name__ == "__main__":
    unittest.main()
