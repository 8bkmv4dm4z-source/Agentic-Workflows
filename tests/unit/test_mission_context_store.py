"""Tests for MissionContextStore, reciprocal_rank_fusion, encode_tool_pattern, _sha256.
Covers SCS-03, SCS-04, SCS-05, SCS-06 from VALIDATION.md.
"""
import pytest

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
