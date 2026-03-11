"""Unit tests for LangGraphOrchestrator wiring of embedding_provider + mission_context_store.

Phase 07.3 Plan 06 — SCS-12: Verify that the two new optional keyword-only params
are forwarded from LangGraphOrchestrator.__init__ to ContextManager.

SC-2 (Phase 07.5 Plan 02): artifact_store constructor wiring tests.
"""
from unittest.mock import MagicMock, patch

import pytest

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator


@pytest.fixture(autouse=True)
def _mock_build_provider():
    """Prevent build_provider() from reading P1_PROVIDER env in CI (e.g. 'scripted')."""
    mock_provider = MagicMock()
    mock_provider.context_size.return_value = 8192
    with patch(
        "agentic_workflows.orchestration.langgraph.graph.build_provider",
        return_value=mock_provider,
    ):
        yield


class TestLangGraphOrchestratorWiring:
    """Tests for embedding_provider + mission_context_store forwarding."""

    def test_zero_args_instantiation(self):
        """LangGraphOrchestrator() with no args must still work (backward compat)."""
        o = LangGraphOrchestrator()
        assert o.context_manager is not None

    def test_none_defaults_equivalent(self):
        """Passing None explicitly must be equivalent to zero-arg instantiation."""
        o = LangGraphOrchestrator(embedding_provider=None, mission_context_store=None)
        assert o.context_manager._store is None
        assert o.context_manager._embedding_provider is None

    def test_embedding_provider_forwarded_to_context_manager(self):
        """embedding_provider passed to __init__ must reach context_manager._embedding_provider."""
        mock_provider = MagicMock()
        o = LangGraphOrchestrator(embedding_provider=mock_provider)
        assert o.context_manager._embedding_provider is mock_provider

    def test_mission_context_store_forwarded_to_context_manager(self):
        """mission_context_store passed to __init__ must reach context_manager._store."""
        mock_store = MagicMock()
        o = LangGraphOrchestrator(mission_context_store=mock_store)
        assert o.context_manager._store is mock_store

    def test_both_params_forwarded_together(self):
        """Both params passed together must both be forwarded."""
        mock_provider = MagicMock()
        mock_store = MagicMock()
        o = LangGraphOrchestrator(
            embedding_provider=mock_provider,
            mission_context_store=mock_store,
        )
        assert o.context_manager._embedding_provider is mock_provider
        assert o.context_manager._store is mock_store

    def test_instance_attributes_stored(self):
        """Both values are also stored as instance attributes on the orchestrator."""
        mock_provider = MagicMock()
        mock_store = MagicMock()
        o = LangGraphOrchestrator(
            embedding_provider=mock_provider,
            mission_context_store=mock_store,
        )
        assert o._embedding_provider is mock_provider
        assert o._mission_context_store is mock_store


# ---------------------------------------------------------------------------
# SC-2: artifact_store wiring (RED stubs — added in Phase 07.5 Plan 02)
# These tests fail RED before Task 2 adds artifact_store param to __init__.
# ---------------------------------------------------------------------------


def test_orchestrator_accepts_artifact_store_none():
    """LangGraphOrchestrator(artifact_store=None) must not raise (backward compat)."""
    orchestrator = LangGraphOrchestrator(artifact_store=None)
    assert orchestrator.context_manager._artifact_store is None


def test_orchestrator_forwards_artifact_store():
    """artifact_store passed to orchestrator must reach context_manager._artifact_store."""
    mock_store = MagicMock()
    orchestrator = LangGraphOrchestrator(artifact_store=mock_store)
    assert orchestrator.context_manager._artifact_store is mock_store
