from __future__ import annotations

"""Structured mission parser for Phase 1 orchestration.

Parses user input into an ordered plan of MissionSteps with sub-task
support, tool suggestions, and dependency inference.  Falls back to the
original regex extractor when structured parsing yields nothing.
"""

import json
import os
import queue
import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agentic_workflows.logger import get_logger

if TYPE_CHECKING:
    from agentic_workflows.orchestration.langgraph.provider import ChatProvider

LOGGER = get_logger("langgraph.mission_parser")

# Tools that indicate complex missions requiring the strong model
_COMPLEX_TOOLS: set[str] = {
    "data_analysis",
    "outline_code",
    "read_file_chunk",
    "run_bash",
    "http_request",
}


@dataclass
class IntentClassification:
    """Classification of a mission's complexity and type.

    Used by ModelRouter to decide strong vs fast provider routing.
    """

    complexity: str  # "simple" | "complex"
    mission_type: str  # "file_io", "computation", "analysis", "multi_step", "tool_call"
    confidence: float  # 0.0-1.0
    source: str  # "llm" | "deterministic_fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "complexity": self.complexity,
            "mission_type": self.mission_type,
            "confidence": self.confidence,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentClassification:
        return cls(
            complexity=data["complexity"],
            mission_type=data["mission_type"],
            confidence=data.get("confidence", 0.5),
            source=data.get("source", "unknown"),
        )


@dataclass
class MissionStep:
    id: str  # "1", "1a", "1.1", "2"
    description: str
    parent_id: str | None = None  # None for top-level
    suggested_tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | in_progress | completed | failed

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
    flat_missions: list[str]  # Backward-compat with existing missions list
    parsing_method: str  # "structured" | "regex_fallback"
    intent_classification: IntentClassification | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": [step.to_dict() for step in self.steps],
            "flat_missions": list(self.flat_missions),
            "parsing_method": self.parsing_method,
            "intent_classification": self.intent_classification.to_dict()
            if self.intent_classification
            else None,
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
        ic_data = data.get("intent_classification")
        intent = IntentClassification.from_dict(ic_data) if ic_data else None
        return cls(
            steps=steps,
            flat_missions=data.get("flat_missions", []),
            parsing_method=data.get("parsing_method", "unknown"),
            intent_classification=intent,
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
    "validate": ["json_parser", "validate_data"],
    "flatten": ["json_parser"],
    "extract_keys": ["json_parser"],
    "regex": ["regex_matcher"],
    "pattern": ["regex_matcher"],
    "match": ["regex_matcher"],
    "find_all": ["regex_matcher"],
    "functions": ["outline_code"],
    "classes": ["outline_code"],
    "imports": ["outline_code"],
    "code": ["outline_code"],
    "schema": ["describe_db_schema", "validate_data"],
    "database": ["describe_db_schema"],
    "sqlite": ["describe_db_schema"],
    "csv": ["describe_db_schema", "format_converter"],
    "db": ["describe_db_schema"],
    # Phase 6: filesystem search & navigation
    "list": ["list_directory"],
    "directory": ["list_directory"],
    "ls": ["list_directory"],
    "folder": ["list_directory"],
    "search": ["search_files", "search_content"],
    "find": ["search_files", "search_content"],
    "glob": ["search_files"],
    "locate": ["search_files"],
    "grep": ["search_content"],
    # Phase 6: comprehension & analysis
    "summarize": ["summarize_text"],
    "condense": ["summarize_text"],
    "tldr": ["summarize_text"],
    "compare": ["compare_texts"],
    "diff": ["compare_texts"],
    "difference": ["compare_texts"],
    "similarity": ["compare_texts"],
    "intent": ["classify_intent"],
    "classify": ["classify_intent"],
    "categorize": ["classify_intent"],
    # Phase 6: format conversion
    "convert": ["format_converter"],
    "yaml": ["format_converter"],
    "toml": ["format_converter"],
    "ini": ["format_converter"],
    "format": ["format_converter"],
    # Phase 6: file management
    "copy": ["file_manager"],
    "move": ["file_manager"],
    "rename": ["file_manager"],
    "delete": ["file_manager"],
    "mkdir": ["file_manager"],
    # Phase 6: encode/decode
    "encode": ["encode_decode"],
    "decode": ["encode_decode"],
    "base64": ["encode_decode"],
    "hex": ["encode_decode"],
    # Phase 6: validation
    "check": ["validate_data"],
    "verify": ["validate_data"],
    "rule": ["validate_data"],
    # Phase 6: run context
    "last_run": ["retrieve_run_context"],
    "previous": ["retrieve_run_context", "query_context"],
    "context": ["retrieve_run_context"],
    "history": ["retrieve_run_context"],
    # Natural language creation verbs
    "create": ["write_file"],
    "make": ["write_file"],
    "generate": ["write_file"],
    "produce": ["write_file"],
    # Counting / measurement aliases
    "count": ["math_stats"],
    "tally": ["math_stats"],
    "measure": ["math_stats"],
    # Summarization alias
    "brief": ["summarize_text"],
    # Comparison alias
    "contrast": ["compare_texts"],
    # Classification alias
    "label": ["classify_intent"],
    # Extraction targets both regex and JSON
    "extract": ["regex_matcher", "json_parser"],
    # Phase 7.9: cross-run context query
    "prior": ["query_context"],
    "recall": ["query_context"],
    "remember": ["query_context"],
}


_LOCAL_PROVIDERS = {"LlamaCppChatProvider", "OllamaChatProvider"}
_DEFAULT_LOCAL_TIMEOUT = 30.0
_DEFAULT_CLOUD_TIMEOUT = 5.0
_DEFAULT_LOCAL_CLASSIFIER_TIMEOUT = 5.0
_DEFAULT_CLOUD_CLASSIFIER_TIMEOUT = 0.5


def _adaptive_parser_timeout(provider: ChatProvider | None) -> float:
    """Return parser timeout in seconds, adaptive to provider type.

    Local models (LlamaCpp/Ollama) get 30s; cloud (Groq/OpenAI) get 5s.
    P1_PARSER_TIMEOUT_SECONDS env var overrides all auto-detection.
    """
    env_override = os.getenv("P1_PARSER_TIMEOUT_SECONDS")
    if env_override:
        try:
            val = float(env_override)
            if val > 0:
                return val
        except ValueError:
            pass
    if provider is not None and type(provider).__name__ in _LOCAL_PROVIDERS:
        return _DEFAULT_LOCAL_TIMEOUT
    return _DEFAULT_CLOUD_TIMEOUT


def _adaptive_classifier_timeout(provider: ChatProvider | None) -> float:
    """Return intent classifier timeout in seconds, adaptive to provider type.

    Local models (LlamaCpp/Ollama) get 5s; cloud (Groq/OpenAI) get 0.5s.
    """
    if provider is not None and type(provider).__name__ in _LOCAL_PROVIDERS:
        return _DEFAULT_LOCAL_CLASSIFIER_TIMEOUT
    return _DEFAULT_CLOUD_CLASSIFIER_TIMEOUT


def parse_missions(
    user_input: str,
    timeout_seconds: float = 5.0,
    max_plan_steps: int = 7,
    classifier_provider: ChatProvider | None = None,
    classifier_timeout: float = 0.5,
) -> StructuredPlan:
    """Parse user input into a StructuredPlan.

    Tries structured parsing first, falls back to flat regex extraction.
    Protected by a hard timeout to prevent runaway parsing on huge inputs.

    If the parsed plan has more than *max_plan_steps* top-level steps,
    excess steps are merged into the last allowed step to prevent
    over-decomposition (guidance doc recommendation: 3-7 steps per plan).
    """
    LOGGER.info(
        "PARSER START timeout_seconds=%.2f max_plan_steps=%s input_chars=%s",
        timeout_seconds,
        max_plan_steps,
        len(user_input),
    )
    if timeout_seconds <= 0:
        plan = _parse_missions_inner(user_input)
        limited = _enforce_step_limit(plan, max_plan_steps)
        _apply_intent_classification(
            limited, user_input, classifier_provider, classifier_timeout
        )
        LOGGER.info(
            "PARSER RESULT method=%s steps=%s flat_missions=%s",
            limited.parsing_method,
            len(limited.steps),
            len(limited.flat_missions),
        )
        return limited

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
        LOGGER.warning("PARSER FALLBACK reason=timeout timeout_seconds=%.2f", timeout_seconds)
        fallback = _enforce_step_limit(_build_fallback_plan(user_input), max_plan_steps)
        _apply_intent_classification(
            fallback, user_input, classifier_provider, classifier_timeout
        )
        LOGGER.info(
            "PARSER RESULT method=%s steps=%s flat_missions=%s",
            fallback.parsing_method,
            len(fallback.steps),
            len(fallback.flat_missions),
        )
        return fallback

    if kind == "err":
        LOGGER.info("PARSER FALLBACK reason=exception")
        fallback = _enforce_step_limit(_build_fallback_plan(user_input), max_plan_steps)
        _apply_intent_classification(
            fallback, user_input, classifier_provider, classifier_timeout
        )
        LOGGER.info(
            "PARSER RESULT method=%s steps=%s flat_missions=%s",
            fallback.parsing_method,
            len(fallback.steps),
            len(fallback.flat_missions),
        )
        return fallback

    limited = _enforce_step_limit(payload, max_plan_steps)
    _apply_intent_classification(
        limited, user_input, classifier_provider, classifier_timeout
    )
    LOGGER.info(
        "PARSER RESULT method=%s steps=%s flat_missions=%s",
        limited.parsing_method,
        len(limited.steps),
        len(limited.flat_missions),
    )
    return limited


def _apply_intent_classification(
    plan: StructuredPlan,
    user_input: str,
    classifier_provider: ChatProvider | None,
    classifier_timeout: float,
) -> None:
    """Apply intent classification to the plan (mutates plan in place)."""
    if classifier_provider is not None:
        plan.intent_classification = _classify_intent(
            user_input, plan, classifier_provider, classifier_timeout
        )
    else:
        plan.intent_classification = _deterministic_classify(plan)


def _deterministic_classify(plan: StructuredPlan) -> IntentClassification:
    """Classify mission complexity using deterministic heuristics.

    Rules:
    - 3+ top-level steps -> complex
    - regex_fallback parsing -> complex (indicates ambiguous input)
    - Complex tools present -> complex
    - Otherwise -> simple
    """
    top_level = [s for s in plan.steps if s.parent_id is None]
    all_tools: set[str] = set()
    for step in plan.steps:
        all_tools.update(step.suggested_tools)

    has_complex_tools = bool(all_tools & _COMPLEX_TOOLS)

    if has_complex_tools or len(top_level) >= 3 or plan.parsing_method == "regex_fallback":
        return IntentClassification(
            complexity="complex",
            mission_type="multi_step",
            confidence=0.6,
            source="deterministic_fallback",
        )
    return IntentClassification(
        complexity="simple",
        mission_type="tool_call",
        confidence=0.7,
        source="deterministic_fallback",
    )


_CLASSIFIER_PROMPT = """\
Classify this mission's complexity and type.

Mission: {user_input}
Steps: {step_count}
Suggested tools: {tools}

Respond with JSON only:
{{"complexity": "simple" or "complex", "mission_type": "file_io" or "computation" or "analysis" or "multi_step" or "tool_call"}}
"""


def _classify_intent(
    user_input: str,
    plan: StructuredPlan,
    provider: ChatProvider,
    timeout: float,
) -> IntentClassification:
    """Classify mission intent using an LLM provider with timeout fallback.

    On timeout or invalid response, falls back to deterministic classification.
    """
    tools_str = ", ".join(
        sorted({t for s in plan.steps for t in s.suggested_tools})
    )
    prompt = _CLASSIFIER_PROMPT.format(
        user_input=user_input[:500],
        step_count=len([s for s in plan.steps if s.parent_id is None]),
        tools=tools_str or "none",
    )

    response_schema = {
        "type": "object",
        "properties": {
            "complexity": {"type": "string", "enum": ["simple", "complex"]},
            "mission_type": {
                "type": "string",
                "enum": ["file_io", "computation", "analysis", "multi_step", "tool_call"],
            },
        },
        "required": ["complexity", "mission_type"],
    }

    outbox: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)

    def _run() -> None:
        try:
            result = provider.generate(
                messages=[{"role": "user", "content": prompt}],
                response_schema=response_schema,
            )
            outbox.put(("ok", result))
        except Exception as exc:  # noqa: BLE001
            outbox.put(("err", exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    try:
        kind, payload = outbox.get(timeout=timeout)
    except queue.Empty:
        LOGGER.warning("INTENT CLASSIFIER timeout after %.2fs, using deterministic fallback", timeout)
        return _deterministic_classify(plan)

    if kind == "err":
        LOGGER.warning("INTENT CLASSIFIER error: %s, using deterministic fallback", payload)
        return _deterministic_classify(plan)

    # Parse JSON response
    try:
        data = json.loads(payload)
        complexity = data["complexity"]
        mission_type = data["mission_type"]
        if complexity not in ("simple", "complex"):
            raise ValueError(f"Invalid complexity: {complexity}")  # noqa: TRY301
        return IntentClassification(
            complexity=complexity,
            mission_type=mission_type,
            confidence=0.8,
            source="llm",
        )
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        LOGGER.warning("INTENT CLASSIFIER invalid JSON response, using deterministic fallback")
        return _deterministic_classify(plan)


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
        r"^\s+"  # leading whitespace (indent)
        r"(?:"
        r"(\d+)([a-z])\s*[\.\):\-]\s*"  # "1a." or "1a)" etc.
        r"|"
        r"(\d+)\.(\d+)\s*[\.\):\-]?\s*"  # "1.1" or "1.1." etc.
        r")"
        r"(.+)",  # description
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
        parent_steps.append(MissionStep(id=sub_id, description=desc, parent_id=parent_id))


def _parse_multiline_descriptions(lines: list[str], steps: list[MissionStep]) -> None:
    """Merge indented continuation lines that don't match any task/subtask pattern into prior step."""
    task_pattern = re.compile(
        r"^\s*(?:[Tt]ask\s*\d+\s*:|"  # Task N:
        r"\d+\s*[\)\.:\-]\s|"  # N. or N) etc.
        r"\d+[a-z]\s*[\.\):\-]|"  # 1a. etc.
        r"\d+\.\d+\s*[\.\):\-]?|"  # 1.1 etc.
        r"[-*+]\s)"  # bullets
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
        if (line.startswith("  ") or line.startswith("\t")) and current_step:
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

    for _parent_id, children in parent_children.items():
        for i, child in enumerate(children):
            if i > 0:
                child.dependencies.append(children[i - 1].id)
            # First child of a parent depends on the parent
            if child.parent_id and child.parent_id not in child.dependencies and i == 0:
                child.dependencies.append(child.parent_id)


def _steps_to_flat_missions(steps: list[MissionStep]) -> list[str]:
    """Convert steps into flat mission strings for backward compat.

    Top-level steps become flat missions and include child sub-task context.
    This preserves critical constraints (for example: file paths/counts)
    for downstream validators without changing mission count semantics.
    """
    children_map: dict[str, list[MissionStep]] = {}
    for step in steps:
        if step.parent_id is None:
            continue
        children_map.setdefault(step.parent_id, []).append(step)

    flat: list[str] = []
    for step in steps:
        if step.parent_id is None:
            mission = f"Task {step.id}: {step.description}"
            children = children_map.get(step.id, [])
            if children:
                child_descriptions = "; ".join(
                    f"{child.id}. {child.description}" for child in children
                )
                mission = f"{mission} | Subtasks: {child_descriptions}"
            flat.append(mission)
    return flat if flat else [s.description for s in steps]


def _enforce_step_limit(plan: StructuredPlan, max_steps: int) -> StructuredPlan:
    """Merge excess top-level steps when the plan exceeds *max_steps*.

    Sub-tasks (steps with a parent_id) are not counted toward the limit.
    When merging, excess steps are folded into the last allowed step's
    description so no information is lost.
    """
    if max_steps <= 0:
        return plan

    top_level = [s for s in plan.steps if s.parent_id is None]
    if len(top_level) <= max_steps:
        return plan

    keep = top_level[:max_steps]
    excess = top_level[max_steps:]
    LOGGER.info(
        "PARSER STEP LIMIT applied max_steps=%s original_top_level=%s merged_excess=%s",
        max_steps,
        len(top_level),
        len(excess),
    )

    # Merge excess descriptions into the last kept step
    last = keep[-1]
    merged_desc = [last.description]
    for s in excess:
        merged_desc.append(s.description)
        # Also merge any suggested tools
        for tool in s.suggested_tools:
            if tool not in last.suggested_tools:
                last.suggested_tools.append(tool)
    last.description = " | ".join(merged_desc)

    # Rebuild steps: kept top-level + their children + excess children reparented
    excess_ids = {s.id for s in excess}
    kept_ids = {s.id for s in keep}
    new_steps: list[MissionStep] = []
    for s in plan.steps:
        if s.parent_id is None:
            if s.id in kept_ids:
                new_steps.append(s)
        else:
            if s.parent_id in excess_ids:
                # Reparent to the last kept step
                s.parent_id = last.id
            new_steps.append(s)

    # Rebuild flat missions
    flat = _steps_to_flat_missions(new_steps)
    return StructuredPlan(steps=new_steps, flat_missions=flat, parsing_method=plan.parsing_method)


def _build_fallback_plan(user_input: str) -> StructuredPlan:
    """Use the original regex extraction as fallback."""
    missions = _extract_missions_regex_fallback(user_input)
    LOGGER.info("PARSER REGEX FALLBACK missions=%s", len(missions))
    steps = [MissionStep(id=str(i + 1), description=m) for i, m in enumerate(missions)]
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
