"""Tests for prompt tier selection and compact system prompt — implemented in plan 07.6-01."""
from __future__ import annotations

import pytest

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator, _select_prompt_tier
from tests.conftest import ScriptedProvider


class TestSelectPromptTier:
    def test_compact_tier_for_small_context(self) -> None:
        """_select_prompt_tier(8192) returns 'compact'."""
        assert _select_prompt_tier(8192) == "compact"

    def test_compact_tier_boundary(self) -> None:
        """_select_prompt_tier(10000) returns 'compact' (at or below boundary)."""
        assert _select_prompt_tier(10000) == "compact"

    def test_full_tier_above_boundary(self) -> None:
        """_select_prompt_tier(10001) returns 'full' (above boundary)."""
        assert _select_prompt_tier(10001) == "full"

    def test_full_tier_for_large_context(self) -> None:
        """_select_prompt_tier(128000) returns 'full'."""
        assert _select_prompt_tier(128000) == "full"


class TestCompactPromptContent:
    def _make_compact_orchestrator(self) -> LangGraphOrchestrator:
        """Build an orchestrator that uses the compact tier (context_size <= 10000)."""

        class SmallProvider:
            """Fake provider with 8192 context — triggers compact tier."""

            def context_size(self) -> int:
                return 8192

            def generate(self, messages, response_schema=None):  # noqa: ANN001
                return '{"action":"finish","answer":"done"}'

        return LangGraphOrchestrator(provider=SmallProvider())  # type: ignore[arg-type]

    def _make_full_orchestrator(self) -> LangGraphOrchestrator:
        """Build an orchestrator that uses the full tier (ScriptedProvider = 32768)."""
        return LangGraphOrchestrator(
            provider=ScriptedProvider(responses=[{"action": "finish", "answer": "done"}])
        )

    def test_compact_prompt_excludes_arg_signatures(self) -> None:
        """System prompt in compact tier omits per-tool argument lines (no '- text_analysis:...')."""
        orchestrator = self._make_compact_orchestrator()
        # The full-tier prompt has detailed arg lines like '- text_analysis: ...'
        assert "- text_analysis:" not in orchestrator.system_prompt
        assert "- sort_array:" not in orchestrator.system_prompt

    def test_compact_prompt_includes_env_block(self) -> None:
        """Compact prompt contains 'python3 is available' env block."""
        orchestrator = self._make_compact_orchestrator()
        assert "python3 is available" in orchestrator.system_prompt

    def test_full_prompt_includes_env_block(self) -> None:
        """Full prompt contains 'python3 is available' env block."""
        orchestrator = self._make_full_orchestrator()
        assert "python3 is available" in orchestrator.system_prompt

    def test_compact_directive_in_compact_prompt(self) -> None:
        """Compact prompt contains text from the ## COMPACT section of supervisor.md."""
        orchestrator = self._make_compact_orchestrator()
        # The COMPACT section contains this phrase
        assert "Pure JSON only" in orchestrator.system_prompt
