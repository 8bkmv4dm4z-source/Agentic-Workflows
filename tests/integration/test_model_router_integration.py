"""Integration tests: end-to-end routing verification with dual provider stubs.

These tests run LangGraphOrchestrator.run() end-to-end with scripted providers
(no live LLM calls) and verify that:
- Planning calls hit the strong provider when two providers are configured
- Single-provider mode works unchanged with has_dual_providers=False
- Cloud fallback triggers on ProviderTimeoutError when fallback_provider is set
- Cloud fallback failure falls through to deterministic fallback
- Routing decisions tracked in structural_health
"""
from __future__ import annotations

import json
import tempfile

from agentic_workflows.orchestration.langgraph.checkpoint_store import SQLiteCheckpointStore
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from agentic_workflows.orchestration.langgraph.memo_store import SQLiteMemoStore
from agentic_workflows.orchestration.langgraph.provider import ProviderTimeoutError


class TrackedScriptedProvider:
    """ScriptedProvider that records how many times generate() was called."""

    def __init__(self, responses: list[dict], name: str = "") -> None:  # type: ignore[type-arg]
        self._responses = [json.dumps(r) for r in responses]
        self._index = 0
        self.name = name
        self.call_count = 0

    def context_size(self) -> int:
        return 32768

    def generate(self, messages: list[dict], response_schema: dict | None = None) -> str:  # type: ignore[type-arg]
        self.call_count += 1
        value = self._responses[min(self._index, len(self._responses) - 1)]
        self._index += 1
        return value


class TimeoutProvider:
    """Provider that always raises ProviderTimeoutError."""

    def __init__(self) -> None:
        self.call_count = 0

    def context_size(self) -> int:
        return 32768

    def generate(self, messages: list[dict], response_schema: dict | None = None) -> str:  # type: ignore[type-arg]
        self.call_count += 1
        raise ProviderTimeoutError("simulated timeout")


class FailingFallbackProvider:
    """Fallback provider that always raises an exception."""

    def __init__(self) -> None:
        self.call_count = 0

    def context_size(self) -> int:
        return 32768

    def generate(self, messages: list[dict], response_schema: dict | None = None) -> str:  # type: ignore[type-arg]
        self.call_count += 1
        raise RuntimeError("cloud provider also failed")


def _make_orchestrator(provider, *, fast_provider=None, fallback_provider=None, max_steps=10) -> LangGraphOrchestrator:
    """Create orchestrator with temp stores."""
    tmp_dir = tempfile.mkdtemp()
    return LangGraphOrchestrator(
        provider=provider,
        fast_provider=fast_provider,
        fallback_provider=fallback_provider,
        memo_store=SQLiteMemoStore(f"{tmp_dir}/memo.db"),
        checkpoint_store=SQLiteCheckpointStore(f"{tmp_dir}/checkpoints.db"),
        max_steps=max_steps,
        plan_call_timeout_seconds=0,  # Disable thread wrapper for deterministic testing
    )


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


# --- Cloud fallback integration tests ---


def test_cloud_fallback_on_timeout() -> None:
    """ProviderTimeoutError triggers cloud fallback; structural_health counters increment."""
    primary = TimeoutProvider()
    fallback = TrackedScriptedProvider(
        [{"action": "finish", "answer": "cloud recovered"}],
        name="cloud_fallback",
    )
    orch = _make_orchestrator(primary, fallback_provider=fallback, max_steps=5)
    result = orch.run("Do something.")
    sh = result["state"]["structural_health"]
    assert sh["cloud_fallback_count"] >= 1, (
        f"Expected cloud_fallback_count >= 1; got {sh['cloud_fallback_count']}"
    )
    assert sh["local_model_failures"]["timeout"] >= 1, (
        f"Expected local_model_failures.timeout >= 1; got {sh['local_model_failures']}"
    )
    assert fallback.call_count >= 1, "Fallback provider should have been called"


def test_no_fallback_provider_timeout_deterministic() -> None:
    """No fallback_provider (None): timeout falls through to deterministic fallback."""
    primary = TimeoutProvider()
    orch = _make_orchestrator(primary, fallback_provider=None, max_steps=5)
    result = orch.run("Do something.")
    sh = result["state"]["structural_health"]
    # Should still track the timeout failure
    assert sh["local_model_failures"]["timeout"] >= 1, (
        f"Expected timeout tracking; got {sh['local_model_failures']}"
    )
    # No cloud fallback should have occurred
    assert sh["cloud_fallback_count"] == 0, (
        f"Expected cloud_fallback_count == 0 (no fallback provider); got {sh['cloud_fallback_count']}"
    )


def test_cloud_fallback_also_fails() -> None:
    """Primary raises timeout, fallback also fails: deterministic fallback still works."""
    primary = TimeoutProvider()
    fallback = FailingFallbackProvider()
    orch = _make_orchestrator(primary, fallback_provider=fallback, max_steps=5)
    result = orch.run("Do something.")
    sh = result["state"]["structural_health"]
    # Fallback was attempted but failed
    assert fallback.call_count >= 1, "Fallback provider should have been attempted"
    # No successful cloud fallback
    assert sh["cloud_fallback_count"] == 0, (
        f"Expected cloud_fallback_count == 0 (fallback also failed); got {sh['cloud_fallback_count']}"
    )
    # Timeout still tracked
    assert sh["local_model_failures"]["timeout"] >= 1, (
        f"Expected timeout tracking; got {sh['local_model_failures']}"
    )


def test_routing_decisions_tracked() -> None:
    """routing_decisions tracks strong/fast split in structural_health."""
    strong = TrackedScriptedProvider(
        [{"action": "finish", "answer": "done"}],
        name="strong",
    )
    fast = TrackedScriptedProvider(
        [{"action": "finish", "answer": "done"}],
        name="fast",
    )
    orch = _make_orchestrator(strong, fast_provider=fast, max_steps=10)
    result = orch.run("Simple task.")
    sh = result["state"]["structural_health"]
    routing = sh["routing_decisions"]
    total = routing.get("strong", 0) + routing.get("fast", 0)
    assert total > 0, (
        f"Expected at least one routing decision recorded; got {routing}"
    )
