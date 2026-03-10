"""Tests for prompt tier selection, compact system prompt, few-shot examples, and token budgets."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator, _select_prompt_tier
from tests.conftest import ScriptedProvider

# Resolve directives directory relative to this test file
_DIRECTIVES_DIR = Path(__file__).resolve().parents[2] / "src" / "agentic_workflows" / "directives"


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


class TestDirectiveFewShotSections:
    """Test that directives contain required ## FEW_SHOT and ## COMPACT sections."""

    def _read_directive(self, name: str) -> str:
        path = _DIRECTIVES_DIR / f"{name}.md"
        return path.read_text(encoding="utf-8")

    def test_supervisor_has_few_shot_section(self) -> None:
        text = self._read_directive("supervisor")
        assert "## FEW_SHOT" in text

    def test_executor_has_compact_section(self) -> None:
        text = self._read_directive("executor")
        assert "## COMPACT" in text

    def test_executor_has_few_shot_section(self) -> None:
        text = self._read_directive("executor")
        assert "## FEW_SHOT" in text

    def test_evaluator_has_compact_section(self) -> None:
        text = self._read_directive("evaluator")
        assert "## COMPACT" in text

    def test_evaluator_has_few_shot_section(self) -> None:
        text = self._read_directive("evaluator")
        assert "## FEW_SHOT" in text

    def test_each_few_shot_has_at_least_2_json_examples(self) -> None:
        """Each FEW_SHOT section contains at least 2 JSON action examples."""
        for name in ("supervisor", "executor", "evaluator"):
            text = self._read_directive(name)
            # Extract FEW_SHOT section
            in_section = False
            section_lines: list[str] = []
            for line in text.splitlines():
                if line.strip() == "## FEW_SHOT":
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    break
                if in_section:
                    section_lines.append(line)
            section_text = "\n".join(section_lines)
            # Count JSON action objects ({"action":...)
            action_count = section_text.count('"action"')
            assert action_count >= 2, f"{name}.md FEW_SHOT has {action_count} action examples, need >= 2"

    def test_supervisor_few_shot_has_store_then_query_pattern(self) -> None:
        """Supervisor FEW_SHOT includes outline_code -> read_file_chunk -> write_file pattern."""
        text = self._read_directive("supervisor")
        in_section = False
        section_lines: list[str] = []
        for line in text.splitlines():
            if line.strip() == "## FEW_SHOT":
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section:
                section_lines.append(line)
        section_text = "\n".join(section_lines)
        assert "outline_code" in section_text
        assert "read_file_chunk" in section_text
        assert "write_file" in section_text
