"""Concurrency tests for Postgres stores.

Validates ROADMAP Phase 7 Success Criterion 2:
"5 concurrent POST /run requests produce no locking errors."

All tests require a live Postgres database (DATABASE_URL env var).
Skipped automatically when DATABASE_URL is not set or psycopg_pool is not installed.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

# Skip entire module if psycopg_pool is not installed
pytest.importorskip("psycopg_pool")

from agentic_workflows.orchestration.langgraph.checkpoint_postgres import (  # noqa: E402
    PostgresCheckpointStore,
)
from agentic_workflows.orchestration.langgraph.memo_postgres import PostgresMemoStore  # noqa: E402
from agentic_workflows.orchestration.langgraph.state_schema import new_run_state  # noqa: E402
from agentic_workflows.storage.postgres import PostgresRunStore  # noqa: E402

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)

CONCURRENT_COUNT = 5


@requires_postgres
@pytest.mark.postgres
class TestConcurrentRunStoreWrites:
    """5 concurrent save_run calls produce no locking errors."""

    async def test_concurrent_save_run(self, pg_pool, clean_pg):
        """5 concurrent save_run() calls complete without errors and all are retrievable."""
        store = PostgresRunStore(pg_pool)
        await store.initialize()

        run_ids = [f"concurrent-run-{uuid.uuid4().hex[:8]}" for _ in range(CONCURRENT_COUNT)]

        # Fire 5 concurrent save_run calls
        await asyncio.gather(
            *[
                store.save_run(rid, status="pending", user_input=f"concurrent-{i}")
                for i, rid in enumerate(run_ids)
            ]
        )

        # Verify all 5 are retrievable
        for rid in run_ids:
            result = await store.get_run(rid)
            assert result is not None, f"Run {rid} should be retrievable after concurrent write"
            assert result["status"] == "pending"

        # Verify list_runs returns at least 5
        all_runs = await store.list_runs(limit=20)
        assert len(all_runs) >= CONCURRENT_COUNT


@requires_postgres
@pytest.mark.postgres
class TestConcurrentCheckpointStoreWrites:
    """5 concurrent checkpoint save calls produce no locking errors."""

    async def test_concurrent_checkpoint_save(self, pg_pool, clean_pg):
        """5 concurrent checkpoint save() calls complete without errors."""
        store = PostgresCheckpointStore(pg_pool)
        loop = asyncio.get_running_loop()

        run_ids = [f"ckpt-{uuid.uuid4().hex[:8]}" for _ in range(CONCURRENT_COUNT)]
        states = [new_run_state(f"mission-{i}", rid) for i, rid in enumerate(run_ids)]

        # Run sync save() calls concurrently via executor
        await asyncio.gather(
            *[
                loop.run_in_executor(
                    None,
                    lambda rid=rid, state=state: store.save(
                        run_id=rid, step=1, node_name="plan", state=state
                    ),
                )
                for rid, state in zip(run_ids, states, strict=True)
            ]
        )

        # Verify all 5 are retrievable
        for rid in run_ids:
            result = store.load_latest(rid)
            assert result is not None, f"Checkpoint {rid} should be retrievable"


@requires_postgres
@pytest.mark.postgres
class TestConcurrentMemoStoreWrites:
    """5 concurrent memo put calls produce no locking errors."""

    async def test_concurrent_memo_put(self, pg_pool, clean_pg):
        """5 concurrent memo put() calls complete without errors."""
        store = PostgresMemoStore(pg_pool)
        loop = asyncio.get_running_loop()

        run_ids = [f"memo-{uuid.uuid4().hex[:8]}" for _ in range(CONCURRENT_COUNT)]

        # Run sync put() calls concurrently via executor
        await asyncio.gather(
            *[
                loop.run_in_executor(
                    None,
                    lambda rid=rid, i=i: store.put(
                        run_id=rid, key=f"key-{i}", value={"concurrent": i}
                    ),
                )
                for i, rid in enumerate(run_ids)
            ]
        )

        # Verify all 5 are retrievable
        for i, rid in enumerate(run_ids):
            result = store.get(run_id=rid, key=f"key-{i}")
            assert result.found is True, f"Memo for {rid} should be retrievable"
            assert result.value == {"concurrent": i}


@requires_postgres
@pytest.mark.postgres
class TestConcurrentMixedOperations:
    """Simulate 5 concurrent requests each performing save_run + checkpoint + memo."""

    async def test_concurrent_mixed_store_operations(self, pg_pool, clean_pg):
        """5 concurrent mixed-store operations complete without locking errors."""
        run_store = PostgresRunStore(pg_pool)
        checkpoint_store = PostgresCheckpointStore(pg_pool)
        memo_store = PostgresMemoStore(pg_pool)
        await run_store.initialize()

        loop = asyncio.get_running_loop()
        run_ids = [f"mixed-{uuid.uuid4().hex[:8]}" for _ in range(CONCURRENT_COUNT)]

        async def simulate_request(i: int, rid: str) -> None:
            """Simulate a single API request: save_run + checkpoint + memo."""
            # Async: save_run
            await run_store.save_run(rid, status="pending", user_input=f"request-{i}")

            # Sync via executor: checkpoint save
            state = new_run_state(f"mission-{i}", rid)
            await loop.run_in_executor(
                None,
                lambda: checkpoint_store.save(
                    run_id=rid, step=1, node_name="plan", state=state
                ),
            )

            # Sync via executor: memo put
            await loop.run_in_executor(
                None,
                lambda: memo_store.put(
                    run_id=rid, key="result", value={"request": i}
                ),
            )

            # Async: update status
            await run_store.update_run(rid, status="completed")

        # Fire all 5 concurrent "requests"
        await asyncio.gather(
            *[simulate_request(i, rid) for i, rid in enumerate(run_ids)]
        )

        # Verify all data is consistent
        for i, rid in enumerate(run_ids):
            run = await run_store.get_run(rid)
            assert run is not None, f"Run {rid} missing"
            assert run["status"] == "completed"

            ckpt = checkpoint_store.load_latest(rid)
            assert ckpt is not None, f"Checkpoint {rid} missing"

            memo = memo_store.get(run_id=rid, key="result")
            assert memo.found is True, f"Memo {rid} missing"
            assert memo.value == {"request": i}
