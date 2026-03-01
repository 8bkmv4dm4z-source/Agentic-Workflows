from __future__ import annotations

"""Run-audit CLI for Phase 1 LangGraph executions.

This utility reads checkpointed run state snapshots and emits a concise
terminal table plus a CSV export for longitudinal tracking.
"""

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CHECKPOINT_DB = ".tmp/langgraph_checkpoints.db"
DEFAULT_MEMO_DB = ".tmp/memo_store.db"
DEFAULT_CSV_PATH = ".tmp/run_summary.csv"


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    step_count: int
    tools_used_count: int
    tools_by_step: str
    memo_entry_count: int
    invalid_json_retries: int
    duplicate_tool_retries: int
    memo_policy_retries: int
    provider_timeout_retries: int
    content_validation_retries: int
    memo_retrieve_hits: int
    memo_retrieve_misses: int
    cache_reuse_hits: int
    cache_reuse_misses: int
    issue_flags: str
    finalized_at: str


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_memo_counts(memo_db_path: str) -> dict[str, int]:
    memo_db = Path(memo_db_path)
    if not memo_db.exists():
        return {}
    with _connect(memo_db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_id, COUNT(*) AS count
            FROM memo_entries
            GROUP BY run_id
            """
        ).fetchall()
    return {str(row["run_id"]): int(row["count"]) for row in rows}


def _load_latest_states(checkpoint_db_path: str) -> list[dict[str, Any]]:
    checkpoint_db = Path(checkpoint_db_path)
    if not checkpoint_db.exists():
        return []
    with _connect(checkpoint_db_path) as conn:
        rows = conn.execute(
            """
            SELECT gc.run_id, gc.step, gc.node_name, gc.state_json, gc.created_at
            FROM graph_checkpoints gc
            JOIN (
                SELECT run_id, MAX(id) AS max_id
                FROM graph_checkpoints
                GROUP BY run_id
            ) latest
            ON gc.id = latest.max_id
            ORDER BY gc.created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _status_from_state(node_name: str, final_answer: str) -> str:
    if node_name != "finalize":
        return "FAILED"
    answer = final_answer.strip()
    if not answer:
        return "FAILED"
    lowered = answer.lower()
    if "planner failed" in lowered or "run failed" in lowered:
        return "FAILED"
    return "SUCCESS"


def _tools_by_step(state: dict[str, Any]) -> tuple[str, int]:
    history = state.get("tool_history", [])
    if not history:
        return ("", 0)
    chunks: list[str] = []
    for item in history:
        call = int(item.get("call", 0))
        tool = str(item.get("tool", ""))
        if call > 0 and tool:
            chunks.append(f"{call}:{tool}")
    return (" | ".join(chunks), len(history))


def _parse_csv_int_list(content: str) -> list[int] | None:
    tokens = [token.strip() for token in content.split(",") if token.strip()]
    if not tokens:
        return []
    numbers: list[int] = []
    for token in tokens:
        if not token.lstrip("-").isdigit():
            return None
        numbers.append(int(token))
    return numbers


def _fibonacci_issue_from_state(state: dict[str, Any]) -> str:
    history = state.get("tool_history", [])
    for item in history:
        if str(item.get("tool", "")) != "write_file":
            continue
        args = dict(item.get("args", {}))
        path = str(args.get("path", "")).lower()
        if "fib" not in path:
            continue
        content = str(args.get("content", ""))
        numbers = _parse_csv_int_list(content)
        if numbers is None:
            return "fib_non_integer_tokens"
        if len(numbers) != 100:
            return f"fib_len_{len(numbers)}"
        if len(numbers) >= 2 and (numbers[0] != 0 or numbers[1] != 1):
            return "fib_bad_prefix"
        for index in range(2, len(numbers)):
            if numbers[index] != numbers[index - 1] + numbers[index - 2]:
                return f"fib_mismatch_i{index}"
    return ""


def summarize_runs(
    *,
    checkpoint_db_path: str = DEFAULT_CHECKPOINT_DB,
    memo_db_path: str = DEFAULT_MEMO_DB,
) -> list[RunSummary]:
    memo_counts = _load_memo_counts(memo_db_path)
    latest_rows = _load_latest_states(checkpoint_db_path)
    summaries: list[RunSummary] = []

    for row in latest_rows:
        state = json.loads(str(row["state_json"]))
        run_id = str(row["run_id"])
        tools_str, tools_count = _tools_by_step(state)
        retries = dict(state.get("retry_counts", {}))
        policy_flags = dict(state.get("policy_flags", {}))
        final_answer = str(state.get("final_answer", ""))
        issue_flags: list[str] = []
        fib_issue = _fibonacci_issue_from_state(state)
        if fib_issue:
            issue_flags.append(fib_issue)
        if retries.get("invalid_json", 0):
            issue_flags.append("invalid_json_retry")
        if retries.get("provider_timeout", 0):
            issue_flags.append("provider_timeout_retry")
        if retries.get("duplicate_tool", 0):
            issue_flags.append("duplicate_tool_retry")

        summaries.append(
            RunSummary(
                run_id=run_id,
                status=_status_from_state(str(row["node_name"]), final_answer),
                step_count=int(state.get("step", row.get("step", 0))),
                tools_used_count=tools_count,
                tools_by_step=tools_str,
                memo_entry_count=int(memo_counts.get(run_id, 0)),
                invalid_json_retries=int(retries.get("invalid_json", 0)),
                duplicate_tool_retries=int(retries.get("duplicate_tool", 0)),
                memo_policy_retries=int(retries.get("memo_policy", 0)),
                provider_timeout_retries=int(retries.get("provider_timeout", 0)),
                content_validation_retries=int(retries.get("content_validation", 0)),
                memo_retrieve_hits=int(policy_flags.get("memo_retrieve_hits", 0)),
                memo_retrieve_misses=int(policy_flags.get("memo_retrieve_misses", 0)),
                cache_reuse_hits=int(policy_flags.get("cache_reuse_hits", 0)),
                cache_reuse_misses=int(policy_flags.get("cache_reuse_misses", 0)),
                issue_flags=",".join(issue_flags),
                finalized_at=str(row["created_at"]),
            )
        )

    return summaries


def _print_table(rows: list[RunSummary]) -> None:
    if not rows:
        print("No checkpointed runs found.")
        return

    headers = [
        "run_id",
        "status",
        "step_count",
        "tools_used",
        "memo_count",
        "invalid_json",
        "dup_tool",
        "memo_policy",
        "provider_timeout",
        "content_validation",
        "memo_hit",
        "memo_miss",
        "cache_hit",
        "cache_miss",
        "issue_flags",
        "tools_by_step",
    ]
    data: list[list[str]] = []
    for row in rows:
        data.append(
            [
                row.run_id,
                row.status,
                str(row.step_count),
                str(row.tools_used_count),
                str(row.memo_entry_count),
                str(row.invalid_json_retries),
                str(row.duplicate_tool_retries),
                str(row.memo_policy_retries),
                str(row.provider_timeout_retries),
                str(row.content_validation_retries),
                str(row.memo_retrieve_hits),
                str(row.memo_retrieve_misses),
                str(row.cache_reuse_hits),
                str(row.cache_reuse_misses),
                row.issue_flags,
                row.tools_by_step,
            ]
        )

    widths = [len(header) for header in headers]
    for record in data:
        for idx, cell in enumerate(record):
            widths[idx] = max(widths[idx], len(cell))

    def render_line(parts: list[str]) -> str:
        return " | ".join(part.ljust(widths[idx]) for idx, part in enumerate(parts))

    print(render_line(headers))
    print("-+-".join("-" * width for width in widths))
    for record in data:
        print(render_line(record))


def _write_csv(rows: list[RunSummary], csv_path: str) -> None:
    output = Path(csv_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "run_id",
                "status",
                "step_count",
                "tools_used_count",
                "tools_by_step",
                "memo_entry_count",
                "invalid_json_retries",
                "duplicate_tool_retries",
                "memo_policy_retries",
                "provider_timeout_retries",
                "content_validation_retries",
                "memo_retrieve_hits",
                "memo_retrieve_misses",
                "cache_reuse_hits",
                "cache_reuse_misses",
                "issue_flags",
                "finalized_at",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.run_id,
                    row.status,
                    row.step_count,
                    row.tools_used_count,
                    row.tools_by_step,
                    row.memo_entry_count,
                    row.invalid_json_retries,
                    row.duplicate_tool_retries,
                    row.memo_policy_retries,
                    row.provider_timeout_retries,
                    row.content_validation_retries,
                    row.memo_retrieve_hits,
                    row.memo_retrieve_misses,
                    row.cache_reuse_hits,
                    row.cache_reuse_misses,
                    row.issue_flags,
                    row.finalized_at,
                ]
            )
    print(f"Wrote CSV summary to {output}")


def _print_run_details(run_id: str, rows: list[RunSummary], checkpoint_db_path: str) -> None:
    target = next((row for row in rows if row.run_id == run_id), None)
    if target is None:
        print(f"Run id '{run_id}' not found.")
        return
    print(f"\nRun detail: {run_id}")
    print(f"status={target.status} steps={target.step_count} memo={target.memo_entry_count}")
    print(f"provider_timeout_retries={target.provider_timeout_retries}")
    print(
        f"memo_retrieve_hits={target.memo_retrieve_hits} memo_retrieve_misses={target.memo_retrieve_misses}"
    )
    print(
        f"cache_reuse_hits={target.cache_reuse_hits} cache_reuse_misses={target.cache_reuse_misses}"
    )
    print(f"issues={target.issue_flags or 'none'}")

    with _connect(checkpoint_db_path) as conn:
        row = conn.execute(
            """
            SELECT state_json
            FROM graph_checkpoints
            WHERE run_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return
    state = json.loads(str(row["state_json"]))
    history = state.get("tool_history", [])
    if not history:
        print("No tool history for this run.")
        return

    print("tool steps:")
    for item in history:
        call = int(item.get("call", 0))
        tool = str(item.get("tool", ""))
        result = dict(item.get("result", {}))
        step_status = "error" if "error" in result else "ok"
        print(f"  #{call} tool={tool} status={step_status}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize LangGraph runs from checkpoint DB.")
    parser.add_argument(
        "--checkpoint-db", default=DEFAULT_CHECKPOINT_DB, help="Path to checkpoint sqlite db"
    )
    parser.add_argument("--memo-db", default=DEFAULT_MEMO_DB, help="Path to memo sqlite db")
    parser.add_argument("--csv-path", default=DEFAULT_CSV_PATH, help="Output CSV path")
    parser.add_argument(
        "--run-id", default="", help="Optional run id to print detailed tool step table"
    )
    args = parser.parse_args()

    rows = summarize_runs(checkpoint_db_path=args.checkpoint_db, memo_db_path=args.memo_db)
    _print_table(rows)
    _write_csv(rows, args.csv_path)
    if args.run_id:
        _print_run_details(args.run_id, rows, args.checkpoint_db)


if __name__ == "__main__":
    main()
