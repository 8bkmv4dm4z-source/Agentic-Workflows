from __future__ import annotations

"""Typed specialist directive configs for runtime routing and tool scopes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SpecialistName = Literal["supervisor", "executor", "evaluator"]

_DIRECTIVE_DIR = Path(__file__).resolve().parents[2] / "directives"


@dataclass(frozen=True, slots=True)
class DirectiveConfig:
    """Runtime metadata for one specialist directive contract."""

    name: SpecialistName
    markdown_path: Path
    allowed_tools: frozenset[str]
    description: str

    def load_markdown(self) -> str:
        return self.markdown_path.read_text(encoding="utf-8")


EXECUTOR_TOOLS = frozenset(
    {
        "repeat_message",
        "sort_array",
        "string_ops",
        "math_stats",
        "write_file",
        "memoize",
        "retrieve_memo",
        "task_list_parser",
        "text_analysis",
        "data_analysis",
        "json_parser",
        "regex_matcher",
        # Phase 4.7 additions
        "parse_code_structure",
        "describe_db_schema",
        # Phase 5 additions
        "read_file",
        "run_bash",
        "http_request",
        "datetime_ops",
        "extract_table",
        "fill_template",
        "hash_content",
        "query_db",
        "recognize_pattern",
        "clear_context",
        "update_file_section",
        # Phase 6 additions
        "list_directory",
        "search_files",
        "search_content",
        "summarize_text",
        "compare_texts",
        "classify_intent",
        "format_converter",
        "file_manager",
        "encode_decode",
        "validate_data",
        "retrieve_run_context",
    }
)

EVALUATOR_TOOLS = frozenset(
    {
        "retrieve_memo",
        "text_analysis",
        "data_analysis",
        "json_parser",
        "regex_matcher",
        # Phase 6 additions (read-only tools)
        "summarize_text",
        "compare_texts",
        "classify_intent",
        "encode_decode",
        "validate_data",
        "retrieve_run_context",
    }
)

SUPERVISOR_TOOLS = frozenset(EXECUTOR_TOOLS | {"audit_run"})

SUPERVISOR_DIRECTIVE = DirectiveConfig(
    name="supervisor",
    markdown_path=_DIRECTIVE_DIR / "supervisor.md",
    allowed_tools=SUPERVISOR_TOOLS,
    description="Planning and lifecycle management specialist.",
)

EXECUTOR_DIRECTIVE = DirectiveConfig(
    name="executor",
    markdown_path=_DIRECTIVE_DIR / "executor.md",
    allowed_tools=EXECUTOR_TOOLS,
    description="Deterministic tool execution specialist.",
)

EVALUATOR_DIRECTIVE = DirectiveConfig(
    name="evaluator",
    markdown_path=_DIRECTIVE_DIR / "evaluator.md",
    allowed_tools=EVALUATOR_TOOLS,
    description="Read-only validation and audit specialist.",
)

DIRECTIVE_BY_SPECIALIST: dict[SpecialistName, DirectiveConfig] = {
    "supervisor": SUPERVISOR_DIRECTIVE,
    "executor": EXECUTOR_DIRECTIVE,
    "evaluator": EVALUATOR_DIRECTIVE,
}


def role_tool_scopes() -> dict[str, list[str]]:
    """Return deterministic sorted tool scopes keyed by specialist role."""
    return {
        role: sorted(config.allowed_tools) for role, config in DIRECTIVE_BY_SPECIALIST.items()
    }
