"""Run route handlers: POST /run (SSE), GET /run/{id}, GET /run/{id}/stream."""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import anyio
import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from agentic_workflows.api.models import ErrorResponse, RunStatusResponse
from agentic_workflows.api.sse import make_error, make_node_end, make_node_start, make_run_complete

log = structlog.get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /run  -- SSE streaming endpoint
# ---------------------------------------------------------------------------


@router.post("/run", response_model=None)
async def post_run(request: Request) -> EventSourceResponse:
    """Start an orchestrator run and stream node-transition SSE events."""
    # Parse and validate body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content=ErrorResponse(error="Invalid JSON body").model_dump(),
        )

    user_input = body.get("user_input")
    if not user_input:
        return JSONResponse(  # type: ignore[return-value]
            status_code=422,
            content=ErrorResponse(error="Validation error", detail="user_input is required").model_dump(),
        )

    run_id = body.get("run_id") or str(uuid4())
    prior_context = body.get("prior_context")
    client_ip = request.client.host if request.client else "unknown"

    orchestrator = request.app.state.orchestrator
    run_store = request.app.state.run_store

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
        "client_ip": client_ip,
    }

    async def producer() -> None:
        """Run orchestrator in a thread and push SSE events into the stream."""
        try:
            def _run_streaming() -> dict[str, Any]:
                """Stream node transitions and return final result."""
                from agentic_workflows.orchestration.langgraph.state_schema import (
                    ensure_state_defaults,
                    new_run_state,
                )
                from agentic_workflows.orchestration.langgraph.mission_parser import parse_missions

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

                # Setup callbacks
                from agentic_workflows.observability import get_langfuse_callback_handler
                orchestrator._active_callbacks = []
                handler = get_langfuse_callback_handler()
                if handler is not None:
                    orchestrator._active_callbacks = [handler]

                orchestrator._write_shared_plan(state)
                orchestrator.checkpoint_store.save(
                    run_id=state["run_id"],
                    step=state["step"],
                    node_name="init",
                    state=state,
                )

                config = {
                    "recursion_limit": orchestrator.max_steps * 9,
                    "callbacks": orchestrator._active_callbacks,
                }

                last_state = dict(state)
                for update_dict in orchestrator._compiled.stream(
                    state, config=config, stream_mode="updates"
                ):
                    # stream_mode="updates" yields {node_name: state_updates}
                    if not isinstance(update_dict, dict):
                        continue
                    for node_name, chunk in update_dict.items():
                        # Emit node SSE events (async send from sync thread)
                        start_evt = make_node_start(node_name, run_id)
                        anyio.from_thread.run(send_stream.send, start_evt)

                        end_evt = make_node_end(node_name, run_id)
                        anyio.from_thread.run(send_stream.send, end_evt)

                        # Track latest state from chunks
                        if isinstance(chunk, dict):
                            last_state.update(chunk)

                # Finalize
                last_state = ensure_state_defaults(last_state, system_prompt=orchestrator.system_prompt)
                final_state = orchestrator._finalize(last_state)

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
            try:
                await run_store.update_run(run_id, status="failed")
            except Exception:
                pass
            error_evt = make_error(run_id, str(exc))
            try:
                await send_stream.send(error_evt)
            except Exception:
                pass
        finally:
            await send_stream.aclose()
            request.app.state.active_streams.pop(run_id, None)

    async def event_generator():  # type: ignore[no-untyped-def]
        """Yield SSE events from the receive stream."""
        async for event in receive_stream:
            yield json.dumps(event, default=str)

    return EventSourceResponse(
        event_generator(),
        data_sender_callable=producer,
    )


# ---------------------------------------------------------------------------
# GET /run/{run_id}  -- status / result retrieval
# ---------------------------------------------------------------------------


@router.get("/run/{run_id}")
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


@router.get("/run/{run_id}/stream", response_model=None)
async def get_run_stream(run_id: str, request: Request) -> EventSourceResponse | JSONResponse:
    """Reconnect to an in-progress run's SSE stream (same session only)."""
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

    # Session validation: verify client IP matches
    client_ip = request.client.host if request.client else "unknown"
    if stream_info.get("client_ip") and stream_info["client_ip"] != client_ip:
        return JSONResponse(
            status_code=403,
            content=ErrorResponse(
                error="Forbidden",
                run_id=run_id,
                detail="Session mismatch: stream belongs to a different client",
            ).model_dump(),
        )

    receive_stream = stream_info["stream"]

    async def event_generator():  # type: ignore[no-untyped-def]
        try:
            async for event in receive_stream:
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
