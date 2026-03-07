"""GET /runs — paginated run history endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from agentic_workflows.api.models import ErrorResponse, RunListResponse, RunSummary

log = structlog.get_logger()

router = APIRouter()


@router.get(
    "/runs",
    response_model=RunListResponse,
    summary="List recent runs",
    description="Return a paginated list of agent runs ordered newest-first. "
    "Use the next_cursor field to fetch the next page.",
    responses={500: {"model": ErrorResponse, "description": "Storage error"}},
)
async def get_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="Number of results per page"),
    cursor: str | None = Query(default=None, description="Pagination cursor (run_id of last item)"),
) -> JSONResponse:
    """Return paginated run summaries, newest first."""
    run_store = request.app.state.run_store

    try:
        rows = await run_store.list_runs(limit=limit + 1, cursor=cursor)
    except Exception as exc:
        log.error("runs.list_error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(error="Storage error", detail=str(exc)).model_dump(),
        )

    # Determine next cursor: if we got limit+1 rows, there is a next page
    has_next = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = page_rows[-1]["run_id"] if has_next and page_rows else None

    items: list[RunSummary] = []
    for row in page_rows:
        # Parse elapsed_s from created_at / completed_at
        elapsed_s: float | None = None
        try:
            if row.get("created_at") and row.get("completed_at"):
                created = datetime.fromisoformat(row["created_at"])
                completed = datetime.fromisoformat(row["completed_at"])
                elapsed_s = (completed - created).total_seconds()
        except (ValueError, TypeError):
            pass

        # Parse created_at to datetime
        created_at: datetime
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError, KeyError):
            created_at = datetime.now(UTC)

        items.append(
            RunSummary(
                run_id=row["run_id"],
                status=row.get("status", "unknown"),
                created_at=created_at,
                elapsed_s=elapsed_s,
                missions_completed=row.get("missions_completed", 0),
            )
        )

    response = RunListResponse(items=items, next_cursor=next_cursor)
    return JSONResponse(content=response.model_dump(mode="json"))
