"""CheckpointStore protocol -- storage abstraction for graph checkpoint persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agentic_workflows.orchestration.langgraph.state_schema import RunState


@runtime_checkable
class CheckpointStore(Protocol):
    """Protocol for persisting node-level state snapshots.

    Implementations must provide synchronous methods for save/load operations.
    SQLite (Phase 1) and Postgres (Phase 7) are the two backends.
    """

    def save(self, *, run_id: str, step: int, node_name: str, state: RunState) -> None:
        """Write a checkpoint snapshot for a specific node transition."""
        ...

    def load_latest(self, run_id: str) -> RunState | None:
        """Load the most recent checkpointed state for a run."""
        ...

    def list_checkpoints(self, run_id: str) -> list[dict[str, Any]]:
        """Return lightweight checkpoint metadata for timeline inspection."""
        ...

    def list_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        """Query distinct run_ids ordered by most recent checkpoint."""
        ...

    def load_latest_run(self) -> RunState | None:
        """Load the final state of the most recent run (any run_id)."""
        ...
