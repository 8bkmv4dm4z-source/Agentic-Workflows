from __future__ import annotations

"""CLI entrypoint for a quick Phase 1 LangGraph run demonstration."""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

# Allow running this file directly while still supporting package execution:
#   python -m agentic_workflows.orchestration.langgraph.run
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[4]
    src_root = repo_root / "src"
    for p in (str(repo_root), str(src_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

from agentic_workflows.orchestration.langgraph.langgraph_orchestrator import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.reviewer import (
    FailOnlyReviewer,
    ReviewDecision,
    WeightedReviewer,
)

# ---------------------------------------------------------------------------
# Audit review panel
# ---------------------------------------------------------------------------

_LEVEL_ICON = {"pass": "✓", "warn": "⚠", "fail": "✗"}
_VALID_REVIEWER_MODES = {"fail_only", "weighted", "both"}
_VALID_PREFERENCE_MODES = {"fail_only", "weighted"}


def _print_audit_panel(
    audit_report: dict[str, Any] | None,
    mission_reports: list[dict[str, Any]],
) -> None:
    """Print a structured audit review panel to stdout."""
    if audit_report is None:
        print("\nNo audit report available.")
        return

    run_id = audit_report.get("run_id", "unknown")
    passed = audit_report.get("passed", 0)
    warned = audit_report.get("warned", 0)
    failed = audit_report.get("failed", 0)
    findings: list[dict[str, Any]] = audit_report.get("findings", [])

    total_missions = len(mission_reports)
    # Missions that had no fail/warn findings
    clean_ids: set[int] = set()
    problem_ids: set[int] = set()
    for f in findings:
        mid = f.get("mission_id", 0)
        if f.get("level") in ("warn", "fail"):
            problem_ids.add(mid)
        elif f.get("level") == "pass":
            clean_ids.add(mid)

    clean_count = len(clean_ids - problem_ids)

    sep = "═" * 60
    print(f"\n{sep}")
    print(f" AUDIT REVIEW — Run {run_id[:8]} | {total_missions} missions | {clean_count}/{total_missions} clean")
    print(sep)
    print()

    # Group findings by mission
    by_mission: dict[int, list[dict[str, Any]]] = {}
    for f in findings:
        mid = f.get("mission_id", 0)
        by_mission.setdefault(mid, []).append(f)

    for report in mission_reports:
        mid = report.get("mission_id", 0)
        mission_text = report.get("mission", "")
        # Truncate long mission text
        short_mission = mission_text[:60] + ("…" if len(mission_text) > 60 else "")

        mission_findings = by_mission.get(mid, [])
        non_pass = [f for f in mission_findings if f.get("level") in ("warn", "fail")]

        if non_pass:
            worst = "fail" if any(f.get("level") == "fail" for f in non_pass) else "warn"
            icon = _LEVEL_ICON[worst]
            print(f" {icon}  Mission {mid} — {short_mission}")
            for f in non_pass:
                level_tag = f.get("level", "?").upper()
                check = f.get("check", "?")
                detail = f.get("detail", "")
                print(f"    [{level_tag}] {check}: {detail}")
        else:
            print(f" {_LEVEL_ICON['pass']}  Mission {mid} — {short_mission}")

    print()
    print(sep)
    summary_parts = []
    if passed:
        summary_parts.append(f"{passed} passed")
    if warned:
        summary_parts.append(f"{warned} warned")
    if failed:
        summary_parts.append(f"{failed} failed")
    print(" " + ", ".join(summary_parts))
    print(sep)


def _normalize_reviewer_mode(mode: str | None) -> str:
    """Resolve reviewer mode from CLI/env/default."""
    candidate = (mode or "").strip().lower()
    if candidate not in _VALID_REVIEWER_MODES:
        return "fail_only"
    return candidate


def _normalize_prefer_mode(mode: str | None) -> str:
    """Resolve preferred reviewer when mode=both."""
    candidate = (mode or "").strip().lower()
    if candidate not in _VALID_PREFERENCE_MODES:
        return "fail_only"
    return candidate


def _derive_changed_files(result: dict[str, Any]) -> list[str]:
    """Derive changed files from mission reports + tool results."""
    changed: set[str] = set()
    mission_report = result.get("mission_report", [])
    if isinstance(mission_report, list):
        for mission in mission_report:
            if not isinstance(mission, dict):
                continue
            written_files = mission.get("written_files", [])
            if isinstance(written_files, list):
                for path in written_files:
                    basename = str(path).replace("\\", "/").rsplit("/", 1)[-1]
                    if basename:
                        changed.add(basename)
            tool_results = mission.get("tool_results", [])
            if isinstance(tool_results, list):
                for record in tool_results:
                    if not isinstance(record, dict) or record.get("tool") != "write_file":
                        continue
                    tool_result = record.get("result", {})
                    if not isinstance(tool_result, dict) or "error" in tool_result:
                        continue
                    maybe_path = str(tool_result.get("path", "")).strip()
                    basename = maybe_path.replace("\\", "/").rsplit("/", 1)[-1]
                    if basename:
                        changed.add(basename)
    tools_used = result.get("tools_used", [])
    if isinstance(tools_used, list):
        for item in tools_used:
            if not isinstance(item, dict):
                continue
            if str(item.get("tool", "")).strip() != "write_file":
                continue
            tool_result = item.get("result", {})
            if not isinstance(tool_result, dict) or "error" in tool_result:
                continue
            maybe_path = str(tool_result.get("path", "")).strip()
            basename = maybe_path.replace("\\", "/").rsplit("/", 1)[-1]
            if basename:
                changed.add(basename)
    return sorted(changed)


def _get_reviewer_decisions(
    *,
    reviewer_mode: str,
    prefer_mode: str,
    result: dict[str, Any],
) -> tuple[ReviewDecision, dict[str, ReviewDecision], str]:
    """Evaluate configured reviewer(s) and select active decision."""
    audit_report = result.get("audit_report")
    mission_report_raw = result.get("mission_report", [])
    mission_report = mission_report_raw if isinstance(mission_report_raw, list) else []
    derived_raw = result.get("derived_snapshot", {})
    derived_snapshot = derived_raw if isinstance(derived_raw, dict) else {}
    changed_files = _derive_changed_files(result)
    decisions: dict[str, ReviewDecision] = {}
    fail_only = FailOnlyReviewer().decide(
        audit_report=audit_report,
        mission_reports=mission_report,
        derived_snapshot=derived_snapshot,
        changed_files=changed_files,
    )
    weighted = WeightedReviewer().decide(
        audit_report=audit_report,
        mission_reports=mission_report,
        derived_snapshot=derived_snapshot,
        changed_files=changed_files,
    )
    if reviewer_mode == "fail_only":
        decisions["fail_only"] = fail_only
        return fail_only, decisions, "fail_only"
    if reviewer_mode == "weighted":
        decisions["weighted"] = weighted
        return weighted, decisions, "weighted"
    decisions["fail_only"] = fail_only
    decisions["weighted"] = weighted
    selected_mode = prefer_mode if fail_only.action != weighted.action else "fail_only"
    selected = decisions[selected_mode]
    return selected, decisions, selected_mode


def _print_reviewer_decisions(
    *,
    reviewer_mode: str,
    selected_mode: str,
    selected: ReviewDecision,
    decisions: dict[str, ReviewDecision],
) -> None:
    """Render reviewer decision summary."""
    print("REVIEWER MODE:", reviewer_mode)
    if reviewer_mode == "both":
        fail_only = decisions["fail_only"]
        weighted = decisions["weighted"]
        print(
            "  fail_only:",
            fail_only.action.upper(),
            "| rerun_missions=",
            fail_only.rerun_mission_ids,
        )
        print(
            "  weighted:",
            weighted.action.upper(),
            "| score=",
            weighted.weighted_score,
            "| rerun_missions=",
            weighted.rerun_mission_ids,
        )
    print(
        "REVIEWER DECISION:",
        f"selected={selected_mode}",
        f"action={selected.action}",
        f"rerun_missions={selected.rerun_mission_ids}",
    )
    if selected.reasons:
        print("  reason:", selected.reasons[0])
    print("CHANGED FILES:", ", ".join(selected.changed_files) if selected.changed_files else "<none>")


def _mission_reports_by_id(
    mission_reports: list[dict[str, Any]],
    ids: list[int],
) -> list[dict[str, Any]]:
    wanted = {mission_id for mission_id in ids if mission_id > 0}
    if not wanted:
        return []
    return [report for report in mission_reports if report.get("mission_id") in wanted]


def _apply_reviewer_decision(
    *,
    orchestrator: LangGraphOrchestrator,
    original_input: str,
    result: dict[str, Any],
    decision: ReviewDecision,
) -> None:
    """Apply reviewer decision by rerunning selected missions or ending."""
    mission_report_raw = result.get("mission_report", [])
    mission_report = mission_report_raw if isinstance(mission_report_raw, list) else []
    if decision.action != "rerun":
        _save_audit(result)
        return
    rerun_missions = _mission_reports_by_id(mission_report, decision.rerun_mission_ids)
    if not rerun_missions:
        print("Reviewer requested rerun but no missions were selected. Saving and exiting.")
        _save_audit(result)
        return
    re_run_input = _build_rerun_input(rerun_missions, original_input)
    print(f"\nRe-running {len(rerun_missions)} mission(s)…\n")
    new_result = orchestrator.run(re_run_input)
    _print_audit_panel(new_result.get("audit_report"), new_result.get("mission_report", []))
    _save_audit(new_result)


def _correction_loop(
    orchestrator: LangGraphOrchestrator,
    original_input: str,
    result: dict[str, Any],
    *,
    reviewer_mode: str,
    prefer_mode: str,
) -> None:
    """Interactive correction loop shown after audit panel.

    In non-interactive mode (piped/CI), auto-saves and exits.
    """
    audit_report = result.get("audit_report")
    selected_decision, all_decisions, selected_mode = _get_reviewer_decisions(
        reviewer_mode=reviewer_mode,
        prefer_mode=prefer_mode,
        result=result,
    )
    _print_reviewer_decisions(
        reviewer_mode=reviewer_mode,
        selected_mode=selected_mode,
        selected=selected_decision,
        decisions=all_decisions,
    )
    is_tty = sys.stdin.isatty()

    if not is_tty:
        _apply_reviewer_decision(
            orchestrator=orchestrator,
            original_input=original_input,
            result=result,
            decision=selected_decision,
        )
        return

    print()
    print(" Options:")
    print("   [d] Apply reviewer decision  (default)")
    print("   [r] Re-run failed missions only")
    print("   [a] Re-run full pipeline")
    print("   [s] Save audit report and exit")
    print("   [q] Quit without saving")
    print(
        f" Reviewer recommends: {selected_decision.action.upper()} "
        f"missions={selected_decision.rerun_mission_ids}"
    )
    print("> ", end="", flush=True)

    try:
        choice = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        choice = "d"

    if choice in {"", "d"}:
        _apply_reviewer_decision(
            orchestrator=orchestrator,
            original_input=original_input,
            result=result,
            decision=selected_decision,
        )
    elif choice == "r":
        failed_missions = _get_failed_missions(audit_report, result.get("mission_report", []))
        if not failed_missions:
            print("No failed missions to re-run.")
            _save_audit(result)
            return
        re_run_input = _build_rerun_input(failed_missions, original_input)
        print(f"\nRe-running {len(failed_missions)} mission(s)…\n")
        new_result = orchestrator.run(re_run_input)
        _print_audit_panel(new_result.get("audit_report"), new_result.get("mission_report", []))
        _save_audit(new_result)
    elif choice == "a":
        print("\nRe-running full pipeline…\n")
        new_result = orchestrator.run(original_input)
        _print_audit_panel(new_result.get("audit_report"), new_result.get("mission_report", []))
        _save_audit(new_result)
    elif choice == "q":
        print("Exiting without saving.")
    else:
        _save_audit(result)


def _get_failed_missions(
    audit_report: dict[str, Any] | None,
    mission_reports: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return mission_report dicts for missions that had fail findings."""
    if not audit_report:
        return []
    bad_ids: set[int] = {
        f["mission_id"]
        for f in audit_report.get("findings", [])
        if f.get("level") == "fail"
    }
    return [r for r in mission_reports if r.get("mission_id") in bad_ids]


def _build_rerun_input(failed_missions: list[dict[str, Any]], original_input: str = "") -> str:
    """Build a minimal user prompt that re-runs the given missions.

    Extracts the full task block from original_input when available so that
    all sub-task context (lists, JSON, text samples) is preserved.
    """
    lines = [
        "Return exactly one JSON object per turn.",
        "No XML tags, no markdown, and no prose outside JSON.",
        'Use only these action schemas:',
        '{"action":"tool","tool_name":"...","args":{...}}',
        '{"action":"finish","answer":"..."}',
        "",
        "Please re-run these tasks:",
        "",
    ]
    for r in failed_missions:
        mid = r.get("mission_id", "?")
        # Try to extract the full task block from the original input
        block: str | None = None
        if original_input and mid != "?":
            pattern = rf"Task\s+{mid}\s*:.*?(?=Task\s+\d+\s*:|$)"
            m = re.search(pattern, original_input, re.DOTALL | re.IGNORECASE)
            if m:
                block = m.group(0).strip()
        if block:
            lines.append(block)
        else:
            # Fallback: use mission title, avoiding double prefix
            mission_text = r.get("mission", "")
            if not re.match(r"Task\s+\d+", mission_text, re.IGNORECASE):
                mission_text = f"Task {mid}: {mission_text}"
            lines.append(mission_text)
    lines.append("")
    lines.append("After completing all tasks, emit finish with a summary.")
    return "\n".join(lines)


def _save_audit(result: dict[str, Any]) -> None:
    """Write audit summary to lastRun.txt."""
    audit = result.get("audit_report")
    if not audit:
        return
    append_enabled = str(os.getenv("P1_APPEND_LASTRUN", "0")).strip().lower()
    if append_enabled not in {"1", "true", "yes", "on"}:
        return
    findings: list[dict[str, Any]] = audit.get("findings", [])
    lines = [
        f"AUDIT REPORT (run {audit.get('run_id', 'unknown')[:8]}):",
    ]
    for f in findings:
        if f.get("level") != "pass":
            lines.append(
                f"  mission {f['mission_id']}: "
                f"{f['level'].upper()} {f['check']} — {f['detail']}"
            )
    lines.append(
        f"  {audit.get('passed', 0)} passed, "
        f"{audit.get('warned', 0)} warned, "
        f"{audit.get('failed', 0)} failed"
    )
    try:
        with open("lastRun.txt", "a", encoding="utf-8") as fh:
            fh.write("\n" + "\n".join(lines) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LangGraph demo with optional reviewer policies.")
    parser.add_argument(
        "--reviewer-mode",
        choices=sorted(_VALID_REVIEWER_MODES),
        default=None,
        help="Reviewer policy mode to decide rerun vs end.",
    )
    parser.add_argument(
        "--prefer",
        choices=sorted(_VALID_PREFERENCE_MODES),
        default="fail_only",
        help="Preferred mode when --reviewer-mode=both and decisions diverge.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = _parse_args()
    env_mode = os.getenv("P1_REVIEWER_MODE")
    reviewer_mode = _normalize_reviewer_mode(args.reviewer_mode or env_mode)
    prefer_mode = _normalize_prefer_mode(args.prefer)
    # This prompt intentionally exercises multiple deterministic tools.
    orchestrator = LangGraphOrchestrator()
    user_input = """Return exactly one JSON object per turn.
No XML tags, no markdown, and no prose outside JSON.
Use only these action schemas:
{"action":"tool","tool_name":"...","args":{...}}
{"action":"finish","answer":"..."}

Please complete these 5 tasks in order, one at a time.
Each task may have sub-tasks (1a, 1b, etc.) — complete them sequentially.

Task 1: Text Analysis Pipeline
  1a. Analyze this text for word count, sentence count, and key terms: "The quick brown fox jumps over the lazy dog. The dog barked loudly at the fox. Meanwhile, the brown cat watched from the fence."
  1b. Uppercase the following key terms and write them to analysis_results.txt: "fox, dog, brown"

Task 2: Data Analysis and Sorting
  2a. Analyze these numbers for summary statistics and outliers: [45, 23, 67, 12, 89, 34, 56, 78, 91, 150, 2, 33]
  2b. Sort the non-outlier values in descending order
  2c. Calculate the mean of the sorted non-outlier array

Task 3: JSON Processing
  3a. Parse and validate this JSON: '{"users":[{"name":"Alice","score":95},{"name":"Bob","score":82},{"name":"Charlie","score":91}]}'
  3b. Extract all user names using regex from: "Alice scored 95, Bob scored 82, Charlie scored 91"
  3c. Sort the names alphabetically, then write them to users_sorted.txt

Task 4: Pattern Matching and Transform
  4a. Use regex to extract all numbers from: "Order #123 has 5 items at $45.99 each, totaling $229.95 with 10% discount"
  4b. Calculate the sum and mean of the extracted numbers
  4c. Write a summary of extracted numbers and their stats to pattern_report.txt

Task 5: Fibonacci with Analysis
  5a. Write the first 50 fibonacci numbers to fib50.txt
  5b. Repeat the final summary as confirmation: "All 5 tasks completed successfully"

After completing all tasks, emit finish with a summary."""
    result = orchestrator.run(user_input)
    # Run-level summary with mission and memo visibility for debugging.
    print("RUN ID:", result["run_id"])
    print("TOOLS USED:")
    for item in result["tools_used"]:
        print(f"  #{item['call']} {item['tool']} {item['result']}")
    print("MISSION REPORT:")
    for mission in result.get("mission_report", []):
        print(
            f"  mission {mission.get('mission_id')}: [{', '.join(mission.get('used_tools', []))}] "
            f"+ result={mission.get('result', '')}"
        )
    print("MEMO STORE ENTRIES:")
    for entry in result.get("memo_store_entries", []):
        print(
            "  "
            f"key={entry.get('key')} hash={entry.get('value_hash')} "
            f"source_tool={entry.get('source_tool')} step={entry.get('step')}"
        )
    print("DERIVED SNAPSHOT:", result.get("derived_snapshot", {}))
    print("ANSWER:", result["answer"])

    # Audit review
    _print_audit_panel(result.get("audit_report"), result.get("mission_report", []))
    _correction_loop(
        orchestrator,
        user_input,
        result,
        reviewer_mode=reviewer_mode,
        prefer_mode=prefer_mode,
    )


if __name__ == "__main__":
    main()
