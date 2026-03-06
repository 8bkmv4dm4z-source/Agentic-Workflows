"""MemoStore protocol -- storage abstraction for memo/cache persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agentic_workflows.orchestration.langgraph.memo_store import MemoLookupResult, PutResult


@runtime_checkable
class MemoStore(Protocol):
    """Protocol for persisting run-scoped memoization entries.

    Implementations must provide synchronous methods mirroring SQLiteMemoStore.
    SQLite (Phase 1) and Postgres (Phase 7) are the two backends.
    """

    def put(
        self,
        *,
        run_id: str,
        key: str,
        value: Any,
        namespace: str = "run",
        source_tool: str = "memoize",
        step: int = 0,
        created_at: str = "",
    ) -> PutResult:
        """Insert or update a memo entry with deterministic hash metadata."""
        ...

    def get(self, *, run_id: str, key: str, namespace: str = "run") -> MemoLookupResult:
        """Retrieve a memoized value for a specific run and key."""
        ...

    def get_latest(self, *, key: str, namespace: str = "run") -> MemoLookupResult:
        """Retrieve latest memoized value by key across all run ids."""
        ...

    def list_entries(self, *, run_id: str, namespace: str = "run") -> list[dict[str, Any]]:
        """List memo metadata for visibility/reporting."""
        ...

    def delete(
        self, *, run_id: str, key: str, namespace: str = "run", value_hash: str | None = None
    ) -> int:
        """Delete memo entries by key (optionally constrained by hash)."""
        ...

    def get_cache_value(self, *, key: str, run_id: str = "shared") -> dict[str, Any] | None:
        """Return cached dict payload for shared cache keys, if present."""
        ...
