"""Shared test fixtures for the agentic-workflows test suite."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory that is cleaned up after the test."""
    return tmp_path


@pytest.fixture
def memo_store(tmp_path: Path) -> SQLiteMemoStore:
    """Provide a fresh SQLiteMemoStore backed by a temp database."""
    return SQLiteMemoStore(db_path=str(tmp_path / "memo.db"))


@pytest.fixture
def checkpoint_store(tmp_path: Path) -> SQLiteCheckpointStore:
    """Provide a fresh SQLiteCheckpointStore backed by a temp database."""
    return SQLiteCheckpointStore(db_path=str(tmp_path / "checkpoints.db"))


class ScriptedProvider:
    """Test provider that returns pre-scripted JSON responses."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self._index = 0

    def generate(self, messages):  # noqa: ANN001
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]
