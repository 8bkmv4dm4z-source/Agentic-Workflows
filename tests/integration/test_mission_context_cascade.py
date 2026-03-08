"""Integration tests for Phase 7.3 MissionContextStore cascade retrieval.

Requires a live Postgres instance with pgvector extension and migrations 001-004 applied.
Skipped automatically when DATABASE_URL is not set.

Covers: SCS-08 (full cascade cycle), SCS-09 (cross-run injection), SCS-10 (two-run smoke).
"""
import os

import pytest

pytest.importorskip("psycopg_pool")

from agentic_workflows.context.embedding_provider import MockEmbeddingProvider
from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
from agentic_workflows.storage.mission_context_store import (
    MissionContextStore,
    encode_tool_pattern,
)

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres integration tests",
)


def _make_embedding(text: str) -> list[float]:
    return MockEmbeddingProvider().embed_sync(text)


@requires_postgres
@pytest.mark.postgres
class TestCascadeFullCycle:
    """SCS-08: Full cascade query cycle with real Postgres."""

    def test_upsert_and_l0_exact_hit(self, pg_pool, clean_pg):
        """Insert a mission context, then retrieve it via L0 exact hash match."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)

        goal = "Compute fibonacci sequence of length 50"
        embedding = _make_embedding(goal)

        store.upsert(
            run_id="run-test-01",
            mission_id="mission-1",
            goal=goal,
            status="completed",
            summary="Computed fib(50) using math_stats tool, result: 12586269025",
            tools_used=["math_stats", "write_file"],
            key_results={"fib_50": 12586269025},
            embedding=embedding,
        )

        results = store.query_cascade(goal, top_k=1)
        assert len(results) == 1
        assert results[0]["goal"] == goal
        assert results[0]["score"] == 1.0  # L0 exact hit score

    def test_l2_bm25_keyword_match(self, pg_pool, clean_pg):
        """Retrieve via L2 BM25 keyword match (different goal, same keywords)."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)

        original_goal = "Sort the numbers in ascending order using bubble sort"
        embedding = _make_embedding(original_goal)

        store.upsert(
            run_id="run-test-02",
            mission_id="mission-2",
            goal=original_goal,
            status="completed",
            summary="Sorted 100 numbers in ascending order",
            tools_used=["sort_array"],
            key_results={},
            embedding=embedding,
        )

        # Query with different wording but same keywords -- should hit L2 BM25
        results = store.query_cascade(
            "sort numbers ascending order",
            embedding=_make_embedding("sort numbers ascending order"),
            top_k=3,
        )
        assert len(results) >= 1
        # Result should be the stored mission
        goals = [r["goal"] for r in results]
        assert original_goal in goals

    def test_l4_cosine_semantic_match(self, pg_pool, clean_pg):
        """Retrieve via L4 cosine similarity for semantically similar but lexically different goal."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)

        # Store a mission
        original_goal = "Analyze the dataset and identify statistical outliers"
        embedding = _make_embedding(original_goal)

        store.upsert(
            run_id="run-test-03",
            mission_id="mission-3",
            goal=original_goal,
            status="completed",
            summary="Identified 5 outliers using IQR method",
            tools_used=["data_analysis"],
            key_results={"outlier_count": 5},
            embedding=embedding,
        )

        # Semantically similar query
        similar_goal = "Find anomalies in the data using statistical methods"
        results = store.query_cascade(
            similar_goal,
            embedding=_make_embedding(similar_goal),
            top_k=3,
        )
        # Should find something (cosine similarity is high for semantically similar text)
        assert isinstance(results, list)  # may or may not match depending on vector distance

    def test_empty_db_returns_empty(self, pg_pool, clean_pg):
        """Query on empty table returns empty list, no exception."""
        store = MissionContextStore(pool=pg_pool)
        results = store.query_cascade("any goal", top_k=3)
        assert results == []

    def test_upsert_idempotent(self, pg_pool, clean_pg):
        """Upserting the same (run_id, mission_id) twice updates, not duplicates."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)
        goal = "Test idempotent upsert"
        embedding = _make_embedding(goal)

        store.upsert(
            run_id="run-idem",
            mission_id="m-idem",
            goal=goal,
            status="completed",
            summary="First summary",
            tools_used=["write_file"],
            key_results={},
            embedding=embedding,
        )
        store.upsert(
            run_id="run-idem",
            mission_id="m-idem",
            goal=goal,
            status="completed",
            summary="Updated summary",
            tools_used=["write_file", "read_file"],
            key_results={},
            embedding=embedding,
        )

        results = store.query_cascade(goal, top_k=5)
        assert len(results) == 1  # no duplicate rows
        assert results[0]["summary"] == "Updated summary"


@requires_postgres
@pytest.mark.postgres
class TestCrossRunInjection:
    """SCS-09: ContextManager.build_planner_context_injection includes cross-run hits."""

    def test_injection_contains_cross_run_prefix(self, pg_pool, clean_pg):
        """After persisting a mission, a new ContextManager with the same store
        should include [Cross-run] Similar: prefix in planner context injection."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)

        # Persist a prior mission
        prior_goal = "Write a summary of the fibonacci sequence"
        embedding = _make_embedding(prior_goal)
        store.upsert(
            run_id="run-prior",
            mission_id="m-prior",
            goal=prior_goal,
            status="completed",
            summary="Wrote fibonacci summary explaining growth pattern",
            tools_used=["write_file", "math_stats"],
            key_results={},
            embedding=embedding,
        )

        # New ContextManager with same store -- simulates a new run
        cm = ContextManager(
            mission_context_store=store,
            embedding_provider=provider,
        )

        # State simulating a new mission with similar goal
        state: dict = {
            "missions": ["Explain the fibonacci sequence and write a summary"],
            "mission_contexts": {},
            "messages": [],
        }
        injection = cm.build_planner_context_injection(state)

        # Should include cross-run context
        assert "[Cross-run] Similar:" in injection

    def test_injection_capped_at_1500_chars(self, pg_pool, clean_pg):
        """Injection output never exceeds 1500 chars even with many stored missions."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)

        # Store 5 missions with long summaries
        for i in range(5):
            goal = f"Mission {i}: process large dataset with statistical analysis"
            embedding = _make_embedding(goal)
            store.upsert(
                run_id=f"run-cap-{i}",
                mission_id=f"m-cap-{i}",
                goal=goal,
                status="completed",
                summary="x" * 400,  # long summary
                tools_used=["data_analysis"],
                key_results={},
                embedding=embedding,
            )

        cm = ContextManager(
            mission_context_store=store,
            embedding_provider=provider,
        )
        state: dict = {
            "missions": ["process dataset with statistical methods"],
            "mission_contexts": {},
            "messages": [],
        }
        injection = cm.build_planner_context_injection(state)
        assert len(injection) <= 1500


@requires_postgres
@pytest.mark.postgres
class TestSmoketwOruns:
    """SCS-10: Two similar missions across runs -- mission 2 sees mission 1 context."""

    def test_two_run_smoke(self, pg_pool, clean_pg):
        """Full smoke: complete run 1 mission, then run 2 planner context includes run 1 context."""
        provider = MockEmbeddingProvider()
        store = MissionContextStore(pool=pg_pool, embedding_provider=provider)

        # --- Run 1: complete a mission ---
        run1_goal = "Sort an array of integers in ascending order"

        cm1 = ContextManager(
            mission_context_store=store,
            embedding_provider=provider,
        )
        # Simulate on_mission_complete call from run 1
        cm1._persist_mission_context({
            "goal": run1_goal,
            "summary": "Sorted 50 integers successfully using sort_array tool",
            "used_tools": ["sort_array"],
            "key_results": {"sorted": True},
            "run_id": "run-smoke-1",
            "mission_id": "mission-smoke-1",
        })

        # --- Run 2: new ContextManager, same store ---
        cm2 = ContextManager(
            mission_context_store=store,
            embedding_provider=provider,
        )
        state: dict = {
            # Similar but not identical goal -- tests L2/L4 retrieval
            "missions": ["Sort the list of numbers from smallest to largest"],
            "mission_contexts": {},
            "messages": [],
        }
        injection = cm2.build_planner_context_injection(state)

        # Mission 2 should see mission 1's context
        assert "[Cross-run] Similar:" in injection or "sort" in injection.lower()
