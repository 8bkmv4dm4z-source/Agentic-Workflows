"""Integration tests for memory consolidation against Postgres."""

from __future__ import annotations

import pytest

psycopg_pool = pytest.importorskip("psycopg_pool")

from conftest import requires_postgres

from agentic_workflows.storage.memory_consolidation import consolidate_memories


def _make_embedding(base: list[float], dim: int = 384) -> str:
    """Create a Postgres vector literal from a base pattern (padded to dim)."""
    vec = (base + [0.0] * dim)[:dim]
    return "[" + ",".join(str(x) for x in vec) + "]"


@requires_postgres
@pytest.mark.integration
class TestConsolidationPostgres:
    def test_consolidates_old_similar_missions(self, pg_pool, clean_pg) -> None:
        """Insert 3 similar old missions, verify consolidation merges them."""
        emb_a = _make_embedding([1.0, 0.01, 0.0])
        emb_b = _make_embedding([1.0, 0.02, 0.0])
        emb_c = _make_embedding([1.0, 0.03, 0.0])

        with pg_pool.connection() as conn:
            for i, (emb, goal) in enumerate(
                [(emb_a, "Sort data A"), (emb_b, "Sort data B"), (emb_c, "Sort data C")]
            ):
                conn.execute(
                    "INSERT INTO mission_contexts "
                    "(run_id, mission_id, goal, summary, tools_used, embedding, status, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'completed', NOW() - INTERVAL '10 days')",
                    (
                        f"run-old-{i}",
                        i,
                        goal,
                        f"summary {i}",
                        ["sort_array"],
                        emb,
                    ),
                )

        result = consolidate_memories(pg_pool, age_days=7, similarity_threshold=0.85)

        assert result["clusters"] >= 1
        assert result["consolidated"] >= 2

        # Verify row count decreased
        with pg_pool.connection() as conn:
            row = conn.execute("SELECT count(*) FROM mission_contexts").fetchone()
            assert row[0] < 3  # was 3, should be 1 after consolidation

    def test_skips_recent_missions(self, pg_pool, clean_pg) -> None:
        """Recent missions (created_at = NOW()) should NOT be consolidated."""
        emb_a = _make_embedding([1.0, 0.01, 0.0])
        emb_b = _make_embedding([1.0, 0.02, 0.0])

        with pg_pool.connection() as conn:
            for i, emb in enumerate([emb_a, emb_b]):
                conn.execute(
                    "INSERT INTO mission_contexts "
                    "(run_id, mission_id, goal, summary, tools_used, embedding, status) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'completed')",
                    (f"run-recent-{i}", i, f"Recent goal {i}", f"summary {i}", ["write_file"], emb),
                )

        result = consolidate_memories(pg_pool, age_days=7, similarity_threshold=0.85)

        assert result["consolidated"] == 0
        assert result["clusters"] == 0

        # Rows should be unchanged
        with pg_pool.connection() as conn:
            row = conn.execute("SELECT count(*) FROM mission_contexts").fetchone()
            assert row[0] == 2
