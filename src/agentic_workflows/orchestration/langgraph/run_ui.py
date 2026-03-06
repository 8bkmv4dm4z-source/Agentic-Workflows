from __future__ import annotations

"""Lightweight terminal UI helpers for run summaries and notable events."""

from typing import Any

_RETRY_ORDER = (
    "invalid_json",
    "provider_timeout",
    "memo_policy",
    "duplicate_tool",
    "content_validation",
    "finish_rejected",
)


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def collect_retry_counts(result: dict[str, Any]) -> dict[str, int]:
    """Collect retry counters from derived snapshot with state fallback."""
    derived_raw = result.get("derived_snapshot", {})
    derived = derived_raw if isinstance(derived_raw, dict) else {}
    state_raw = result.get("state", {})
    state = state_raw if isinstance(state_raw, dict) else {}
    retries_raw = state.get("retry_counts", {})
    retries = retries_raw if isinstance(retries_raw, dict) else {}

    return {
        "invalid_json": _coerce_int(
            derived.get("invalid_json_retries", retries.get("invalid_json", 0))
        ),
        "provider_timeout": _coerce_int(
            derived.get("provider_timeout_retries", retries.get("provider_timeout", 0))
        ),
        "memo_policy": _coerce_int(derived.get("memo_policy_retries", retries.get("memo_policy", 0))),
        "duplicate_tool": _coerce_int(
            derived.get("duplicate_tool_retries", retries.get("duplicate_tool", 0))
        ),
        "content_validation": _coerce_int(
            derived.get("content_validation_retries", retries.get("content_validation", 0))
        ),
        "finish_rejected": _coerce_int(
            derived.get("finish_rejections", retries.get("finish_rejected", 0))
        ),
    }


def render_execution_summary_panel(
    *,
    mission_count: int,
    changed_files: list[str],
    tool_count: int,
    retry_counts: dict[str, int],
) -> str:
    """Render a compact execution summary panel."""
    sep = "=" * 60
    listed_files = ", ".join(changed_files) if changed_files else "<none>"
    total_retries = sum(max(0, count) for count in retry_counts.values())
    retry_parts = [
        f"{name}={max(0, retry_counts.get(name, 0))}"
        for name in _RETRY_ORDER
        if max(0, retry_counts.get(name, 0)) > 0
    ]
    retry_text = ", ".join(retry_parts) if retry_parts else "<none>"
    lines = [
        sep,
        " EXECUTION SUMMARY",
        sep,
        f" missions: {max(0, mission_count)}",
        f" changed_files ({len(changed_files)}): {listed_files}",
        f" tool_count: {max(0, tool_count)}",
        f" retries: total={total_retries} details={retry_text}",
        sep,
    ]
    return "\n".join(lines)


def build_verify_gate_outcome(
    result: dict[str, Any],
    *,
    retry_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Build deterministic Execute→Verify gate outcome for CLI presentation."""
    retries = retry_counts if retry_counts is not None else collect_retry_counts(result)
    mission_reports_raw = result.get("mission_report", [])
    mission_reports = mission_reports_raw if isinstance(mission_reports_raw, list) else []
    audit_raw = result.get("audit_report", {})
    audit = audit_raw if isinstance(audit_raw, dict) else {}
    audit_failed = _coerce_int(audit.get("failed", 0))
    completed = sum(
        1
        for report in mission_reports
        if str(report.get("status", "")).strip().lower() == "completed"
    )
    total = len(mission_reports)
    checks = {
        "missions_completed": (completed == total) if total > 0 else False,
        "audit_no_failures": audit_failed == 0,
        "finish_rejections_clear": _coerce_int(retries.get("finish_rejected", 0)) == 0,
    }
    failed_checks = [name for name, ok in checks.items() if not ok]
    status = "pass" if not failed_checks else "fail"
    return {
        "status": status,
        "failed_checks": failed_checks,
        "checks": checks,
        "completed_missions": completed,
        "total_missions": total,
    }


def render_verify_gate_panel(verify_gate: dict[str, Any]) -> str:
    """Render Execute→Verify gate panel used before rerun/finalize decisions."""
    sep = "=" * 60
    status = str(verify_gate.get("status", "fail")).upper()
    checks = verify_gate.get("checks", {})
    failed_checks = verify_gate.get("failed_checks", [])
    completed = _coerce_int(verify_gate.get("completed_missions", 0))
    total = _coerce_int(verify_gate.get("total_missions", 0))
    lines = [sep, f" VERIFY GATE [{status}]", sep]
    lines.append(f" mission_completion: {completed}/{total}")
    if isinstance(checks, dict):
        for name in ("missions_completed", "audit_no_failures", "finish_rejections_clear"):
            lines.append(f" - {name}: {'ok' if bool(checks.get(name, False)) else 'fail'}")
    if isinstance(failed_checks, list) and failed_checks:
        lines.append(f" failed_checks: {failed_checks}")
    lines.append(sep)
    return "\n".join(lines)


def extract_notable_events(
    result: dict[str, Any],
    *,
    retry_counts: dict[str, int] | None = None,
) -> list[str]:
    """Extract a deterministic list of notable events from result artifacts."""
    retries = retry_counts if retry_counts is not None else collect_retry_counts(result)
    events: list[str] = []

    audit_raw = result.get("audit_report")
    audit = audit_raw if isinstance(audit_raw, dict) else {}
    findings_raw = audit.get("findings", [])
    findings = findings_raw if isinstance(findings_raw, list) else []
    fail_count = 0
    warn_count = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        level = str(finding.get("level", "")).strip().lower()
        if level == "fail":
            fail_count += 1
        elif level == "warn":
            warn_count += 1
    if fail_count or warn_count:
        events.append(f"audit findings: fail={fail_count}, warn={warn_count}")

    if retries.get("finish_rejected", 0) > 0:
        events.append(f"finish rejections: {retries['finish_rejected']}")
    if retries.get("duplicate_tool", 0) > 0:
        events.append(f"duplicate retries: {retries['duplicate_tool']}")
    if retries.get("content_validation", 0) > 0:
        events.append(f"content validation retries: {retries['content_validation']}")

    state_raw = result.get("state", {})
    state_dict = state_raw if isinstance(state_raw, dict) else {}
    if state_dict.get("context_clear_requested"):
        events.append("context cleared")
    answer_str = str(result.get("answer", ""))
    if answer_str.startswith("__CLARIFY__:"):
        events.append("clarify action emitted")

    return events


def render_notable_events_panel(events: list[str]) -> str:
    """Render notable event lines inside a panel."""
    sep = "=" * 60
    lines = [sep, " NOTABLE EVENTS", sep]
    if events:
        for event in events:
            lines.append(f" - {event}")
    else:
        lines.append(" - <none>")
    lines.append(sep)
    return "\n".join(lines)


def collect_pipeline_trace(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract pipeline trace events from run result state."""
    state_raw = result.get("state", {})
    state = state_raw if isinstance(state_raw, dict) else {}
    policy_flags = state.get("policy_flags", {})
    trace_raw = policy_flags.get("pipeline_trace", [])
    return [e for e in trace_raw if isinstance(e, dict)]


_SPECIALIST_COLORS = {
    "executor": "\033[36m",   # cyan
    "evaluator": "\033[33m",  # yellow
    "supervisor": "\033[35m", # magenta
}
_COLOR_RESET = "\033[0m"


def render_specialist_routing(
    *,
    specialist: str,
    tool: str,
    mission_id: int,
    status: str = "executing",
) -> None:
    """Print a live routing line showing specialist→tool assignment."""
    color = _SPECIALIST_COLORS.get(specialist.lower(), "")
    label = specialist.upper()
    print(f"{color}→ [{label:10s}]  {tool:<25s}  mission={mission_id}  status={status}{_COLOR_RESET}")


def render_mission_status_panel(mission_reports: list[dict[str, Any]]) -> str:
    """Render a summary panel showing per-mission completion status."""
    # Deduplicate by mission_id — keep last occurrence (most up-to-date status).
    seen: dict[Any, dict[str, Any]] = {}
    for report in mission_reports:
        seen[report.get("mission_id", "?")] = report
    deduped = list(seen.values())

    # Content width: "│ " + icon(1) + " " + id(3) + " " + text(26) + suffix(8) + " │"
    # = 2 + 1 + 1 + 3 + 1 + 26 + 8 + 2 = 44 total display width
    header = "Mission Status"
    inner_width = 42  # chars between the two border │ chars
    dashes_top = "─" * (inner_width - len(header) - 2)  # "─ " + header + " " + dashes
    sep_top = f"┌─ {header} {dashes_top}┐"
    sep_bot = "└" + "─" * inner_width + "┘"
    lines = [sep_top]
    for report in deduped:
        mid = report.get("mission_id", "?")
        mission_text = str(report.get("mission", ""))[:26]
        status = str(report.get("status", "")).strip().lower()
        if status == "completed":
            icon = "+"
            suffix = ""
        elif status == "failed":
            icon = "x"
            suffix = "  [fail]"
        else:
            icon = "-"
            suffix = f"  [{status[:4]}]"
        lines.append(f"│ {icon} {mid!s:<3} {mission_text:<26}{suffix:<8} │")
    lines.append(sep_bot)
    return "\n".join(lines)


def render_pipeline_trace_panel(trace_events: list[dict[str, Any]]) -> str:
    """Render a vertical pipeline trace panel showing every stage transition."""
    sep = "=" * 60
    lines = [sep, " PIPELINE TRACE", sep]
    if not trace_events:
        lines.append(" <no trace events>")
        lines.append(sep)
        return "\n".join(lines)

    _STAGE_LABELS = {
        "parser": "PARSER",
        "planner_output": "PLANNER",
        "planner_retry": "RETRY",
        "specialist_route": "SPECIALIST",
        "tool_exec": "TOOL",
        "validator_fail": "VALIDATOR FAIL",
        "validator_pass": "VALIDATOR OK",
        "mission_complete": "MISSION DONE",
        "loop_state": "LOOP",
    }

    for event in trace_events:
        stage = str(event.get("stage", "?"))
        step = event.get("step", "?")
        label = _STAGE_LABELS.get(stage, stage.upper())

        if stage == "parser":
            detail = (
                f"method={event.get('method', '?')} "
                f"steps={event.get('step_count', 0)} "
                f"flat={event.get('flat_count', 0)}"
            )
        elif stage == "planner_output":
            detail = (
                f"src={event.get('source', '?')} "
                f"action={event.get('action_type', '?')} "
                f"tool={event.get('tool_name', '')} "
                f"mission={event.get('mission_id', 0)}"
            )
        elif stage == "planner_retry":
            detail = f"reason={event.get('reason', '?')} retry={event.get('retry_count', 0)}"
        elif stage == "specialist_route":
            detail = (
                f"specialist={event.get('specialist', '?')} "
                f"tool={event.get('tool_name', '')} "
                f"mission={event.get('mission_id', 0)}"
            )
        elif stage == "tool_exec":
            err = " ERR" if event.get("has_error") else ""
            detail = (
                f"tool={event.get('tool', '?')}{err} "
                f"keys={event.get('result_keys', [])} "
                f"mission={event.get('mission_id', 0)}"
            )
        elif stage == "validator_fail":
            detail = (
                f"tool={event.get('tool', '?')} "
                f"retry={event.get('retry_count', 0)} "
                f"reason={str(event.get('reason', ''))[:60]}"
            )
        elif stage == "validator_pass":
            detail = f"tool={event.get('tool', '?')} check={event.get('check', 'none')}"
        elif stage == "mission_complete":
            detail = (
                f"mission={event.get('mission_id', 0)} "
                f"preview={event.get('mission_preview', '')[:50]}"
            )
        elif stage == "loop_state":
            detail = (
                f"step={event.get('step', 0)} "
                f"queue={event.get('queue_depth', 0)} "
                f"done={event.get('completed_count', 0)}/{event.get('total_count', 0)} "
                f"timeout={event.get('timeout_mode', False)}"
            )
        else:
            detail = str({k: v for k, v in event.items() if k not in ("stage", "step")})[:80]

        lines.append(f" [{label:14s}] step={step!s:>3}  {detail}")

    lines.append(sep)
    return "\n".join(lines)


def _word_wrap(text: str, width: int) -> list[str]:
    """Wrap text into lines of at most `width` chars, breaking at word boundaries."""
    words = text.split()
    result: list[str] = []
    current = ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            result.append(current)
            current = word
    if current:
        result.append(current)
    return result or [""]


def render_clarification_panel(question: str, missing: list[str]) -> str:
    """Render a styled clarification request panel with word-wrapped question."""
    _CYAN = "\033[36m"
    _BOLD = "\033[1m"
    _RESET = "\033[0m"
    width = 60
    inner = width - 4  # "│ " + content + " │" — 2 chars each side

    # Wrap at inner-3 so "Q: " prefix and "   " continuation indent both fit.
    q_lines = _word_wrap(question, inner - 3)

    # Top border: "┌─ Clarification Needed " + dashes + "┐"
    header = "Clarification Needed"
    dashes_top = "─" * (inner - len(header))
    lines = [f"{_CYAN}┌─ {header} {dashes_top}┐{_RESET}"]

    # First question line with "Q: " prefix
    first_line = f"Q: {q_lines[0]}"
    lines.append(f"{_CYAN}│{_RESET} {_BOLD}{first_line:<{inner}}{_RESET} {_CYAN}│{_RESET}")
    # Continuation lines indented to align with first line text
    for cont in q_lines[1:]:
        padded = f"   {cont}"
        lines.append(f"{_CYAN}│{_RESET} {padded:<{inner}} {_CYAN}│{_RESET}")

    # Blank separator line
    lines.append(f"{_CYAN}│{_RESET} {' ' * inner} {_CYAN}│{_RESET}")

    if missing:
        lines.append(f"{_CYAN}│{_RESET} {'Missing:':<{inner}} {_CYAN}│{_RESET}")
        for item in missing[:4]:
            bullet = f"  • {item}"
            lines.append(f"{_CYAN}│{_RESET} {bullet:<{inner}} {_CYAN}│{_RESET}")

    lines.append(f"{_CYAN}└{'─' * (width - 2)}┘{_RESET}")
    return "\n".join(lines)


def render_context_warning_panel(scope: str, budget_used: int, budget_total: int) -> str:
    """Render a context reset warning panel."""
    _YELLOW = "\033[33m"
    _RESET = "\033[0m"
    used_k = budget_used // 1000
    total_k = budget_total // 1000
    return (
        f"{_YELLOW}\u26a0  Context Reset \u2014 scope: {scope} | Used: {used_k}k / {total_k}k tokens{_RESET}\n"
        f"   Previous mission summaries retained in session."
    )


def render_stuck_indicator(rejection_count: int, max_rejections: int) -> str:
    """Render an inline stuck-loop warning."""
    _RED = "\033[31m"
    _RESET = "\033[0m"
    return f"{_RED}\u27f3 Planner retrying ({rejection_count}/{max_rejections}) \u2014 mission still pending{_RESET}"
