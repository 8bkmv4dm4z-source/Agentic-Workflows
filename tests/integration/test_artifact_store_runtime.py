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
        provider = MockEmbeddingProvider()
        artifact_store = ArtifactStore(pool=pg_pool, embedding_provider=provider)
        cm = ContextManager(embedding_provider=provider, artifact_store=artifact_store)

        run_id = "test-run-artifact-01"
        state = _make_state(run_id, mission_id=1, goal="Write output to file")

        # Simulate tool execution: write_file produces a file_path artifact
        cm.on_tool_result(
            state,
            "write_file",
            result={"result": "Successfully wrote 10 characters to /tmp/out.txt"},
            args={"path": "/tmp/out.txt"},
            mission_id=1,
        )
        cm.on_mission_complete(state, mission_id=1)

        # Query mission_artifacts directly
        with pg_pool.connection() as conn:
            rows = conn.execute(
                "SELECT key, value, source_tool FROM mission_artifacts WHERE run_id = %s",
                (run_id,),
            ).fetchall()

        assert len(rows) >= 1
        keys = [r[0] for r in rows]
        tools = [r[2] for r in rows]
        assert "file_path" in keys
        assert "write_file" in tools

    def test_no_artifacts_when_pool_none(self, pg_pool, clean_pg):
        """SC-1 extended: ArtifactStore(pool=None) is a no-op — no rows inserted."""
        _provider = MockEmbeddingProvider()  # noqa: F841
        artifact_store_no_pool = ArtifactStore(pool=None)
        cm = ContextManager(artifact_store=artifact_store_no_pool)

        run_id = "test-run-no-pool-01"
        state = _make_state(run_id, mission_id=1, goal="Write output to file")

        # Call lifecycle methods — must not raise
        cm.on_tool_result(
            state,
            "write_file",
            result={"result": "Successfully wrote 5 characters to /tmp/x.txt"},
            args={"path": "/tmp/x.txt"},
            mission_id=1,
        )
        cm.on_mission_complete(state, mission_id=1)

        # No rows should exist in mission_artifacts for this run_id
        with pg_pool.connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM mission_artifacts WHERE run_id = %s",
                (run_id,),
            ).fetchone()[0]

        assert count == 0

    def test_multiple_artifacts_from_data_analysis(self, pg_pool, clean_pg):
        """SC-1 multi: data_analysis produces mean + outliers — both rows in mission_artifacts."""
        provider = MockEmbeddingProvider()
        artifact_store = ArtifactStore(pool=pg_pool, embedding_provider=provider)
        cm = ContextManager(embedding_provider=provider, artifact_store=artifact_store)

        run_id = "test-run-data-analysis-01"
        state = _make_state(run_id, mission_id=1, goal="Analyze dataset for outliers")

        # Simulate data_analysis tool result — produces mean + outliers artifacts
        cm.on_tool_result(
            state,
            "data_analysis",
            result={"mean": 5.0, "outliers": [10], "non_outliers": [1, 2, 3, 4, 5]},
            args={},
            mission_id=1,
        )
        cm.on_mission_complete(state, mission_id=1)

        # Both mean and outliers should be persisted
        with pg_pool.connection() as conn:
            rows = conn.execute(
                "SELECT key FROM mission_artifacts WHERE run_id = %s",
                (run_id,),
            ).fetchall()

        keys = [r[0] for r in rows]
        assert len(rows) >= 2
        assert "mean" in keys
        assert "outliers" in keys
