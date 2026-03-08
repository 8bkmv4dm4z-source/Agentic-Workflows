"""Structural tests for storage protocol ABCs — ensures importability and runtime_checkable."""
from __future__ import annotations

from agentic_workflows.storage.checkpoint_protocol import CheckpointStore
from agentic_workflows.storage.memo_protocol import MemoStore
from agentic_workflows.storage.protocol import RunStore


def test_checkpoint_store_is_runtime_checkable():
    # Anything can be checked; non-implementing class returns False
    assert not isinstance(object(), CheckpointStore)


def test_memo_store_is_runtime_checkable():
    assert not isinstance(object(), MemoStore)


def test_run_store_is_runtime_checkable():
    assert not isinstance(object(), RunStore)


def test_checkpoint_store_concrete_satisfies_protocol():
    from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
    store = SQLiteCheckpointStore(db_path=":memory:")
    assert isinstance(store, CheckpointStore)


def test_memo_store_concrete_satisfies_protocol():
    from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
    store = SQLiteMemoStore(db_path=":memory:")
    assert isinstance(store, MemoStore)
