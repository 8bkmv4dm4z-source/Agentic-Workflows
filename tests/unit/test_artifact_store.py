"""Tests for ArtifactStore.
Covers SCS-07 from VALIDATION.md.
"""
from agentic_workflows.storage.artifact_store import ArtifactStore


class TestArtifactStoreFallback:
    def test_upsert_no_conn(self):
        store = ArtifactStore(pool=None)
        # Must not raise when pool is None
        store.upsert(
            run_id="run-1",
            mission_id="m-1",
            key="output_file",
            value="file content here",
            source_tool="write_file",
            embedding=[0.0] * 384,
        )

    def test_search_no_conn(self):
        store = ArtifactStore(pool=None)
        results = store.search(embedding=[0.0] * 384, limit=5)
        assert results == []
