"""Integration tests for Phase 7.5 SC-1: ArtifactStore runtime wiring.

Verifies that after a mission completes with tool results, artifacts are
persisted to the mission_artifacts table in Postgres.

Requires a live Postgres instance with migrations 001-004 applied.
Skipped automatically when DATABASE_URL is not set.

Covers: SC-1 (primary), SC-1 extended (pool=None no-op), SC-1 data_analysis multiple artifacts.
"""
import os

import pytest

pytest.importorskip("psycopg_pool")

from agentic_workflows.context.embedding_provider import MockEmbeddingProvider  # noqa: E402
from agentic_workflows.orchestration.langgraph.context_manager import (  # noqa: E402
    ContextManager,
    MissionContext,
)
from agentic_workflows.storage.artifact_store import ArtifactStore  # noqa: E402

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres integration tests",
)


def _make_state(run_id: str, mission_id: int = 1, goal: str = "test goal") -> dict:
    """Build minimum RunState shape required by ContextManager lifecycle methods."""
    return {
        "run_id": run_id,
        "messages": [{"role": "system", "content": "sys"}],
        "mission_contexts": {
            str(mission_id): MissionContext(
                mission_id=mission_id,
                goal=goal,
                status="pending",
                step_range=(1, 3),
            ).model_dump()
        },
        "mission_reports": [],
        "current_step": 3,
    }


@requires_postgres
@pytest.mark.postgres
class TestArtifactStoreRuntime:
    """SC-1: mission completes → artifacts appear in mission_artifacts table."""

    def test_artifacts_persisted_after_mission_complete(self, pg_pool, clean_pg):
        """SC-1 primary: write_file artifact is persisted to mission_artifacts after mission complete."""
        raise NotImplementedError("RED stub — implement in GREEN phase")

    def test_no_artifacts_when_pool_none(self, pg_pool, clean_pg):
        """SC-1 extended: ArtifactStore(pool=None) is a no-op — no rows inserted."""
        raise NotImplementedError("RED stub — implement in GREEN phase")

    def test_multiple_artifacts_from_data_analysis(self, pg_pool, clean_pg):
        """SC-1 multi: data_analysis produces mean + outliers — both rows in mission_artifacts."""
        raise NotImplementedError("RED stub — implement in GREEN phase")
