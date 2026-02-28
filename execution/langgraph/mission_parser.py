from __future__ import annotations

"""Structured mission parser for Phase 1 orchestration.

Parses user input into an ordered plan of MissionSteps with sub-task
support, tool suggestions, and dependency inference.  Falls back to the
original regex extractor when structured parsing yields nothing.
"""

import queue
import re
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MissionStep:
    id: str                          # "1", "1a", "1.1", "2"
    description: str
    parent_id: str | None = None     # None for top-level
    suggested_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"          # pending | in_progress | completed | failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "parent_id": self.parent_id,
            "suggested_tools": list(self.suggested_tools),
            "dependencies": list(self.dependencies),
            "status": self.status,
        }


@dataclass
class StructuredPlan:
    steps: list[MissionStep]
    flat_missions: list[str]         # Backward-compat with existing missions list
    parsing_method: str              # "structured" | "regex_fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "flat_missions": list(self.flat_missions),
            "parsing_method": self.parsing_method,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StructuredPlan:
        steps = [
            MissionStep(
                id=s["id"],
                description=s["description"],
                parent_id=s.get("parent_id"),
                suggested_tools=s.get("suggested_tools", []),
                dependencies=s.get("dependencies", []),
                status=s.get("status", "pending"),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            steps=steps,
            flat_missions=data.get("flat_missions", []),
            parsing_method=data.get("parsing_method", "unknown"),
        )


# ---------------------------------------------------------------------------
# Keyword → tool heuristic map
# ---------------------------------------------------------------------------

_TOOL_KEYWORD_MAP: dict[str, list[str]] = {
    "sort": ["sort_array"],
    "order": ["sort_array"],
    "ascending": ["sort_array"],
    "descending": ["sort_array"],
    "repeat": ["repeat_message"],
    "echo": ["repeat_message"],
    "uppercase": ["string_ops"],
    "lowercase": ["string_ops"],
    "reverse": ["string_ops"],
    "trim": ["string_ops"],
    "replace": ["string_ops"],
    "split": ["string_ops"],
    "write": ["write_file"],
    "write_file": ["write_file"],
    "save": ["write_file"],
    "fibonacci": ["write_file", "math_stats"],
    "mean": ["math_stats"],
    "median": ["math_stats"],
    "sum": ["math_stats"],
    "add": ["math_stats"],
    "subtract": ["math_stats"],
    "multiply": ["math_stats"],
    "divide": ["math_stats"],
    "math": ["math_stats"],
    "calculate": ["math_stats"],
    "memoize": ["memoize"],
    "memo": ["memoize"],
    "retrieve": ["retrieve_memo"],
    "analyze": ["text_analysis", "data_analysis"],
    "analysis": ["text_analysis", "data_analysis"],
    "word_count": ["text_analysis"],
    "sentence_count": ["text_analysis"],
    "key_terms": ["text_analysis"],
    "complexity": ["text_analysis"],
    "statistics": ["data_analysis"],
    "stats": ["data_analysis"],
    "outlier": ["data_analysis"],
    "percentile": ["data_analysis"],
    "distribution": ["data_analysis"],
    "z_score": ["data_analysis"],
    "normalize": ["data_analysis"],
    "correlation": ["data_analysis"],
    "json": ["json_parser"],
    "parse": ["json_parser"],
    "validate": ["json_parser"],
    "flatten": ["json_parser"],
    "extract_keys": ["json_parser"],
    "regex": ["regex_matcher"],
    "pattern": ["regex_matcher"],
    "match": ["regex_matcher"],
    "find_all": ["regex_matcher"],
}


def parse_missions(user_input: str, timeout_seconds: float = 5.0) -> StructuredPlan:
    """Parse user input into a StructuredPlan.

    Tries structured parsing first, falls back to flat regex extraction.
    Protected by a hard timeout to prevent runaway parsing on huge inputs.
    """
    if timeout_seconds <= 0:
        return _parse_missions_inner(user_input)

    outbox: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            outbox.put(("ok", _parse_missions_inner(user_input)))
        except Exception as exc:  # noqa: BLE001
            outbox.put(("err", exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    try:
        kind, payload = outbox.get(timeout=timeout_seconds)
    except queue.Empty:
        return _build_fallback_plan(user_input)

    if kind == "err":
        return _build_fallback_plan(user_input)
    return payload


def _parse_missions_inner(user_input: str) -> StructuredPlan:
    """Core parsing logic without timeout wrapper."""
    lines = [line.rstrip() for line in user_input.splitlines()]

    # Try structured numbered tasks first
    steps = _parse_numbered_tasks(lines)
    if steps:
        _parse_nested_subtasks(lines, steps)
        _parse_multiline_descriptions(lines, steps)
        _suggest_tools_for_steps(steps)
        _detect_dependencies(steps)
        flat = _steps_to_flat_missions(steps)
        return StructuredPlan(steps=steps, flat_missions=flat, parsing_method="structured")

    # Try bullet list parsing
    steps = _parse_bullet_lists(lines)
    if steps:
        _suggest_tools_for_steps(steps)
        _detect_dependencies(steps)
        flat = _steps_to_flat_missions(steps)
        return StructuredPlan(steps=steps, flat_missions=flat, parsing_method="structured")

    # Fall back to regex
    return _build_fallback_plan(user_input)


def _parse_numbered_tasks(lines: list[str]) -> list[MissionStep]:
    """Handle `Task N:`, `N.`, `N)`, `N -` patterns for top-level tasks."""
    steps: list[MissionStep] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Task N: ...
        m = re.match(r"^[Tt]ask\s*(\d+)\s*:\s*(.+)", stripped)
        if m:
            steps.append(MissionStep(id=m.group(1), description=m.group(2).strip()))
            continue
        # N. ... or N) ... or N - ... or N: ...
        m = re.match(r"^(\d+)\s*[\)\.:\-]\s+(.+)", stripped)
        if m:
            steps.append(MissionStep(id=m.group(1), description=m.group(2).strip()))
            continue
    return steps


def _parse_bullet_lists(lines: list[str]) -> list[MissionStep]:
    """Handle `- `, `* `, `+ ` bullet patterns."""
    steps: list[MissionStep] = []
    counter = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^[-*+]\s+(.+)", stripped)
        if m:
            counter += 1
            steps.append(MissionStep(id=str(counter), description=m.group(1).strip()))
    return steps


def _parse_nested_subtasks(lines: list[str], parent_steps: list[MissionStep]) -> None:
    """Detect indented sub-task lines and attach them as children.

    Recognizes patterns like:
      - `1a.`, `1b.`, `2a)`, etc.  (letter-suffixed sub-IDs)
      - `1.1`, `1.2`, `2.1`, etc.  (dot-notation sub-IDs)
      - 2+ space indented lines under a parent
    """
    parent_ids = {s.id for s in parent_steps}
    subtask_re = re.compile(
        r"^\s+"                          # leading whitespace (indent)
        r"(?:"
        r"(\d+)([a-z])\s*[\.\):\-]\s*"  # "1a." or "1a)" etc.
        r"|"
        r"(\d+)\.(\d+)\s*[\.\):\-]?\s*" # "1.1" or "1.1." etc.
        r")"
        r"(.+)",                         # description
        re.IGNORECASE,
    )
    for line in lines:
        m = subtask_re.match(line)
        if not m:
            continue
        if m.group(1) and m.group(2):
            parent_id = m.group(1)
            sub_id = f"{m.group(1)}{m.group(2)}"
            desc = m.group(5).strip()
        elif m.group(3) and m.group(4):
            parent_id = m.group(3)
            sub_id = f"{m.group(3)}.{m.group(4)}"
            desc = m.group(5).strip()
        else:
            continue

        if parent_id not in parent_ids:
            continue
        # Avoid duplicates
        if any(s.id == sub_id for s in parent_steps):
            continue
        parent_steps.append(
            MissionStep(id=sub_id, description=desc, parent_id=parent_id)
        )


def _parse_multiline_descriptions(lines: list[str], steps: list[MissionStep]) -> None:
    """Merge indented continuation lines that don't match any task/subtask pattern into prior step."""
    task_pattern = re.compile(
        r"^\s*(?:[Tt]ask\s*\d+\s*:|"    # Task N:
        r"\d+\s*[\)\.:\-]\s|"           # N. or N) etc.
        r"\d+[a-z]\s*[\.\):\-]|"        # 1a. etc.
        r"\d+\.\d+\s*[\.\):\-]?|"       # 1.1 etc.
        r"[-*+]\s)"                       # bullets
    )
    current_step: MissionStep | None = None
    step_by_line: dict[int, MissionStep] = {}

    # Map each step to its line index
    for li, line in enumerate(lines):
        stripped = line.strip()
        for step in steps:
            if step.description and stripped.endswith(step.description):
                step_by_line[li] = step
                current_step = step
                break

    for li, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            current_step = None
            continue
        if li in step_by_line:
            current_step = step_by_line[li]
            continue
        if task_pattern.match(line):
            continue
        # Continuation line: indented, not a task pattern
        if line.startswith("  ") or line.startswith("\t"):
            if current_step:
                current_step.description += " " + stripped


def _suggest_tools_for_steps(steps: list[MissionStep]) -> None:
    """Apply keyword heuristic to suggest tools for each step."""
    for step in steps:
        _suggest_tools_for_step(step)


def _suggest_tools_for_step(step: MissionStep) -> None:
    """Keyword heuristic mapping from step description to tool names."""
    desc_lower = step.description.lower()
    suggested: list[str] = []
    for keyword, tools in _TOOL_KEYWORD_MAP.items():
        if keyword in desc_lower:
            for tool in tools:
                if tool not in suggested:
                    suggested.append(tool)
    step.suggested_tools = suggested


def _detect_dependencies(steps: list[MissionStep]) -> None:
    """Infer sequential dependencies from step references and parent-child.

    Sub-tasks depend on earlier siblings under the same parent.
    Top-level tasks are implicitly sequential (1 before 2, etc.).
    """
    parent_children: dict[str | None, list[MissionStep]] = {}
    for step in steps:
        parent_children.setdefault(step.parent_id, []).append(step)

    for parent_id, children in parent_children.items():
        for i, child in enumerate(children):
            if i > 0:
                child.dependencies.append(children[i - 1].id)
            if child.parent_id and child.parent_id not in child.dependencies:
                # First child of a parent depends on the parent
                if i == 0:
                    child.dependencies.append(child.parent_id)


def _steps_to_flat_missions(steps: list[MissionStep]) -> list[str]:
    """Convert steps into flat mission strings for backward compat.

    Only top-level steps become flat missions (sub-tasks are implicit).
    """
    flat: list[str] = []
    for step in steps:
        if step.parent_id is None:
            # Reconstruct "Task N: description" format
            flat.append(f"Task {step.id}: {step.description}")
    return flat if flat else [s.description for s in steps]


def _build_fallback_plan(user_input: str) -> StructuredPlan:
    """Use the original regex extraction as fallback."""
    missions = _extract_missions_regex_fallback(user_input)
    steps = [
        MissionStep(id=str(i + 1), description=m)
        for i, m in enumerate(missions)
    ]
    _suggest_tools_for_steps(steps)
    return StructuredPlan(steps=steps, flat_missions=missions, parsing_method="regex_fallback")


def _extract_missions_regex_fallback(user_input: str) -> list[str]:
    """Exact copy of the original graph.py:946-958 regex logic."""
    lines = [line.strip() for line in user_input.splitlines() if line.strip()]
    task_lines: list[str] = []
    for line in lines:
        if re.match(r"^(task\s*\d+\s*:)", line, flags=re.IGNORECASE):
            task_lines.append(line)
            continue
        if re.match(r"^\d+[\)\.:\-\s]", line):
            task_lines.append(line)
    if task_lines:
        return task_lines
    return ["Primary mission"]
