"""Tests for MissionContextStore, reciprocal_rank_fusion, encode_tool_pattern, _sha256.
Covers SCS-03, SCS-04, SCS-05, SCS-06 from VALIDATION.md.
"""
from agentic_workflows.storage.mission_context_store import (
    MissionContextStore,
    _sha256,
    encode_tool_pattern,
    reciprocal_rank_fusion,
)


class TestEncodeToolPattern:
    def test_known_tools(self):
        # write_file=bit4, sort_array=bit1  →  (1<<4)|(1<<1) = 18
        result = encode_tool_pattern(["write_file", "sort_array"])
        assert result == (1 << 4) | (1 << 1)

    def test_unknown_tools_ignored(self):
        result = encode_tool_pattern(["nonexistent_tool"])
        assert result == 0

    def test_empty_list(self):
        assert encode_tool_pattern([]) == 0

    def test_all_bits_unique(self):
        # Each registered tool should produce a different bit position
        r1 = encode_tool_pattern(["write_file"])
        r2 = encode_tool_pattern(["sort_array"])
        assert r1 != r2
        assert r1 & r2 == 0  # non-overlapping bits


class TestSha256:
    def test_determinism(self):
        assert _sha256("same input") == _sha256("same input")

    def test_different_inputs(self):
        assert _sha256("input a") != _sha256("input b")

    def test_returns_hex_string(self):
        result = _sha256("test")
        assert isinstance(result, str)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestReciprocalRankFusion:
    def test_known_input(self):
        # b appears in both lists at rank 1 and rank 0 — should score highest or tied with a
        scores = reciprocal_rank_fusion(["a", "b", "c"], ["b", "c", "a"])
        assert list(scores.keys())[0] in ("a", "b")  # winner is a or b
        assert "b" in scores

    def test_single_list(self):
        scores = reciprocal_rank_fusion(["x", "y", "z"])
        keys = list(scores.keys())
        assert keys == ["x", "y", "z"]  # order preserved from single list

    def test_empty(self):
        scores = reciprocal_rank_fusion()
        assert scores == {}

    def test_k_parameter(self):
        scores_k60 = reciprocal_rank_fusion(["a"], k=60)
        scores_k1 = reciprocal_rank_fusion(["a"], k=1)
        # k=1 gives higher score (1/(1+0+1)=0.5) than k=60 (1/(60+0+1)=~0.016)
        assert scores_k1["a"] > scores_k60["a"]


class TestMissionContextStoreFallback:
    def test_cascade_no_conn(self):
        store = MissionContextStore(pool=None)
        results = store.query_cascade("any mission goal")
        assert results == []

    def test_upsert_no_conn(self):
        store = MissionContextStore(pool=None)
        # Must not raise — no-op when pool is None
        store.upsert(
            run_id="run-1",
            mission_id="m-1",
            goal="test goal",
            status="completed",
            summary="summary",
            tools_used=["write_file"],
            key_results={},
            embedding=[0.0] * 384,
        )


class TestL2EarlyExit:
    """L2 early-exit: if BM25 returns >= top_k results, L4 HNSW is never called."""

    def _make_fake_row(self, id_: int) -> tuple:
        """Minimal DB row tuple matching the SELECT column order."""
        return (id_, "run-1", "m-1", f"goal {id_}", f"summary {id_}", ["write_file"], 0.9)

    def test_l4_skipped_when_l2_has_enough(self):
        """L4 query (embedding branch) must not execute when L2 >= top_k."""
        from unittest.mock import MagicMock

        store = MissionContextStore(pool=None)

        # Patch _cascade to observe internal behaviour via a real implementation
        # We test the logic by verifying that with top_k=3 and 3 L2 rows,
        # the method returns without touching L4 (embedding=None guard bypassed).
        # Strategy: mock the pool so we can control what each conn.execute returns.
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        # L0 exact hit → None (no short-circuit)
        # L2 returns 3 rows (== top_k=3) → triggers early-exit
        l2_rows = [self._make_fake_row(i) for i in range(3)]

        execute_returns = [
            MagicMock(fetchone=MagicMock(return_value=None)),   # L0
            MagicMock(fetchall=MagicMock(return_value=l2_rows)),  # L2
            # L4 must NOT be called — any call here would be a test failure
        ]
        mock_conn.execute.side_effect = execute_returns

        store._pool = mock_pool
        embedding = [0.1] * 384  # provide embedding to prove L4 is skipped, not missing
        results = store._cascade("sort the list", [], embedding, top_k=3)

        # L4 execute must not have been called (only L0 + L2 = 2 calls)
        assert mock_conn.execute.call_count == 2, (
            f"Expected 2 DB calls (L0+L2), got {mock_conn.execute.call_count}"
        )
        assert len(results) == 3


class TestSourceLayerAttribution:
    """source_layer field is set correctly on results from _cascade()."""

    def _make_fake_row(self, id_: int) -> tuple:
        """Minimal DB row tuple matching the SELECT column order."""
        return (id_, "run-1", "m-1", f"goal {id_}", f"summary {id_}", ["write_file"], 0.9)

    def test_l0_hit_has_source_layer_l0(self):
        """L0 exact hash match must set source_layer='L0' and score=1.0."""
        from unittest.mock import MagicMock

        store = MissionContextStore(pool=None)
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        l0_row = self._make_fake_row(99)
        mock_conn.execute.return_value.fetchone = MagicMock(return_value=l0_row)

        store._pool = mock_pool
        results = store._cascade("exact goal", [], None, top_k=3)

        assert len(results) == 1
        assert results[0]["source_layer"] == "L0"
        assert results[0]["score"] == 1.0

    def test_l2_early_exit_has_source_layer_l2(self):
        """L2 early-exit path must set source_layer='L2' on all results."""
        from unittest.mock import MagicMock

        store = MissionContextStore(pool=None)
        mock_conn = MagicMock()
        mock_pool = MagicMock()
        mock_pool.connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_pool.connection.return_value.__exit__ = MagicMock(return_value=False)

        l2_rows = [self._make_fake_row(i) for i in range(3)]
        execute_returns = [
            MagicMock(fetchone=MagicMock(return_value=None)),   # L0 miss
            MagicMock(fetchall=MagicMock(return_value=l2_rows)),  # L2 returns 3 (>= top_k=3)
        ]
        mock_conn.execute.side_effect = execute_returns

        store._pool = mock_pool
        results = store._cascade("sort the list", [], [0.1] * 384, top_k=3)

        assert len(results) == 3
        for r in results:
            assert r["source_layer"] == "L2", f"Expected 'L2', got '{r['source_layer']}'"

    def test_fallback_no_pool_returns_empty(self):
        """query_cascade() returns [] when pool=None (no source_layer needed)."""
        store = MissionContextStore(pool=None)
        results = store.query_cascade("any goal")
        assert results == []
