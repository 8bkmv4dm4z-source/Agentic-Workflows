"""API-client entrypoint for conversational agent sessions.

Usage:
    python -m agentic_workflows.cli.user_run [--debug]

Connects to the FastAPI service (default http://localhost:8000).
If the server is not running, auto-starts uvicorn in the background.
SSE events are rendered with Rich terminal formatting.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel

from agentic_workflows.logger import get_logger

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
_TMP_DIR = Path(os.environ.get("TMP_DIR", ".tmp"))

_log = get_logger("cli.user_run")

console = Console()

# Tools that represent data-access / data-query operations
_DATA_ACCESS_TOOLS = frozenset({
    "read_file",
    "write_file",
    "data_analysis",
    "sort_array",
    "run_bash",
    "search_files",
    "http_request",
    "hash_content",
})

_DEBUG = False


def _render_data_access_panel(tools_used: list[dict]) -> None:
    """Render a Rich panel summarising data-access tool calls from tool_history."""
    hits = [t for t in tools_used if isinstance(t, dict) and t.get("tool") in _DATA_ACCESS_TOOLS]
    if not hits:
        return
    lines = []
    for entry in hits:
        tool = entry.get("tool", "?")
        args = entry.get("args", {})
        result = entry.get("result", "")
        # Build a short arg summary — show "path" or "query" key if present, else first key
        arg_summary = ""
        if isinstance(args, dict):
            for key in ("path", "query", "command", "url", "content"):
                if key in args:
                    arg_summary = f"{key}={str(args[key])[:60]}"
                    break
            if not arg_summary and args:
                first_key = next(iter(args))
                arg_summary = f"{first_key}={str(args[first_key])[:60]}"
        result_str = str(result)[:120] if result else "(no output)"
        lines.append(f"[bold]{tool}[/]({arg_summary})\n  -> {result_str}")
    body = "\n".join(lines)
    console.print(Panel(body, title=f"Data Access ({len(hits)} calls)", style="bold magenta"))


def _write_run_report(run_id: str, result: dict[str, Any]) -> None:
    """Write a compact run report to .tmp/p2_latest_run.log (overwrite each run)."""
    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"RUN_ID: {run_id}"]

    mission_reports = result.get("mission_report", [])
    lines.append(f"MISSIONS: {len(mission_reports)}")
    for report in mission_reports:
        if not isinstance(report, dict):
            continue
        mid = report.get("mission_id", "?")
        tools = ", ".join(str(t) for t in report.get("used_tools", [])) or "none"
        result_text = str(report.get("result", ""))[:200]
        lines.append(f"  Mission {mid} [tools={tools}]: {result_text}")

    audit = result.get("audit_report")
    if isinstance(audit, dict):
        passed = audit.get("passed", 0)
        warned = audit.get("warned", 0)
        failed = audit.get("failed", 0)
        lines.append(f"AUDIT: passed={passed} warned={warned} failed={failed}")
        for finding in audit.get("findings", []):
            if not isinstance(finding, dict):
                continue
            level = finding.get("level", "?")
            if level != "pass":
                lines.append(
                    f"  [{level.upper()}] mission={finding.get('mission_id')} "
                    f"{finding.get('check')}: {finding.get('detail')}"
                )

    # Routing & fallback stats
    if isinstance(audit, dict):
        sh = audit.get("structural_health", {})
        routing = sh.get("routing_decisions", {})
        fallback_count = sh.get("cloud_fallback_count", 0)
        local_failures = sh.get("local_model_failures", {})
        if routing or fallback_count:
            lines.append(f"ROUTING: strong={routing.get('strong', 0)} fast={routing.get('fast', 0)}")
        if fallback_count:
            lines.append(f"CLOUD_FALLBACK: {fallback_count} event(s)")
        if local_failures and (local_failures.get('timeout', 0) or local_failures.get('parse', 0)):
            lines.append(f"LOCAL_FAILURES: timeout={local_failures.get('timeout', 0)} parse={local_failures.get('parse', 0)}")

    tools_used_list = result.get("tools_used", [])
    data_hits = [t for t in tools_used_list if isinstance(t, dict) and t.get("tool") in _DATA_ACCESS_TOOLS]
    if data_hits:
        lines.append(f"DATA_ACCESS: {len(data_hits)} call(s)")
        for entry in data_hits:
            tool = entry.get("tool", "?")
            result_snippet = str(entry.get("result", ""))[:100]
            lines.append(f"  {tool}: {result_snippet}")

    answer = result.get("answer", "")
    lines.append(f"ANSWER: {str(answer)[:500]}")

    (_TMP_DIR / "p2_latest_run.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_server_running() -> None:
    """Check if the API server is reachable; auto-start uvicorn if not."""
    for attempt in range(6):
        try:
            _health_headers: dict[str, str] = {}
            _health_api_key = os.environ.get("API_KEY")
            if _health_api_key:
                _health_headers["X-API-Key"] = _health_api_key
            resp = httpx.get(f"{API_BASE_URL}/health", timeout=2.0, headers=_health_headers)
            if resp.status_code == 200:
                return
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError):
            pass

        if attempt == 0:
            console.print("[yellow]API server not running, starting uvicorn...[/]")
            host = os.environ.get("API_HOST", "0.0.0.0")
            port = os.environ.get("API_PORT", "8000")
            _TMP_DIR.mkdir(parents=True, exist_ok=True)
            _server_log_fh = open(_TMP_DIR / "server_logs.txt", "a")  # noqa: SIM115
            env = {**os.environ, "GSD_LOG_DIR": str(_TMP_DIR)}
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "agentic_workflows.api.app:app",
                    "--host",
                    host,
                    "--port",
                    port,
                    "--log-level",
                    "info",
                ],
                start_new_session=True,
                stdout=_server_log_fh,
                stderr=_server_log_fh,
                env=env,
            )

        if attempt < 5:
            time.sleep(1)

    raise RuntimeError(
        f"Could not connect to API server at {API_BASE_URL} after 5 retries. "
        "Check server logs or start manually with: "
        "python -m uvicorn agentic_workflows.api.app:app"
    )


def _render_event(event: dict[str, Any]) -> None:
    """Render a single SSE event with Rich formatting."""
    event_type = event.get("type", "")
    tier = event.get("tier", "ui")

    # Debug-tier events only shown when debug mode is active
    if tier == "debug" and not _DEBUG:
        return

    if event_type == "node_start":
        node = event.get("node", "unknown")
        model = event.get("model")
        label = f">>> {node}" + (f" (model: {model})" if model else "")
        console.print(f"[bold blue]{label}[/]")

    elif event_type == "node_end":
        node = event.get("node", "unknown")
        console.print(f"[green]  completed: {node}[/]")

    elif event_type == "run_complete":
        result = event.get("result", {})

        # Answer panel
        answer = result.get("answer", "")
        if answer:
            console.print(Panel(str(answer), title="Answer", style="bold cyan"))

        # Mission report panels
        reports = result.get("mission_report", [])
        for i, report in enumerate(reports, 1):
            if not isinstance(report, dict):
                continue
            mission_text = report.get("mission", "")
            title = f"Mission {i}: {mission_text[:60]}" if mission_text else f"Mission {i}"
            tools = report.get("used_tools", [])
            status = report.get("result", "")
            lines = []
            if status:
                status_str = str(status)[:300]
                lines.append(status_str)
            if tools:
                lines.append(f"Tools: {', '.join(str(t) for t in tools)}")
            body = "\n".join(lines) if lines else "(no details)"
            console.print(Panel(body, title=title, style="cyan"))

        # Data access panel — shows data-querying tool calls
        tools_used_list = result.get("tools_used", [])
        if isinstance(tools_used_list, list):
            _render_data_access_panel(tools_used_list)

        # Audit panel
        audit = result.get("audit_report")
        if isinstance(audit, dict):
            checks = audit.get("checks", [])
            passed = sum(1 for c in checks if isinstance(c, dict) and c.get("passed"))
            total = len(checks)
            console.print(Panel(f"Checks: {passed}/{total} passed", title="Audit", style="bold yellow"))

        console.print(Panel("Run Complete", style="bold green"))

    elif event_type == "state_diff":
        node = event.get("node", "unknown")
        diff = event.get("diff", {})
        console.print(f"[dim]  [debug] state_diff ({node}): {json.dumps(diff, default=str)[:200]}[/]")

    elif event_type == "error":
        detail = event.get("detail", "Unknown error")
        console.print(f"[bold red]ERROR: {detail}[/]")


async def stream_run(
    user_input: str,
    prior_context: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """POST /run and stream SSE events, returning (run_id, answer)."""
    payload: dict[str, Any] = {"user_input": user_input}
    if prior_context is not None:
        payload["prior_context"] = prior_context

    headers: dict[str, str] = {}
    _api_key = os.environ.get("API_KEY")
    if _api_key:
        headers["X-API-Key"] = _api_key

    ctx_turns = len(prior_context) if prior_context else 0
    _log.info("SESSION REQUEST input_chars=%d context_turns=%d api=%s", len(user_input), ctx_turns, API_BASE_URL)
    _t0 = time.monotonic()

    run_id = ""
    answer = ""
    last_result: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=300.0) as client, client.stream("POST", "/run", json=payload, headers=headers) as resp:
        if resp.status_code != 200:
            body = await resp.aread()
            _log.error("SESSION ERROR status=%d body=%s", resp.status_code, body.decode()[:300])
            console.print(f"[bold red]Server error {resp.status_code}: {body.decode()[:500]}[/]")
            return "", ""

        async for line in resp.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str:
                continue
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            if not run_id and "run_id" in event:
                run_id = event["run_id"]
            if event.get("type") == "run_complete":
                last_result = event.get("result", {})
                answer = last_result.get("answer", "")

            _render_event(event)

    _elapsed = time.monotonic() - _t0
    if run_id and last_result:
        missions = len(last_result.get("mission_report", []))
        tools = len(last_result.get("tools_used", []))
        audit = last_result.get("audit_report", {})
        audit_summary = ""
        if isinstance(audit, dict):
            audit_summary = f" audit=P{audit.get('passed', 0)}/W{audit.get('warned', 0)}/F{audit.get('failed', 0)}"
        _log.info(
            "SESSION COMPLETE run_id=%s elapsed=%.1fs missions=%d tools=%d answer_chars=%d%s",
            run_id, _elapsed, missions, tools, len(answer), audit_summary,
        )
        _write_run_report(run_id, last_result)
    elif not run_id:
        _log.warning("SESSION NO_RESULT elapsed=%.1fs", _elapsed)

    return run_id, answer


async def interactive_session() -> None:
    """Interactive loop: prompt user, stream runs, accumulate context."""
    sep = "=" * 60
    console.print(sep)
    console.print("  Agentic Workflows - API Client Session")
    console.print(sep)
    console.print("  Commands: quit/q  exit  clear")
    console.print(f"  API: {API_BASE_URL}")
    console.print(sep)
    console.print()

    prior_context: list[dict[str, Any]] | None = None

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nSession ended.")
            break

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q"}:
            console.print("Session ended.")
            break
        if user_input.lower() == "clear":
            prior_context = None
            console.print("[yellow]Context cleared.[/]")
            continue

        console.print()
        run_id, answer = await stream_run(user_input, prior_context=prior_context)

        # Build minimal prior context for follow-up turns
        if run_id:
            if prior_context is None:
                prior_context = []
            prior_context.append({"role": "user", "content": user_input})
            if answer:
                prior_context.append({"role": "assistant", "content": answer})
            # Keep context window manageable (5 exchanges = 10 messages)
            if len(prior_context) > 10:
                prior_context = prior_context[-10:]

        console.print()


def main() -> None:
    """CLI entrypoint: parse args, ensure server, start interactive session."""
    global _DEBUG  # noqa: PLW0603
    if "--debug" in sys.argv or os.environ.get("DEBUG_SSE"):
        _DEBUG = True

    _ensure_server_running()
    asyncio.run(interactive_session())


if __name__ == "__main__":
    main()
