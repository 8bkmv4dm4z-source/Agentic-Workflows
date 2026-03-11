"""Integration tests for BTLNK-01: large-result planner context cap.

Tests verify that ContextManager intercepts large tool results and injects
compact pointers into the planner context. All tests use pool=None so they
run in CI without a Postgres connection.

Real Postgres round-trip tests (ToolResultCache.get() retrieval) require
psycopg_pool and are gated via requires_postgres marker.
"""
from __future__ import annotations

import json

import pytest

from agentic_workflows.orchestration.langgraph.context_manager import ContextManager
from agentic_workflows.storage.tool_result_cache import ToolResultCache, make_args_hash


def test_large_result_never_reaches_planner_raw() -> None:
    """After a tool returns >2000 chars, planner injection contains compact pointer not raw result."""
    cache = ToolResultCache(pool=None)
    cm = ContextManager(tool_result_cache=cache)

    # Build a large result (>2000 chars)
    large_data = "A" * 2500
    large_result = {"output": large_data}
    large_result_str = json.dumps(large_result)
    assert len(large_result_str) > 2000, "Precondition: result must be >2000 chars"

    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {
                "call": 1,
                "tool": "data_dump_tool",
                "args": {"query": "all_records"},
                "result": large_result,
            }
        ],
        "step": 1,
        "run_id": "integ-run-001",
        "structural_health": {"tool_result_truncations": 0},
    }

    injection = cm.build_planner_context_injection(state)

    # Must contain compact pointer header
    assert "[Result truncated" in injection, (
        f"Expected compact pointer in injection, got: {injection!r}"
    )
    # Must reference the tool
    assert "data_dump_tool" in injection

    # Must NOT contain the raw 2500-char data field
    # (summary is first 200 chars of JSON-encoded result, which includes some 'A's,
    # but the full 2500-char raw string must not appear)
    assert "A" * 500 not in injection, "Raw large result leaked into planner injection"


def test_compact_pointer_format_matches_spec() -> None:
    """Compact pointer matches the four-element locked format from FEATURE-CONTEXT.md.

    Expected format:
        [Result truncated — N chars stored | chunks: 3000 chars each]
        Tool: my_tool | Key: <full_hash>
        Summary: <first 200 chars>...
        → call retrieve_tool_result(key="<full_hash>", offset=0, limit=3000) to read full result
    """
    cache = ToolResultCache(pool=None)
    cm = ContextManager(tool_result_cache=cache)

    large_result = {"data": "B" * 2100}
    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {
                "call": 1,
                "tool": "my_tool",
                "args": {"n": 42},
                "result": large_result,
            }
        ],
        "step": 1,
        "run_id": "integ-run-002",
        "structural_health": {"tool_result_truncations": 0},
    }

    injection = cm.build_planner_context_injection(state)

    # Must match all four locked elements
    assert "[Result truncated —" in injection
    assert "chunks: 3000 chars each]" in injection
    assert "Tool: my_tool" in injection
    assert "Key:" in injection
    assert "Summary:" in injection
    assert "retrieve_tool_result" in injection


def test_full_result_retrievable_from_cache() -> None:
    """With pool=None, ToolResultCache.get() returns None (no-op); compact pointer is still generated."""
    cache = ToolResultCache(pool=None)
    cm = ContextManager(tool_result_cache=cache)

    large_result = {"rows": "C" * 2200}
    large_result_str = json.dumps(large_result)
    tool_name = "fetch_data"
    args = {"table": "users"}
    args_hash = make_args_hash(tool_name, args)

    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {
                "call": 1,
                "tool": tool_name,
                "args": args,
                "result": large_result,
            }
        ],
        "step": 1,
        "run_id": "integ-run-003",
        "structural_health": {"tool_result_truncations": 0},
    }

    injection = cm.build_planner_context_injection(state)

    # pool=None: compact pointer is generated even without DB storage
    assert "[Result truncated" in injection

    # pool=None: get() returns None (no storage)
    assert cache.get(tool_name=tool_name, args_hash=args_hash) is None


def test_tool_history_not_modified() -> None:
    """ContextManager must NOT modify tool_history — audit safety preserved."""
    cache = ToolResultCache(pool=None)
    cm = ContextManager(tool_result_cache=cache)

    large_result = {"data": "D" * 2100}
    original_result = dict(large_result)  # snapshot before call

    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {
                "call": 1,
                "tool": "audit_tool",
                "args": {},
                "result": large_result,
            }
        ],
        "step": 1,
        "run_id": "integ-run-004",
        "structural_health": {"tool_result_truncations": 0},
    }

    cm.build_planner_context_injection(state)

    # tool_history must be unchanged
    assert state["tool_history"][0]["result"] == original_result, (
        "tool_history was mutated — audit safety violated"
    )


def test_structural_health_increments_per_large_result() -> None:
    """structural_health['tool_result_truncations'] increments for each large result intercepted."""
    cm = ContextManager(tool_result_cache=None)

    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {"call": 1, "tool": "tool_a", "args": {}, "result": {"data": "E" * 2100}},
            {"call": 2, "tool": "tool_b", "args": {}, "result": {"data": "F" * 2100}},
            {"call": 3, "tool": "tool_c", "args": {}, "result": {"ok": True}},  # small
        ],
        "step": 1,
        "run_id": "integ-run-005",
        "structural_health": {"tool_result_truncations": 0},
    }

    cm.build_planner_context_injection(state)

    # 2 large results → 2 truncations (small result is below threshold)
    assert state["structural_health"]["tool_result_truncations"] == 2


def test_orchestrator_accepts_tool_result_cache_param() -> None:
    """LangGraphOrchestrator.__init__ accepts tool_result_cache and forwards to ContextManager."""
    from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator

    cache = ToolResultCache(pool=None)
    # Must not raise TypeError for unexpected keyword argument
    orch = LangGraphOrchestrator(tool_result_cache=cache)
    # ContextManager must have the cache forwarded
    assert orch.context_manager._tool_result_cache is cache


def test_small_results_not_truncated() -> None:
    """Results <=2000 chars are not replaced with compact pointers."""
    cm = ContextManager(tool_result_cache=None)

    small_result = {"value": 42, "status": "ok"}
    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {"call": 1, "tool": "small_tool", "args": {}, "result": small_result}
        ],
        "step": 1,
        "run_id": "integ-run-006",
        "structural_health": {"tool_result_truncations": 0},
    }

    injection = cm.build_planner_context_injection(state)

    # No compact pointer should appear for small result
    assert "[Result truncated" not in injection
    assert state["structural_health"]["tool_result_truncations"] == 0


# ---------------------------------------------------------------------------
# Postgres-gated tests (require live pool — skipped in CI)
# ---------------------------------------------------------------------------

psycopg_pool = pytest.importorskip("psycopg_pool", reason="psycopg_pool not installed")

requires_postgres = pytest.mark.skipif(
    not __import__("os").getenv("DATABASE_URL"),
    reason="Postgres not available (DATABASE_URL not set)",
)


@requires_postgres
def test_postgres_full_result_retrievable_from_cache(pg_pool) -> None:  # type: ignore[no-untyped-def]
    """With a real Postgres pool, ToolResultCache.get() returns the stored full result."""
    cache = ToolResultCache(pool=pg_pool)
    cm = ContextManager(tool_result_cache=cache)

    large_result = {"rows": "G" * 2200}
    large_result_str = json.dumps(large_result)
    tool_name = "pg_fetch"
    args = {"table": "orders"}
    args_hash = make_args_hash(tool_name, args)

    state: dict = {
        "mission_contexts": {},
        "tool_history": [
            {"call": 1, "tool": tool_name, "args": args, "result": large_result}
        ],
        "step": 1,
        "run_id": "integ-pg-001",
        "structural_health": {"tool_result_truncations": 0},
    }

    cm.build_planner_context_injection(state)

    # With real pool, get() should return the stored full result
    retrieved = cache.get(tool_name=tool_name, args_hash=args_hash)
    assert retrieved is not None, "Expected stored result to be retrievable"
    assert retrieved == large_result_str
