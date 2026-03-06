"""Integration tests: end-to-end routing verification with dual provider stubs.

These tests run LangGraphOrchestrator.run() end-to-end with scripted providers
(no live LLM calls) and verify that:
- Planning calls hit the strong provider when two providers are configured
- Single-provider mode works unchanged with has_dual_providers=False
"""
from __future__ import annotations

import json

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator


class TrackedScriptedProvider:
    """ScriptedProvider that records how many times generate() was called."""

    def __init__(self, responses: list[dict], name: str = "") -> None:  # type: ignore[type-arg]
        self._responses = [json.dumps(r) for r in responses]
        self._index = 0
        self.name = name
        self.call_count = 0

    def generate(self, messages: list[dict]) -> str:  # type: ignore[type-arg]
        self.call_count += 1
        value = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return value


def test_strong_provider_called_for_planning() -> None:
    """Strong provider must receive at least one call in a dual-provider end-to-end run."""
    strong = TrackedScriptedProvider(
        [{"action": "finish", "answer": "done"}],
        name="strong",
    )
    fast = TrackedScriptedProvider(
        [{"action": "finish", "answer": "done"}],
        name="fast",
    )
    orch = LangGraphOrchestrator(provider=strong, fast_provider=fast, max_steps=10)
    assert orch._router.has_dual_providers, "Expected dual providers"
    orch.run("Simple task")
    assert strong.call_count > 0, (
        f"Strong provider was never called (call_count={strong.call_count}). "
        "Planning calls should route to the strong provider."
    )


def test_single_provider_mode_unchanged() -> None:
    """Single-provider mode: has_dual_providers=False; provider receives all calls."""
    provider = TrackedScriptedProvider(
        [{"action": "finish", "answer": "done"}],
        name="only",
    )
    orch = LangGraphOrchestrator(provider=provider, max_steps=10)
    assert not orch._router.has_dual_providers, "Expected single-provider mode"
    orch.run("Simple task")
    assert provider.call_count > 0, "Provider was never called"
