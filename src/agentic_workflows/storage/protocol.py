"""RunStore protocol -- storage abstraction for run persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunStore(Protocol):
    """Protocol for persisting agent run records.

    Implementations must provide async methods for CRUD operations on runs.
    SQLite (Phase 6) and Postgres (Phase 7) are planned backends.
    """

    async def save_run(self, run_id: str, *, status: str, **fields: Any) -> None:
        """Insert a new run record."""
        ...

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve a run by ID, or None if not found."""
        ...

    async def list_runs(
        self, limit: int = 20, cursor: str | None = None
    ) -> list[dict[str, Any]]:
        """Return runs ordered by created_at DESC, with optional cursor pagination."""
        ...

    async def update_run(self, run_id: str, **fields: Any) -> None:
        """Update fields on an existing run record."""
        ...
