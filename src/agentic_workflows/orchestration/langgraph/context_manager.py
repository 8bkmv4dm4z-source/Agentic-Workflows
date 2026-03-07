"""Context management for multi-mission orchestration.

Provides typed models for mission context, artifact tracking, and deterministic
summary generation. MissionContext objects are stored as serialized dicts
(model_dump()) in RunState to avoid checkpointer serialization issues with
Pydantic BaseModel objects in TypedDict.

Phase 7.1 — CTX-01, CTX-02, CTX-03, CTX-04, CTX-05, CTX-06, CTX-08, CTX-09, CTX-10, CTX-11.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agentic_workflows.logger import get_logger

_logger = get_logger("context_manager")


# ── Models ───────────────────────────────────────────────────────────


class ArtifactRecord(BaseModel):
    """A single artifact produced by a tool execution."""

    key: str
    value: str
    source_tool: str
    source_mission_id: int


class SubMissionContext(BaseModel):
    """Context for a sub-mission within a parent mission."""

    sub_mission_id: str
    goal: str
    status: str = "pending"
    tools_used: list[str] = Field(default_factory=list)
    key_results: dict[str, str] = Field(default_factory=dict)


class MissionContext(BaseModel):
    """Typed context for a single mission within a run.

    Stored as model_dump() dicts in RunState.mission_contexts to avoid
    checkpointer serialization issues (Pydantic BaseModel in TypedDict).
    Reconstruct via MissionContext.model_validate(d) when reading.
    """

    mission_id: int
    goal: str
    status: str = "pending"
    tools_used: list[str] = Field(default_factory=list)
    key_results: dict[str, str] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    sub_missions: dict[str, SubMissionContext] = Field(default_factory=dict)
    summary: str = ""
    step_range: tuple[int, int] | None = None

    def build_summary(self) -> str:
        """Produce a deterministic summary string from structured data.

        Format:
            Mission {id}: {goal} | Tools: {tool1 -> tool2} | {key}: {value} | Artifacts: {k=v, ...}
        """
        parts: list[str] = [f"Mission {self.mission_id}: {self.goal}"]

        if self.tools_used:
            parts.append(f"Tools: {' -> '.join(self.tools_used)}")

        for k, v in self.key_results.items():
            parts.append(f"{k}: {v}")

        if self.artifacts:
            artifact_strs = [f"{a.key}={a.value}" for a in self.artifacts]
            parts.append(f"Artifacts: {', '.join(artifact_strs)}")

        return " | ".join(parts)


# ── Artifact extraction ──────────────────────────────────────────────


def _extract_write_file(
    result: dict[str, Any], args: dict[str, Any], mission_id: int
) -> list[ArtifactRecord]:
    path = args.get("path", "")
    records: list[ArtifactRecord] = []
    if path:
        records.append(
            ArtifactRecord(
                key="file_path",
                value=str(path),
                source_tool="write_file",
                source_mission_id=mission_id,
            )
        )
    return records


def _extract_data_analysis(
    result: dict[str, Any], args: dict[str, Any], mission_id: int
) -> list[ArtifactRecord]:
    records: list[ArtifactRecord] = []
    if "mean" in result:
        records.append(
            ArtifactRecord(
                key="mean",
                value=str(result["mean"]),
                source_tool="data_analysis",
                source_mission_id=mission_id,
            )
        )
    if "outliers" in result:
        records.append(
            ArtifactRecord(
                key="outliers",
                value=json.dumps(result["outliers"]),
                source_tool="data_analysis",
                source_mission_id=mission_id,
            )
        )
    return records


def _extract_sort_array(
    result: dict[str, Any], args: dict[str, Any], mission_id: int
) -> list[ArtifactRecord]:
    records: list[ArtifactRecord] = []
    sorted_val = result.get("sorted", result.get("result"))
    if sorted_val is not None:
        records.append(
            ArtifactRecord(
                key="sorted_result",
                value=json.dumps(sorted_val) if not isinstance(sorted_val, str) else sorted_val,
                source_tool="sort_array",
                source_mission_id=mission_id,
            )
        )
    return records


_ARTIFACT_EXTRACTORS: dict[
    str,
    Any,
] = {
    "write_file": _extract_write_file,
    "data_analysis": _extract_data_analysis,
    "sort_array": _extract_sort_array,
}


def extract_artifacts(
    tool_name: str,
    result: dict[str, Any],
    args: dict[str, Any],
    mission_id: int,
) -> list[ArtifactRecord]:
    """Extract structured artifacts from a tool result.

    Returns empty list for error results. Uses tool-specific extractors
    when available, falls back to a generic extractor for unknown tools.
    """
    # Error results produce no artifacts
    if "error" in result:
        return []

    extractor = _ARTIFACT_EXTRACTORS.get(tool_name)
    if extractor is not None:
        return extractor(result, args, mission_id)

    # Generic fallback: first 200 chars of stringified result
    raw = json.dumps(result, default=str)
    return [
        ArtifactRecord(
            key="result",
            value=raw[:200],
            source_tool=tool_name,
            source_mission_id=mission_id,
        )
    ]


# ── Summary extraction from tool results ─────────────────────────────


def extract_summary_from_result(tool_name: str, result: dict[str, Any]) -> dict[str, str]:
    """Extract deterministic key fields from a tool result.

    Returns a dict[str, str] of the most important fields for each tool type.
    """
    if tool_name == "write_file":
        return {"outcome": str(result.get("result", ""))}

    if tool_name == "data_analysis":
        summary: dict[str, str] = {}
        for field in ("mean", "median", "outliers", "non_outliers"):
            if field in result:
                summary[field] = str(result[field])
        return summary

    if tool_name == "sort_array":
        sorted_val = result.get("sorted", result.get("result"))
        if sorted_val is not None:
            return {"sorted": str(sorted_val)}
        return {}

    # Generic: truncate to 200 chars
    raw = json.dumps(result, default=str)
    return {"result": raw[:200]}


# ── ContextManager ───────────────────────────────────────────────────


class ContextManager:
    """Manages mission contexts within a run.

    Skeleton class -- full eviction, enrichment, and wiring methods will be
    added in subsequent plans.
    """

    def __init__(
        self,
        large_result_threshold: int = 4000,
        sliding_window_cap: int = 30,
        step_threshold: int = 10,
    ) -> None:
        self.large_result_threshold = large_result_threshold
        self.sliding_window_cap = sliding_window_cap
        self.step_threshold = step_threshold

    def get_artifacts_for_mission(
        self, state: dict[str, Any], mission_id: int
    ) -> list[ArtifactRecord]:
        """Return artifacts from all missions with id < mission_id.

        Reconstructs MissionContext from serialized dicts in state.
        """
        mission_contexts: dict[str, Any] = state.get("mission_contexts", {})
        artifacts: list[ArtifactRecord] = []

        for mid_str, ctx_dict in mission_contexts.items():
            mid = int(mid_str)
            if mid < mission_id:
                ctx = MissionContext.model_validate(ctx_dict)
                artifacts.extend(ctx.artifacts)

        return artifacts

    def build_specialist_context(
        self, state: dict[str, Any], mission_id: int
    ) -> dict[str, str]:
        """Build enriched context dict for specialist invocation.

        Returns a dict with:
        - ``mission_goal``: goal string for the given mission_id
        - ``prior_results_summary``: formatted summaries of all completed
          missions with id < mission_id, using the same ``build_summary()``
          format as ``MissionContext``.
        """
        mission_contexts: dict[str, Any] = state.get("mission_contexts", {})

        # Resolve mission goal
        goal = ""
        mid_str = str(mission_id)
        if mid_str in mission_contexts:
            ctx = MissionContext.model_validate(mission_contexts[mid_str])
            goal = ctx.goal
        else:
            # Fallback to state["missions"] list (0-indexed)
            missions_list: list[str] = state.get("missions", [])
            idx = mission_id - 1
            if 0 <= idx < len(missions_list):
                goal = missions_list[idx]

        # Build prior results summary from completed missions with id < mission_id
        prior_parts: list[str] = []
        for mid_key in sorted(mission_contexts.keys(), key=lambda k: int(k)):
            mid = int(mid_key)
            if mid >= mission_id:
                continue
            ctx = MissionContext.model_validate(mission_contexts[mid_key])
            if ctx.status == "completed":
                prior_parts.append(ctx.build_summary())

        prior_results_summary = "\n".join(prior_parts)

        return {
            "mission_goal": goal,
            "prior_results_summary": prior_results_summary,
        }

    # ── Eviction methods (Plan 02) ──────────────────────────────────

    def on_mission_complete(self, state: dict[str, Any], mission_id: int) -> None:
        """Evict mission messages and inject a summary on mission completion.

        Looks up MissionContext from state, builds a deterministic summary,
        removes messages belonging to the mission (using step_range), and injects
        the summary as a role="user" message with [Orchestrator] prefix.
        """
        mid_str = str(mission_id)
        mission_contexts: dict[str, Any] = state.get("mission_contexts", {})
        if mid_str not in mission_contexts:
            return

        ctx = MissionContext.model_validate(mission_contexts[mid_str])
        summary = ctx.build_summary()
        ctx.status = "completed"
        ctx.summary = summary

        # Identify messages belonging to this mission via step_range
        messages: list[dict[str, Any]] = state.get("messages", [])
        step_range = ctx.step_range
        if step_range is not None:
            start_step, end_step = step_range
            # Remove messages in the step range (indices start_step..end_step inclusive)
            # Messages[0] is system prompt, messages[1:] are chronological.
            # step_range maps to message indices: start_step..end_step
            keep: list[dict[str, Any]] = []
            removed_count = 0
            for i, msg in enumerate(messages):
                if i == 0:
                    # Always keep system prompt
                    keep.append(msg)
                elif start_step <= i <= end_step:
                    removed_count += 1
                else:
                    keep.append(msg)
            # Inject summary as role="user" with [Orchestrator] prefix
            # Insert at the position where the mission messages were
            insert_pos = min(start_step, len(keep))
            summary_msg: dict[str, Any] = {
                "role": "user",
                "content": f"[Orchestrator] {summary}",
            }
            keep.insert(insert_pos, summary_msg)
            state["messages"] = keep
        else:
            # No step_range: just append summary
            removed_count = 0
            state["messages"].append({
                "role": "user",
                "content": f"[Orchestrator] {summary}",
            })

        # Update mission context in state
        state["mission_contexts"][mid_str] = ctx.model_dump()

        self._emit_eviction_event(
            state,
            trigger="mission_complete",
            mission_id=mission_id,
            messages_removed=removed_count,
            summary_injected=summary,
        )

    def on_tool_result(
        self,
        state: dict[str, Any],
        tool_name: str,
        result: dict[str, Any],
        args: dict[str, Any],
        mission_id: int,
    ) -> None:
        """Process a tool result: replace large results with placeholders, extract artifacts.

        If the stringified result exceeds large_result_threshold, the most recent
        tool result message for this tool is replaced with a compact placeholder.
        Artifacts and summary fields are always extracted into MissionContext.
        """
        result_str = str(result)
        result_len = len(result_str)
        replaced = False

        if result_len > self.large_result_threshold:
            # Find the most recent tool result message for this tool
            messages: list[dict[str, Any]] = state.get("messages", [])
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                content = msg.get("content", "")
                if f"TOOL RESULT ({tool_name})" in content or (
                    msg.get("role") == "user" and tool_name in content and "TOOL RESULT" in content
                ):
                    messages[i] = {
                        "role": "user",
                        "content": (
                            f"[Orchestrator] [tool_result: {tool_name}, "
                            f"{result_len} chars, stored in context]"
                        ),
                    }
                    replaced = True
                    break

        # Extract artifacts and update MissionContext
        mid_str = str(mission_id)
        mission_contexts: dict[str, Any] = state.get("mission_contexts", {})
        if mid_str in mission_contexts:
            ctx = MissionContext.model_validate(mission_contexts[mid_str])
            new_artifacts = extract_artifacts(tool_name, result, args, mission_id)
            ctx.artifacts.extend(new_artifacts)
            summary_fields = extract_summary_from_result(tool_name, result)
            ctx.key_results.update(summary_fields)
            if tool_name not in ctx.tools_used:
                ctx.tools_used.append(tool_name)
            state["mission_contexts"][mid_str] = ctx.model_dump()

        if replaced:
            self._emit_eviction_event(
                state,
                trigger="large_tool_result",
                mission_id=mission_id,
                messages_removed=1,
                summary_injected=f"[tool_result: {tool_name}, {result_len} chars]",
            )

    def compact(self, state: dict[str, Any]) -> None:
        """Unified compaction: enforce sliding window hard cap.

        Replaces the old _compact_messages() and _evict_tool_result_messages().
        Keeps system prompt (first message) + newest (cap - 1) messages.
        """
        messages: list[dict[str, Any]] = state.get("messages", [])
        if len(messages) <= self.sliding_window_cap:
            return

        # Keep system prompt + newest (cap - 1) messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        keep_count = max(0, self.sliding_window_cap - len(system_msgs))
        removed = len(non_system) - keep_count

        state["messages"] = system_msgs + non_system[-keep_count:] if keep_count > 0 else system_msgs

        if removed > 0:
            self._emit_eviction_event(
                state,
                trigger="sliding_window",
                mission_id=0,
                messages_removed=removed,
                summary_injected="",
            )

    def build_planner_context_injection(self, state: dict[str, Any]) -> str:
        """Build a context injection string from completed mission summaries.

        Format: "[Orchestrator] Prior missions: {summary1}; {summary2}. Available artifacts: {key=value, ...}"
        Returns empty string if no completed missions exist.
        """
        mission_contexts: dict[str, Any] = state.get("mission_contexts", {})
        summaries: list[str] = []
        all_artifacts: list[str] = []

        for mid_key in sorted(mission_contexts.keys(), key=lambda k: int(k)):
            ctx = MissionContext.model_validate(mission_contexts[mid_key])
            if ctx.status == "completed":
                summaries.append(ctx.summary if ctx.summary else ctx.build_summary())
                for a in ctx.artifacts:
                    all_artifacts.append(f"{a.key}={a.value}")

        if not summaries:
            return ""

        parts = [f"[Orchestrator] Prior missions: {'; '.join(summaries)}"]
        if all_artifacts:
            parts.append(f"Available artifacts: {', '.join(all_artifacts)}")
        return ". ".join(parts)

    def _emit_eviction_event(
        self,
        state: dict[str, Any],
        trigger: str,
        mission_id: int,
        messages_removed: int,
        summary_injected: str,
    ) -> None:
        """Log eviction event and record in policy_flags.pipeline_trace."""
        _logger.info(
            "CONTEXT EVICT trigger=%s mission_id=%s messages_removed=%s summary=%s",
            trigger,
            mission_id,
            messages_removed,
            summary_injected[:100] if summary_injected else "",
        )
        policy_flags: dict[str, Any] = state.get("policy_flags", {})
        trace: list[dict[str, Any]] = policy_flags.setdefault("pipeline_trace", [])
        trace.append({
            "stage": "context_eviction",
            "step": state.get("step", 0),
            "trigger": trigger,
            "mission_id": mission_id,
            "messages_removed": messages_removed,
            "summary_injected": summary_injected,
        })
