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
from typing import Any

import httpx
from rich.console import Console
from rich.panel import Panel

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

console = Console()

_DEBUG = False


def _ensure_server_running() -> None:
    """Check if the API server is reachable; auto-start uvicorn if not."""
    for attempt in range(6):
        try:
            resp = httpx.get(f"{API_BASE_URL}/health", timeout=2.0)
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
        console.print(f"[bold blue]>>> {node}[/]")

    elif event_type == "node_end":
        node = event.get("node", "unknown")
        console.print(f"[green]  completed: {node}[/]")

    elif event_type == "run_complete":
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
) -> str:
    """POST /run and stream SSE events, returning the run_id."""
    payload: dict[str, Any] = {"user_input": user_input}
    if prior_context is not None:
        payload["prior_context"] = prior_context

    run_id = ""
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=300.0) as client:
        async with client.stream("POST", "/run", json=payload) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                console.print(f"[bold red]Server error {resp.status_code}: {body.decode()[:500]}[/]")
                return ""

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

                _render_event(event)

    return run_id


async def interactive_session() -> None:
    """Interactive loop: prompt user, stream runs, accumulate context."""
    sep = "=" * 60
    console.print(sep)
    console.print("  Agentic Workflows - API Client Session")
    console.print(sep)
    console.print("  Commands: quit/q  exit")
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

        console.print()
        run_id = await stream_run(user_input, prior_context=prior_context)

        # Build minimal prior context for follow-up turns
        if run_id:
            if prior_context is None:
                prior_context = []
            prior_context.append({"role": "user", "content": user_input})
            # Keep context window manageable
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
