"""Tests for proactive context compaction before planner LLM calls.

Phase 7.8 stabilization: prevents exceed_context_size_error by compacting
messages when estimated tokens approach 80% of provider ctx_limit.
"""

from __future__ import annotations

from agentic_workflows.orchestration.langgraph.context_manager import ContextManager


def _make_msg(role: str, content: str) -> dict:
    return {"role": role, "content": content}


class TestProactiveCompact:
    def test_triggers_when_over_80_percent(self) -> None:
        """proactive_compact() should reduce messages when tokens > 80% of ctx_limit."""
        cm = ContextManager(sliding_window_cap=50)
        # Each message ~250 chars = ~62 tokens. 20 messages = ~1250 tokens.
        # ctx_limit=1500 -> threshold=1200. 1250 > 1200 -> should trigger.
        messages = [_make_msg("system", "system prompt")] + [
            _make_msg("user", "x" * 250) for _ in range(20)
        ]
        state: dict = {"messages": messages, "policy_flags": {}, "step": 5}
        original_count = len(state["messages"])
        cm.proactive_compact(state, ctx_limit=1500)
        # Should have fewer messages after compaction
        assert len(state["messages"]) < original_count

    def test_no_op_when_under_threshold(self) -> None:
        """proactive_compact() should not modify messages when under 80% threshold."""
        cm = ContextManager(sliding_window_cap=50)
        # 3 messages ~60 tokens. ctx_limit=10000 -> threshold=8000. No trigger.
        messages = [
            _make_msg("system", "system prompt"),
            _make_msg("user", "hello"),
            _make_msg("assistant", "hi there"),
        ]
        state: dict = {"messages": list(messages), "policy_flags": {}, "step": 2}
        cm.proactive_compact(state, ctx_limit=10000)
        assert len(state["messages"]) == 3

    def test_aggressive_compaction_on_very_large_messages(self) -> None:
        """proactive_compact() aggressively compacts when sliding window is not enough."""
        cm = ContextManager(sliding_window_cap=100)  # high cap won't trigger standard compact
        # 50 messages of 500 chars each = ~6250 tokens
        # ctx_limit=2000 -> threshold=1600. Way over.
        messages = [_make_msg("system", "system prompt")] + [
            _make_msg("user", "y" * 500) for _ in range(50)
        ]
        state: dict = {"messages": messages, "policy_flags": {}, "step": 10}
        cm.proactive_compact(state, ctx_limit=2000)
        # Aggressive compaction keeps system + 5 non-system messages
        assert len(state["messages"]) <= 6

    def test_no_crash_when_still_over_limit(self) -> None:
        """proactive_compact() logs warning but does not crash when messages still exceed limit."""
        cm = ContextManager(sliding_window_cap=100)
        # Even 5 messages of 5000 chars each = ~6250 tokens > ctx_limit=100
        messages = [_make_msg("system", "s" * 5000)] + [
            _make_msg("user", "z" * 5000) for _ in range(5)
        ]
        state: dict = {"messages": messages, "policy_flags": {}, "step": 1}
        # Should not raise -- graceful degradation
        cm.proactive_compact(state, ctx_limit=100)
        # Still has messages (didn't crash)
        assert len(state["messages"]) > 0
