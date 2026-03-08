"""Unit tests for LangGraphOrchestrator wiring of embedding_provider + mission_context_store.

Phase 07.3 Plan 06 — SCS-12: Verify that the two new optional keyword-only params
are forwarded from LangGraphOrchestrator.__init__ to ContextManager.
"""
from unittest.mock import MagicMock

import pytest

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator


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
