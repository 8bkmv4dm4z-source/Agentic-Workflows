"""Run route handlers: POST /run (SSE), GET /run/{id}, GET /run/{id}/stream."""

from __future__ import annotations

import contextlib
import json
import os
import time
from typing import Any
from uuid import uuid4

import anyio
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentic_workflows.api.models import ErrorResponse, RunRequest, RunStatusResponse
from agentic_workflows.api.sse import make_error, make_node_end, make_node_start, make_run_complete
from agentic_workflows.api.stream_token import generate_token, validate_token

log = structlog.get_logger()

router = APIRouter()

_SSE_MAX_DEFAULT = 300  # seconds


# ---------------------------------------------------------------------------
# POST /run  -- SSE streaming endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=None,
    summary="Start an orchestrator run",
    description="Submit a natural-language task and receive SSE events as the agent executes. "
    "The stream emits node_start, node_end, and run_complete events.",
    responses={422: {"model": ErrorResponse, "description": "Validation error"}},
)
async def post_run(body: RunRequest, request: Request) -> EventSourceResponse:
    """Start an orchestrator run and stream node-transition SSE events."""
    user_input = body.user_input
    run_id = f"pub_{uuid4().hex}"
    prior_context = [entry.model_dump() for entry in body.prior_context] or None
    client_ip = request.client.host if request.client else "unknown"

    orchestrator = request.app.state.orchestrator
    run_store = request.app.state.run_store
    stream_secret = request.app.state.stream_secret

    # Generate HMAC stream token for reconnect authorization
    stream_token = generate_token(run_id, stream_secret)

    # Persist initial run record
    await run_store.save_run(
        run_id,
        status="running",
        user_input=user_input,
        prior_context=prior_context,
        client_ip=client_ip,
    )

    # Create memory object streams for SSE bridge
    send_stream, receive_stream = anyio.create_memory_object_stream[dict[str, Any]](
        max_buffer_size=100,
    )

    # Store receive_stream for reconnection support
    request.app.state.active_streams[run_id] = {
        "stream": receive_stream,
    }

    async def producer() -> None:
        """Run orchestrator in a thread and push SSE events into the stream."""
        try:
            def _run_streaming() -> dict[str, Any]:
                """Stream node transitions and return final result."""
                from agentic_workflows.orchestration.langgraph.mission_parser import parse_missions
                from agentic_workflows.orchestration.langgraph.state_schema import (
                    ensure_state_defaults,
                    new_run_state,
                )

                # Build state (mirror run() logic)
                state = new_run_state(orchestrator.system_prompt, user_input, run_id=run_id)
                if prior_context:
                    prior_system_parts = [
                        m["content"] for m in prior_context if m.get("role") == "system"
                    ]
                    prior_conversation = [
                        m for m in prior_context if m.get("role") != "system"
                    ]
                    if prior_system_parts:
                        for msg in state["messages"]:
                            if msg.get("role") == "system":
                                msg["content"] += "\n\n" + "\n".join(prior_system_parts)
                                break
                    if prior_conversation:
                        system_msgs = [m for m in state["messages"] if m.get("role") == "system"]
                        user_msgs = [m for m in state["messages"] if m.get("role") != "system"]
                        state["messages"] = system_msgs + prior_conversation + user_msgs

                state = ensure_state_defaults(state, system_prompt=orchestrator.system_prompt)
                state["rerun_context"] = {}

                structured_plan = parse_missions(user_input)
                missions = structured_plan.flat_missions
                contracts = orchestrator._build_mission_contracts_from_plan(structured_plan, missions)
                state["missions"] = missions
                state["structured_plan"] = structured_plan.to_dict()
                state["mission_contracts"] = contracts
                state["mission_reports"] = orchestrator._initialize_mission_reports(
                    missions, contracts=contracts
                )
                state["active_mission_index"] = -1
                state["active_mission_id"] = 0

                # Setup callbacks via ContextVar (W1-2: per-request isolation)
                from agentic_workflows.observability import get_langfuse_callback_handler
                from agentic_workflows.orchestration.langgraph.graph import _active_callbacks_var
                handler = get_langfuse_callback_handler()
                _active_callbacks_var.set([handler] if handler else [])

                orchestrator._write_shared_plan(state)
                orchestrator.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="init",
                    state=state,
                )

                config = {
                    "recursion_limit": orchestrator.max_steps * 9,
                    "callbacks": _active_callbacks_var.get(),
                }

                # Stream graph execution, emitting SSE events for each node.
                # NOTE: stream_mode="updates" yields dicts where annotated list
                # fields (tool_history, mission_reports, etc.) are zeroed by
                # _sequential_node to prevent operator.add doubling.  We only
                # use the stream for SSE events, not state accumulation.
                for update_dict in orchestrator._compiled.stream(
                    state, config=config, stream_mode="updates"
                ):
                    # stream_mode="updates" yields {node_name: state_updates}
                    if not isinstance(update_dict, dict):
                        continue
                    for node_name, _chunk in update_dict.items():
                        model = getattr(orchestrator.provider, "model", None) if node_name == "plan" else None
                        start_evt = make_node_start(node_name, run_id, model=model)
                        anyio.from_thread.run(send_stream.send, start_evt)

                        end_evt = make_node_end(node_name, run_id)
                        anyio.from_thread.run(send_stream.send, end_evt)

                # Retrieve the complete final state from the checkpoint saved
                # by _finalize (which ran as a graph node during streaming).
                # This avoids the annotated-list-field zeroing issue entirely.
                saved = orchestrator.checkpoint_store.load_latest(run_id)
                final_state = saved if saved is not None else state
                final_state = ensure_state_defaults(final_state, system_prompt=orchestrator.system_prompt)

                memo_entries = orchestrator.memo_store.list_entries(run_id=final_state["run_id"])
                return {
                    "answer": final_state.get("final_answer", ""),
                    "tools_used": final_state.get("tool_history", []),
                    "mission_report": final_state.get("mission_reports", []),
                    "run_id": final_state.get("run_id"),
                    "memo_events": final_state.get("memo_events", []),
                    "memo_store_entries": memo_entries,
                    "derived_snapshot": orchestrator._build_derived_snapshot(
                        final_state, memo_entries
                    ),
                    "checkpoints": orchestrator.checkpoint_store.list_checkpoints(
                        final_state["run_id"]
                    ),
                    "audit_report": final_state.get("audit_report"),
                    "state": dict(final_state),
                }

            # Run the orchestrator in a background thread
            result = await anyio.to_thread.run_sync(_run_streaming)

            # Persist completed result
            await run_store.update_run(
                run_id,
                status="completed",
                completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                result=result,
                missions_completed=len(result.get("mission_report", [])),
                tools_used=[
                    t["tool"] if isinstance(t, dict) else str(t)
                    for t in result.get("tools_used", [])
                ],
            )

            # Emit run_complete event
            complete_evt = make_run_complete(run_id, _safe_serialize(result))
            await send_stream.send(complete_evt)

        except Exception as exc:
            log.error("run.producer_error", run_id=run_id, error=str(exc))
            with contextlib.suppress(Exception):
                await run_store.update_run(run_id, status="failed")
            error_evt = make_error(run_id, str(exc))
            with contextlib.suppress(Exception):
                await send_stream.send(error_evt)
        finally:
            await send_stream.aclose()
            request.app.state.active_streams.pop(run_id, None)

    _sse_max = int(os.environ.get("SSE_MAX_DURATION_SECONDS", str(_SSE_MAX_DEFAULT)))

    async def event_generator():  # type: ignore[no-untyped-def]
        """Yield SSE events from the receive stream with duration cap."""
        start = time.time()
        async for event in receive_stream:
            if time.time() - start > _sse_max:
                yield json.dumps({"type": "error", "detail": "stream_timeout"}, default=str)
                return
            yield json.dumps(event, default=str)

    return EventSourceResponse(
        event_generator(),
        data_sender_callable=producer,
        headers={"X-Stream-Token": stream_token},
    )


# ---------------------------------------------------------------------------
# GET /run/{run_id}  -- status / result retrieval
# ---------------------------------------------------------------------------


@router.get(
    "/run/{run_id}",
    response_model=RunStatusResponse,
    summary="Get run status",
    description="Retrieve the current status of a run. Returns partial progress for in-progress runs "
    "and full results (including audit report) for completed runs.",
    responses={404: {"model": ErrorResponse, "description": "Run not found"}},
)
async def get_run(run_id: str, request: Request) -> JSONResponse:
    """Return run status (partial for in-progress, full for completed/failed)."""
    run_store = request.app.state.run_store
    row = await run_store.get_run(run_id)

    if row is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(error="Run not found", run_id=run_id).model_dump(),
        )

    status = row.get("status", "pending")
    elapsed_s = None
    if row.get("created_at"):
        try:
            from datetime import UTC, datetime
            created = datetime.fromisoformat(row["created_at"])
            if status == "running":
                elapsed_s = (datetime.now(UTC) - created).total_seconds()
            elif row.get("completed_at"):
                completed = datetime.fromisoformat(row["completed_at"])
                elapsed_s = (completed - created).total_seconds()
        except (ValueError, TypeError):
            pass

    # Parse JSON fields
    result_data = _parse_json_field(row.get("result_json"))
    tools_used = _parse_json_field(row.get("tools_used_json")) or []

    # Extract audit_report and mission_reports from result if available
    audit_report = None
    mission_reports: list[dict[str, Any]] = []
    if isinstance(result_data, dict):
        audit_report = result_data.get("audit_report")
        mission_reports = result_data.get("mission_report", [])

    response = RunStatusResponse(
        run_id=run_id,
        status=status,
        elapsed_s=elapsed_s,
        missions_completed=row.get("missions_completed", 0),
        tools_used_so_far=tools_used if isinstance(tools_used, list) else [],
        result=result_data if status in ("completed", "failed") else None,
        audit_report=audit_report,
        mission_reports=mission_reports,
    )
    return JSONResponse(content=response.model_dump())


# ---------------------------------------------------------------------------
# GET /run/{run_id}/stream  -- reconnect to in-progress SSE stream
# ---------------------------------------------------------------------------


@router.get(
    "/run/{run_id}/stream",
    response_model=None,
    summary="Reconnect to SSE stream",
    description="Reconnect to an in-progress run's SSE event stream. "
    "Requires a valid X-Stream-Token header obtained from the POST /run response.",
    responses={
        404: {"model": ErrorResponse, "description": "Stream not found or run completed"},
        403: {"model": ErrorResponse, "description": "Invalid or expired stream token"},
    },
)
async def get_run_stream(run_id: str, request: Request) -> EventSourceResponse | JSONResponse:
    """Reconnect to an in-progress run's SSE stream (requires valid HMAC stream token)."""
    active_streams = request.app.state.active_streams
    stream_info = active_streams.get(run_id)

    if stream_info is None:
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                error="Stream not found",
                run_id=run_id,
                detail="Run not in progress or already completed",
            ).model_dump(),
        )

    # Token-based validation: verify HMAC stream token
    stream_token_header = request.headers.get("X-Stream-Token")
    stream_secret = request.app.state.stream_secret

    if not stream_token_header or not validate_token(stream_token_header, run_id, stream_secret):
        return JSONResponse(
            status_code=403,
            content=ErrorResponse(
                error="Forbidden",
                run_id=run_id,
                detail="Missing or invalid stream token",
            ).model_dump(),
        )

    receive_stream = stream_info["stream"]

    _sse_max = int(os.environ.get("SSE_MAX_DURATION_SECONDS", str(_SSE_MAX_DEFAULT)))

    async def event_generator():  # type: ignore[no-untyped-def]
        start = time.time()
        try:
            async for event in receive_stream:
                if time.time() - start > _sse_max:
                    yield json.dumps({"type": "error", "detail": "stream_timeout"}, default=str)
                    return
                yield json.dumps(event, default=str)
        except anyio.ClosedResourceError:
            pass

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_field(value: str | None) -> Any:
    """Parse a JSON string field from the DB, returning None on failure."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def _safe_serialize(obj: Any) -> dict[str, Any]:
    """Convert a result dict to JSON-safe form."""
    try:
        serialized = json.loads(json.dumps(obj, default=str))
        return serialized if isinstance(serialized, dict) else {"raw": serialized}
    except (TypeError, ValueError):
        return {"error": "Result not serializable"}
