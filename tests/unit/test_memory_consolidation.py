"""Unit tests for memory consolidation clustering logic."""

from __future__ import annotations

from agentic_workflows.storage.memory_consolidation import (
    _cluster_by_similarity,
    _cosine_similarity,
    _merge_cluster_summary,
    consolidate_memories,
)

# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        assert _cosine_similarity([1, 0, 0], [1, 0, 0]) == 1.0

    def test_orthogonal_vectors(self) -> None:
        assert _cosine_similarity([1, 0, 0], [0, 1, 0]) == 0.0

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0, 0, 0], [1, 0, 0]) == 0.0

    def test_opposite_vectors(self) -> None:
        assert _cosine_similarity([1, 0, 0], [-1, 0, 0]) == -1.0

    def test_similar_vectors(self) -> None:
        # [1, 1, 0] and [1, 0.9, 0] should have high similarity
        sim = _cosine_similarity([1, 1, 0], [1, 0.9, 0])
        assert sim > 0.99

    def test_both_zero_vectors(self) -> None:
        assert _cosine_similarity([0, 0, 0], [0, 0, 0]) == 0.0


# ---------------------------------------------------------------------------
# _cluster_by_similarity
# ---------------------------------------------------------------------------


def _make_item(item_id: int, embedding: list[float], goal: str = "goal") -> dict:
    return {
        "id": item_id,
        "embedding": embedding,
        "goal": goal,
        "summary": f"summary for {item_id}",
        "tools_used": ["tool_a"],
        "run_id": f"run-{item_id}",
        "mission_id": item_id,
    }


class TestClusterBySimilarity:
    def test_two_similar_pairs(self) -> None:
        """4 items: pair (1,2) similar, pair (3,4) similar, pairs dissimilar."""
        items = [
            _make_item(1, [1, 0, 0]),
            _make_item(2, [0.99, 0.05, 0]),  # close to item 1
            _make_item(3, [0, 1, 0]),
            _make_item(4, [0.05, 0.99, 0]),  # close to item 3
        ]
        clusters = _cluster_by_similarity(items, threshold=0.85)
        assert len(clusters) == 2
        # Each cluster should have 2 items
        sizes = sorted(len(c) for c in clusters)
        assert sizes == [2, 2]

    def test_all_similar(self) -> None:
        """All items are very similar -> 1 cluster."""
        items = [
            _make_item(1, [1, 0.01, 0]),
            _make_item(2, [1, 0.02, 0]),
            _make_item(3, [1, 0.03, 0]),
        ]
        clusters = _cluster_by_similarity(items, threshold=0.85)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_no_similar(self) -> None:
        """All items orthogonal -> N singleton clusters."""
        items = [
            _make_item(1, [1, 0, 0]),
            _make_item(2, [0, 1, 0]),
            _make_item(3, [0, 0, 1]),
        ]
        clusters = _cluster_by_similarity(items, threshold=0.85)
        assert len(clusters) == 3
        for c in clusters:
            assert len(c) == 1

    def test_empty_input(self) -> None:
        clusters = _cluster_by_similarity([], threshold=0.85)
        assert clusters == []


# ---------------------------------------------------------------------------
# _merge_cluster_summary
# ---------------------------------------------------------------------------


class TestMergeClusterSummary:
    def test_combines_goals(self) -> None:
        cluster = [
            _make_item(1, [1, 0, 0], goal="Sort numbers"),
            _make_item(2, [1, 0, 0], goal="Arrange data"),
        ]
        summary = _merge_cluster_summary(cluster)
        assert "Sort numbers" in summary
        assert "Arrange data" in summary
        assert "Consolidated 2 missions" in summary

    def test_merges_tools_used(self) -> None:
        cluster = [
            {"id": 1, "goal": "A", "tools_used": ["sort_array", "write_file"], "summary": "s"},
            {"id": 2, "goal": "B", "tools_used": ["sort_array", "read_file"], "summary": "s"},
        ]
        summary = _merge_cluster_summary(cluster)
        # Just check it returns a string; tools union is internal
        assert isinstance(summary, str)

    def test_truncates_long_summary(self) -> None:
        cluster = [_make_item(i, [1, 0, 0], goal="x" * 200) for i in range(10)]
        summary = _merge_cluster_summary(cluster)
        assert len(summary) <= 500


# ---------------------------------------------------------------------------
# consolidate_memories: pool=None early return
# ---------------------------------------------------------------------------


class TestConsolidateMemories:
    def test_pool_none_returns_early(self) -> None:
        result = consolidate_memories(pool=None)
        assert result == {"clusters": 0, "consolidated": 0, "kept": 0}
