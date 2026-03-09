"""Wave 0 stub tests for prompt tier selection and compact system prompt.

All tests raise NotImplementedError — RED state until plan 07.6-01 implements
_select_prompt_tier() and compact prompt generation.
"""
from __future__ import annotations

import pytest

# Try to import _select_prompt_tier — it does not exist yet; tests will raise NotImplementedError
try:
    from agentic_workflows.orchestration.langgraph.graph import _select_prompt_tier  # noqa: F401
    _SELECT_PROMPT_TIER_MISSING = False
except (ImportError, AttributeError):
    _SELECT_PROMPT_TIER_MISSING = True

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from tests.conftest import ScriptedProvider


class TestSelectPromptTier:
    def test_compact_tier_for_small_context(self) -> None:
        """_select_prompt_tier(8192) returns 'compact'."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_compact_tier_boundary(self) -> None:
        """_select_prompt_tier(10000) returns 'compact' (at or below boundary)."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_full_tier_above_boundary(self) -> None:
        """_select_prompt_tier(10001) returns 'full' (above boundary)."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_full_tier_for_large_context(self) -> None:
        """_select_prompt_tier(128000) returns 'full'."""
        raise NotImplementedError("stub — implement in plan 07.6-01")


class TestCompactPromptContent:
    def test_compact_prompt_excludes_arg_signatures(self) -> None:
        """System prompt in compact tier omits per-tool argument lines."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_compact_prompt_includes_env_block(self) -> None:
        """Compact prompt contains 'python3 is available' env block."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_full_prompt_includes_env_block(self) -> None:
        """Full prompt contains 'python3 is available' env block."""
        raise NotImplementedError("stub — implement in plan 07.6-01")

    def test_compact_directive_in_compact_prompt(self) -> None:
        """Compact prompt contains '## COMPACT' section text."""
        raise NotImplementedError("stub — implement in plan 07.6-01")
