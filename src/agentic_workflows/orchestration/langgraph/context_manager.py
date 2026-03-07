"""Context management for multi-mission orchestration.

Provides typed models for mission context, artifact tracking, and deterministic
summary generation. MissionContext objects are stored as serialized dicts
(model_dump()) in RunState to avoid checkpointer serialization issues with
Pydantic BaseModel objects in TypedDict.

Phase 7.1 — CTX-01, CTX-02, CTX-03, CTX-09.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


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
