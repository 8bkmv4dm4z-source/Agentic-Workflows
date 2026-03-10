from __future__ import annotations

"""CLI entrypoint for a quick Phase 1 LangGraph run demonstration."""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable
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

from agentic_workflows.observability import flush as flush_observability
from agentic_workflows.observability import observe
from agentic_workflows.orchestration.langgraph.langgraph_orchestrator import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.reviewer import (
    FailOnlyReviewer,
    ReviewDecision,
    WeightedReviewer,
)
from agentic_workflows.orchestration.langgraph.run_ui import (
    build_verify_gate_outcome,
    collect_retry_counts,
    extract_notable_events,
    render_execution_summary_panel,
    render_notable_events_panel,
    render_verify_gate_panel,
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

    # Routing & Fallback section
    sh = audit_report.get("structural_health", {})
    routing = sh.get("routing_decisions", {})
    fallback_count = sh.get("cloud_fallback_count", 0)
    local_failures = sh.get("local_model_failures", {})
    if routing or fallback_count or local_failures:
        print(f"\n  Routing & Fallback:")
        if routing:
            print(f"    Routing: strong={routing.get('strong', 0)} fast={routing.get('fast', 0)}")
        if fallback_count:
            print(f"    Cloud fallbacks: {fallback_count}")
        if local_failures and (local_failures.get('timeout', 0) or local_failures.get('parse', 0)):
            print(f"    Local failures: timeout={local_failures.get('timeout', 0)} parse={local_failures.get('parse', 0)}")

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


def _print_run_ui_panels(result: dict[str, Any]) -> None:
    """Print lightweight run summary panels for rerun review."""
    mission_reports_raw = result.get("mission_report", [])
    mission_reports = mission_reports_raw if isinstance(mission_reports_raw, list) else []
    tools_used_raw = result.get("tools_used", [])
    tools_used = tools_used_raw if isinstance(tools_used_raw, list) else []
    changed_files = _derive_changed_files(result)
    retry_counts = collect_retry_counts(result)
    print(
        render_execution_summary_panel(
            mission_count=len(mission_reports),
            changed_files=changed_files,
            tool_count=len(tools_used),
            retry_counts=retry_counts,
        )
    )
    print(
        render_notable_events_panel(
            extract_notable_events(
                result,
                retry_counts=retry_counts,
            )
        )
    )
    print(render_verify_gate_panel(build_verify_gate_outcome(result, retry_counts=retry_counts)))


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
    unmet = _normalize_unmet_requirements(
        unmet_requirements=selected.unmet_requirements,
        mission_ids=selected.rerun_mission_ids,
    )
    if unmet:
        print("  unmet_requirements:", unmet)
    print("CHANGED FILES:", ", ".join(selected.changed_files) if selected.changed_files else "<none>")


def _mission_reports_by_id(
    mission_reports: list[dict[str, Any]],
    ids: list[int],
) -> list[dict[str, Any]]:
    wanted = {mission_id for mission_id in ids if mission_id > 0}
    if not wanted:
        return []
    return [report for report in mission_reports if report.get("mission_id") in wanted]


def _normalize_unmet_requirements(
    unmet_requirements: dict[int, dict[str, list[str]]] | None,
    mission_ids: list[int],
) -> dict[int, dict[str, list[str]]]:
    if not isinstance(unmet_requirements, dict):
        return {}
    wanted = {mission_id for mission_id in mission_ids if mission_id > 0}
    if not wanted:
        return {}
    normalized: dict[int, dict[str, list[str]]] = {}
    for mission_id in wanted:
        entry = unmet_requirements.get(mission_id, {})
        if not isinstance(entry, dict):
            continue
        missing_tools = entry.get("missing_tools", [])
        missing_files = entry.get("missing_files", [])
        normalized[mission_id] = {
            "missing_tools": [str(item) for item in missing_tools],
            "missing_files": [str(item) for item in missing_files],
        }
    return normalized


def _build_rerun_context(
    *,
    rerun_mission_ids: list[int],
    unmet_requirements: dict[int, dict[str, list[str]]] | None,
) -> dict[str, Any]:
    return {
        "target_mission_ids": [mission_id for mission_id in rerun_mission_ids if mission_id > 0],
        "unmet_requirements": _normalize_unmet_requirements(
            unmet_requirements=unmet_requirements,
            mission_ids=rerun_mission_ids,
        ),
    }


def _apply_reviewer_decision(
    *,
    orchestrator: LangGraphOrchestrator,
    original_input: str,
    result: dict[str, Any],
    decision: ReviewDecision,
    requirement_refinement: str = "",
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
    re_run_input = _build_rerun_input(
        rerun_missions,
        original_input,
        requirement_refinement=requirement_refinement,
        unmet_requirements=_normalize_unmet_requirements(
            unmet_requirements=decision.unmet_requirements,
            mission_ids=decision.rerun_mission_ids,
        ),
    )
    rerun_context = _build_rerun_context(
        rerun_mission_ids=decision.rerun_mission_ids,
        unmet_requirements=decision.unmet_requirements,
    )
    print(f"\nRe-running {len(rerun_missions)} mission(s)…\n")
    new_result = orchestrator.run(re_run_input, rerun_context=rerun_context)
    _print_run_ui_panels(new_result)
    _print_audit_panel(new_result.get("audit_report"), new_result.get("mission_report", []))
    _save_audit(new_result)


def _collect_mandatory_rerun_refinement(
    *,
    input_fn: Callable[[], str] = input,
    print_fn: Callable[..., None] = print,
) -> tuple[str, bool]:
    """Collect mandatory rerun acceptance criteria.

    Returns (criteria_text, confirmed). If the user cancels, confirmed=False.
    """
    print()
    print_fn("Rerun acceptance criteria is required before executing a rerun.")
    print_fn("Enter concise criteria, or type 's' to save and exit without rerun.")
    while True:
        print_fn("> ", end="", flush=True)
        try:
            candidate = input_fn().strip()
        except (EOFError, KeyboardInterrupt):
            return "", False
        if candidate.lower() in {"s", "save", "skip", "cancel", "q", "quit"}:
            return "", False
        if candidate:
            print_fn("RERUN_CRITERIA_CONFIRMED")
            return candidate, True
        print_fn("Acceptance criteria cannot be empty.")


def _append_requirement_refinement(user_input: str, requirement_refinement: str) -> str:
    """Append rerun acceptance criteria to a full-pipeline rerun prompt."""
    refinement = requirement_refinement.strip()
    if not refinement:
        return user_input
    return (
        f"{user_input.rstrip()}\n\n"
        "Rerun requirement refinements (strict acceptance criteria):\n"
        f"{refinement}"
    )


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

    rerun_refinement = ""
    criteria_confirmed = False
    if selected_decision.action == "rerun":
        rerun_refinement, criteria_confirmed = _collect_mandatory_rerun_refinement()
        if not criteria_confirmed:
            print("Rerun cancelled. Saving audit and exiting.")
            _save_audit(result)
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
        if selected_decision.action == "rerun" and not criteria_confirmed:
            rerun_refinement, criteria_confirmed = _collect_mandatory_rerun_refinement()
            if not criteria_confirmed:
                print("Rerun cancelled. Saving audit and exiting.")
                _save_audit(result)
                return
        _apply_reviewer_decision(
            orchestrator=orchestrator,
            original_input=original_input,
            result=result,
            decision=selected_decision,
            requirement_refinement=rerun_refinement,
        )
    elif choice == "r":
        if not criteria_confirmed:
            rerun_refinement, criteria_confirmed = _collect_mandatory_rerun_refinement()
            if not criteria_confirmed:
                print("Rerun cancelled. Saving audit and exiting.")
                _save_audit(result)
                return
        failed_missions = _get_failed_missions(audit_report, result.get("mission_report", []))
        if not failed_missions:
            print("No failed missions to re-run.")
            _save_audit(result)
            return
        re_run_input = _build_rerun_input(
            failed_missions,
            original_input,
            requirement_refinement=rerun_refinement,
            unmet_requirements=_normalize_unmet_requirements(
                unmet_requirements=selected_decision.unmet_requirements,
                mission_ids=[int(mission.get("mission_id", 0)) for mission in failed_missions],
            ),
        )
        rerun_context = _build_rerun_context(
            rerun_mission_ids=[int(mission.get("mission_id", 0)) for mission in failed_missions],
            unmet_requirements=selected_decision.unmet_requirements,
        )
        print(f"\nRe-running {len(failed_missions)} mission(s)…\n")
        new_result = orchestrator.run(re_run_input, rerun_context=rerun_context)
        _print_run_ui_panels(new_result)
        _print_audit_panel(new_result.get("audit_report"), new_result.get("mission_report", []))
        _save_audit(new_result)
    elif choice == "a":
        if not criteria_confirmed:
            rerun_refinement, criteria_confirmed = _collect_mandatory_rerun_refinement()
            if not criteria_confirmed:
                print("Rerun cancelled. Saving audit and exiting.")
                _save_audit(result)
                return
        print("\nRe-running full pipeline…\n")
        refined_input = _append_requirement_refinement(original_input, rerun_refinement)
        new_result = orchestrator.run(refined_input)
        _print_run_ui_panels(new_result)
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


def _build_rerun_input(
    failed_missions: list[dict[str, Any]],
    original_input: str = "",
    *,
    requirement_refinement: str = "",
    unmet_requirements: dict[int, dict[str, list[str]]] | None = None,
) -> str:
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
    refinement = requirement_refinement.strip()
    if refinement:
        lines.extend(
            [
                "Rerun requirement refinements (strict acceptance criteria):",
                refinement,
                "",
            ]
        )
    if unmet_requirements:
        lines.append("Reviewer unresolved requirements by mission:")
        for mission_id in sorted(unmet_requirements):
            entry = unmet_requirements[mission_id]
            missing_tools = entry.get("missing_tools", [])
            missing_files = entry.get("missing_files", [])
            lines.append(
                f"- mission {mission_id}: "
                f"missing_tools={missing_tools} missing_files={missing_files}"
            )
        lines.append("")
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


def _default_demo_input() -> str:
    """Return the default deterministic multi-task demo prompt."""
    return """Return exactly one JSON object per turn.
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


def _mission_success_from_result(result: dict[str, Any]) -> tuple[int, int, float]:
    """Return (succeeded_missions, total_missions, rate) using fail findings as denominator."""
    mission_report_raw = result.get("mission_report", [])
    mission_reports = mission_report_raw if isinstance(mission_report_raw, list) else []
    if not mission_reports:
        return (0, 0, 0.0)

    mission_ids: list[int] = []
    for index, mission in enumerate(mission_reports):
        if not isinstance(mission, dict):
            continue
        mission_id = mission.get("mission_id")
        mission_ids.append(mission_id if isinstance(mission_id, int) and mission_id > 0 else index + 1)
    if not mission_ids:
        return (0, 0, 0.0)

    fail_ids: set[int] = set()
    audit_report = result.get("audit_report", {})
    if isinstance(audit_report, dict):
        findings = audit_report.get("findings", [])
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict):
                    continue
                if str(finding.get("level", "")).lower() != "fail":
                    continue
                mission_id = finding.get("mission_id")
                if isinstance(mission_id, int) and mission_id > 0:
                    fail_ids.add(mission_id)

    succeeded = sum(1 for mission_id in mission_ids if mission_id not in fail_ids)
    total = len(mission_ids)
    return (succeeded, total, (succeeded / total) if total else 0.0)


def _extract_fail_mission_ids(audit_report: dict[str, Any] | None) -> list[int]:
    """Return sorted mission IDs with fail-level findings."""
    if not isinstance(audit_report, dict):
        return []
    findings = audit_report.get("findings", [])
    if not isinstance(findings, list):
        return []
    fail_ids: set[int] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        if str(finding.get("level", "")).lower() != "fail":
            continue
        mission_id = finding.get("mission_id")
        if isinstance(mission_id, int) and mission_id > 0:
            fail_ids.add(mission_id)
    return sorted(fail_ids)


def _collect_fork_attempt_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    """Capture normalized per-attempt metrics used by fork-test artifacts."""
    retry_counts = collect_retry_counts(result)
    verify_gate = build_verify_gate_outcome(result, retry_counts=retry_counts)
    succeeded, total, success_rate = _mission_success_from_result(result)
    audit_report = result.get("audit_report", {})
    audit = audit_report if isinstance(audit_report, dict) else {}
    return {
        "run_id": str(result.get("run_id", "")),
        "verify_status": str(verify_gate.get("status", "fail")).upper(),
        "verify_failed_checks": [
            str(item) for item in verify_gate.get("failed_checks", [])
        ],
        "mission_succeeded": succeeded,
        "mission_total": total,
        "mission_success_rate": success_rate,
        "audit_passed": int(audit.get("passed", 0)),
        "audit_warned": int(audit.get("warned", 0)),
        "audit_failed": int(audit.get("failed", 0)),
        "retry_counts": retry_counts,
        "answer": str(result.get("answer", "")),
        "fail_mission_ids": _extract_fail_mission_ids(audit),
    }


def _write_fork_test_artifact(
    *,
    artifact_path: Path,
    run_index: int,
    attempts: list[dict[str, Any]],
    rerun_triggered: bool,
    rerun_reason: str,
) -> None:
    """Write one run artifact for fork-test mode."""
    if not attempts:
        return
    initial_attempt = attempts[0]
    final_attempt = attempts[-1]
    lines = [
        f"RUN_INDEX: {run_index}",
        f"RUN_ID: {final_attempt.get('run_id', '')}",
        f"VERIFY_GATE: {final_attempt.get('verify_status', 'FAIL')}",
        f"VERIFY_FAILED_CHECKS: {final_attempt.get('verify_failed_checks', [])}",
        "MISSION_SUCCESS: "
        f"{final_attempt.get('mission_succeeded', 0)}/{final_attempt.get('mission_total', 0)} "
        f"({float(final_attempt.get('mission_success_rate', 0.0)) * 100:.2f}%)",
        "AUDIT_COUNTS: "
        f"passed={final_attempt.get('audit_passed', 0)} "
        f"warned={final_attempt.get('audit_warned', 0)} "
        f"failed={final_attempt.get('audit_failed', 0)}",
        f"RETRIES: {json.dumps(final_attempt.get('retry_counts', {}), sort_keys=True)}",
        f"ANSWER: {final_attempt.get('answer', '')}",
        f"ATTEMPTS_TOTAL: {len(attempts)}",
        f"RERUN_TRIGGERED: {rerun_triggered}",
        f"RERUN_REASON: {rerun_reason}",
        f"INITIAL_VERIFY_GATE: {initial_attempt.get('verify_status', 'FAIL')}",
        f"INITIAL_VERIFY_FAILED_CHECKS: {initial_attempt.get('verify_failed_checks', [])}",
        f"INITIAL_FAIL_MISSIONS: {initial_attempt.get('fail_mission_ids', [])}",
        f"FINAL_FAIL_MISSIONS: {final_attempt.get('fail_mission_ids', [])}",
    ]
    for attempt_index, attempt in enumerate(attempts, start=1):
        lines.extend(
            [
                f"ATTEMPT_{attempt_index}_RUN_ID: {attempt.get('run_id', '')}",
                f"ATTEMPT_{attempt_index}_VERIFY_GATE: {attempt.get('verify_status', 'FAIL')}",
                f"ATTEMPT_{attempt_index}_FAILED_CHECKS: {attempt.get('verify_failed_checks', [])}",
                "ATTEMPT_"
                f"{attempt_index}_MISSION_SUCCESS: "
                f"{attempt.get('mission_succeeded', 0)}/{attempt.get('mission_total', 0)}",
                "ATTEMPT_"
                f"{attempt_index}_AUDIT_COUNTS: "
                f"passed={attempt.get('audit_passed', 0)} "
                f"warned={attempt.get('audit_warned', 0)} "
                f"failed={attempt.get('audit_failed', 0)}",
                "ATTEMPT_"
                f"{attempt_index}_RETRIES: "
                f"{json.dumps(attempt.get('retry_counts', {}), sort_keys=True)}",
                f"ATTEMPT_{attempt_index}_FAIL_MISSIONS: {attempt.get('fail_mission_ids', [])}",
            ]
        )
    artifact_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_fork_test_batch(
    *,
    orchestrator: LangGraphOrchestrator,
    user_input: str,
    runs: int,
    output_dir: Path,
    prefix: str,
    rerun_max: int = 1,
    rerun_on: str = "fail_only",
) -> dict[str, Any]:
    """Run N executions and persist per-run artifacts plus summary statistics."""
    output_dir.mkdir(parents=True, exist_ok=True)
    initial_pass_count = 0
    final_pass_count = 0
    rerun_runs = 0
    artifacts: list[Path] = []

    for run_index in range(1, runs + 1):
        attempts: list[dict[str, Any]] = []
        rerun_triggered = False
        rerun_reason = "none"
        remaining_reruns = max(0, rerun_max)

        latest_result = orchestrator.run(user_input)
        attempts.append(_collect_fork_attempt_snapshot(latest_result))
        initial_status = str(attempts[0].get("verify_status", "FAIL")).upper()
        if initial_status == "PASS":
            initial_pass_count += 1

        while rerun_on == "fail_only" and remaining_reruns > 0:
            fail_ids = [int(item) for item in attempts[-1].get("fail_mission_ids", [])]
            if not fail_ids:
                break
            mission_report_raw = latest_result.get("mission_report", [])
            mission_report = mission_report_raw if isinstance(mission_report_raw, list) else []
            rerun_missions = _mission_reports_by_id(mission_report, fail_ids)
            if not rerun_missions:
                break
            rerun_triggered = True
            rerun_reason = "fail_findings_present"
            rerun_input = _build_rerun_input(rerun_missions, user_input)
            rerun_context = _build_rerun_context(
                rerun_mission_ids=fail_ids,
                unmet_requirements=None,
            )
            latest_result = orchestrator.run(rerun_input, rerun_context=rerun_context)
            attempts.append(_collect_fork_attempt_snapshot(latest_result))
            remaining_reruns -= 1

        final_status = str(attempts[-1].get("verify_status", "FAIL")).upper()
        if final_status == "PASS":
            final_pass_count += 1
        if rerun_triggered:
            rerun_runs += 1

        artifact_path = output_dir / f"{prefix}{run_index}.txt"
        _write_fork_test_artifact(
            artifact_path=artifact_path,
            run_index=run_index,
            attempts=attempts,
            rerun_triggered=rerun_triggered,
            rerun_reason=rerun_reason,
        )
        artifacts.append(artifact_path)
        print(
            f"[fork-test] run={run_index}/{runs} file={artifact_path.name} "
            f"initial={initial_status} final={final_status} attempts={len(attempts)}"
        )

    success_rate = (final_pass_count / runs) if runs > 0 else 0.0
    initial_success_rate = (initial_pass_count / runs) if runs > 0 else 0.0
    pass_lift = final_pass_count - initial_pass_count
    summary_path = output_dir / f"{prefix}_summary.txt"
    summary_lines = [
        f"TOTAL_RUNS: {runs}",
        f"INITIAL_PASS_RUNS: {initial_pass_count}",
        f"FINAL_PASS_RUNS: {final_pass_count}",
        f"RUNS_WITH_RERUN: {rerun_runs}",
        f"PASS_LIFT_FROM_RERUN: {pass_lift}",
        f"INITIAL_VERIFY_SUCCESS_RATE: {initial_success_rate * 100:.2f}%",
        f"VERIFY_PASS_RUNS: {final_pass_count}",
        f"VERIFY_SUCCESS_RATE: {success_rate * 100:.2f}%",
        "ARTIFACT_FILES:",
    ]
    summary_lines.extend(f"- {path.name}" for path in artifacts)
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(
        f"[fork-test] success={final_pass_count}/{runs} ({success_rate * 100:.2f}%) "
        f"initial={initial_pass_count}/{runs} rerun_runs={rerun_runs} summary={summary_path.name}"
    )
    return {
        "total_runs": runs,
        "initial_verify_passes": initial_pass_count,
        "verify_passes": final_pass_count,
        "verify_success_rate": success_rate,
        "initial_verify_success_rate": initial_success_rate,
        "runs_with_rerun": rerun_runs,
        "pass_lift_from_rerun": pass_lift,
        "artifact_files": [str(path) for path in artifacts],
        "summary_file": str(summary_path),
    }


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
    parser.add_argument(
        "--fork-test-runs",
        type=int,
        default=0,
        help="Run the demo N times and write per-run files (<prefix>1.txt..N.txt).",
    )
    parser.add_argument(
        "--fork-test-prefix",
        default="test",
        help="Prefix for fork-test output files (default: test).",
    )
    parser.add_argument(
        "--fork-test-dir",
        default=".",
        help="Output directory for fork-test artifacts.",
    )
    parser.add_argument(
        "--fork-test-rerun-max",
        type=int,
        default=1,
        help="Max targeted reruns per fork test run (default: 1).",
    )
    parser.add_argument(
        "--fork-test-rerun-on",
        choices=["fail_only", "none"],
        default="fail_only",
        help="Fork-test rerun trigger policy (default: fail_only).",
    )
    return parser.parse_args(argv)


def _build_orchestrator() -> tuple[LangGraphOrchestrator, Any]:
    """Construct orchestrator with MissionContextStore + EmbeddingProvider if DATABASE_URL is set.

    Returns (orchestrator, pool) — caller must close pool when done (pool may be None).
    """
    db_url = os.getenv("DATABASE_URL")
    pool = None
    embedding_provider = None
    mission_context_store = None
    artifact_store = None

    if db_url:
        try:
            from psycopg_pool import (
                ConnectionPool as PgConnectionPool,  # type: ignore[import-untyped]
            )

            from agentic_workflows.context.embedding_provider import get_embedding_provider
            from agentic_workflows.storage.mission_context_store import MissionContextStore

            pool = PgConnectionPool(
                conninfo=db_url,
                min_size=2,
                max_size=10,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            pool.open(wait=True)
            embedding_provider = get_embedding_provider()
            mission_context_store = MissionContextStore(pool=pool, embedding_provider=embedding_provider)
            from agentic_workflows.storage.artifact_store import ArtifactStore
            artifact_store = ArtifactStore(pool=pool, embedding_provider=embedding_provider)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Could not connect to Postgres — running without vector memory: {exc}")
            pool = None
            artifact_store = None

    fallback_provider = None
    if os.getenv("GROQ_API_KEY"):
        try:
            from agentic_workflows.orchestration.langgraph.provider import GroqChatProvider
            fallback_provider = GroqChatProvider()
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] Could not create Groq fallback provider: {exc}")

    return LangGraphOrchestrator(
        embedding_provider=embedding_provider,
        mission_context_store=mission_context_store,
        artifact_store=artifact_store,
        fallback_provider=fallback_provider,
    ), pool


@observe(name="run")
def main() -> None:
    args = _parse_args()
    env_mode = os.getenv("P1_REVIEWER_MODE")
    reviewer_mode = _normalize_reviewer_mode(args.reviewer_mode or env_mode)
    prefer_mode = _normalize_prefer_mode(args.prefer)
    # This prompt intentionally exercises multiple deterministic tools.
    orchestrator, _pg_pool = _build_orchestrator()
    user_input = _default_demo_input()
    try:
        if args.fork_test_runs > 0:
            _run_fork_test_batch(
                orchestrator=orchestrator,
                user_input=user_input,
                runs=args.fork_test_runs,
                output_dir=Path(args.fork_test_dir),
                prefix=args.fork_test_prefix,
                rerun_max=max(0, int(args.fork_test_rerun_max)),
                rerun_on=str(args.fork_test_rerun_on),
            )
            return
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
        _print_run_ui_panels(result)

        # Audit review
        _print_audit_panel(result.get("audit_report"), result.get("mission_report", []))
        _correction_loop(
            orchestrator,
            user_input,
            result,
            reviewer_mode=reviewer_mode,
            prefer_mode=prefer_mode,
        )
    finally:
        flush_observability()
        if _pg_pool is not None:
            import contextlib
            with contextlib.suppress(Exception):
                _pg_pool.close()


if __name__ == "__main__":
    main()
