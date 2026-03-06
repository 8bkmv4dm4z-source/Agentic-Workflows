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

from agentic_workflows.logger import setup_dual_logging

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
_TMP_DIR = Path(os.environ.get("TMP_DIR", ".tmp"))

console = Console()

_DEBUG = False


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
                    "warning",
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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

    run_id = ""
    answer = ""
    last_result: dict[str, Any] = {}
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=300.0) as client:
        async with client.stream("POST", "/run", json=payload, headers=headers) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
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

    if run_id and last_result:
        _write_run_report(run_id, last_result)

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

    setup_dual_logging(log_dir=str(_TMP_DIR))
    _ensure_server_running()
    asyncio.run(interactive_session())


if __name__ == "__main__":
    main()
