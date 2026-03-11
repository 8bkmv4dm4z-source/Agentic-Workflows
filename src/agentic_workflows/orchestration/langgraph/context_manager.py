"""Context management for multi-mission orchestration.

Provides typed models for mission context, artifact tracking, and deterministic
summary generation. MissionContext objects are stored as serialized dicts
(model_dump()) in RunState to avoid checkpointer serialization issues with
Pydantic BaseModel objects in TypedDict.

Phase 7.1 — CTX-01, CTX-02, CTX-03, CTX-04, CTX-05, CTX-06, CTX-08, CTX-09, CTX-10, CTX-11.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from agentic_workflows.logger import get_logger

if TYPE_CHECKING:
    from agentic_workflows.context.embedding_provider import EmbeddingProvider
    from agentic_workflows.storage.artifact_store import ArtifactStore
    from agentic_workflows.storage.mission_context_store import MissionContextStore

_logger = get_logger("context_manager")

# W2-5: Cap for pipeline_trace entries (matches graph.py _PIPELINE_TRACE_CAP).
# Defined locally to avoid circular import with graph.py.
_PIPELINE_TRACE_CAP: int = 500

# Timeout for cross-run cascade queries — prevents a slow/hung Postgres connection
# from blocking the planner indefinitely.
_CASCADE_TIMEOUT_SECONDS: float = 2.0

# Maximum number of entries in _cascade_cache / _embed_cache.  Prevents unbounded
# memory growth in long-lived processes (e.g. FastAPI workers with many unique goals).
# When the limit is reached, the oldest half is evicted (FIFO).
_CACHE_MAX_SIZE: int = 200


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
        mission_context_store: MissionContextStore | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self.large_result_threshold = large_result_threshold
        self.sliding_window_cap = sliding_window_cap
        self.step_threshold = step_threshold
        self._store = mission_context_store
        self._embedding_provider = embedding_provider
        self._artifact_store = artifact_store
        self._logger = _logger
        # Per-run caches keyed by f"{run_id}:{goal_text}" to prevent cross-run contamination
        self._cascade_cache: dict[str, list] = {}   # cache_key → cached hits
        self._embed_cache: dict[str, list[float]] = {}  # cache_key → embedding
        # Phase 7.4: dedup set — tracks keys already injected as [Cross-run] this run
        self._injected_cross_run_keys: set[str] = set()

    # ── Cache helpers ──────────────────────────────────────────────────

    def _cache_put(self, cache: dict, key: str, value: object) -> None:
        """Insert *value* at *key* in *cache*; evict oldest half on overflow.

        Uses FIFO eviction: when ``len(cache) >= _CACHE_MAX_SIZE``, the oldest
        ``_CACHE_MAX_SIZE // 2`` entries (insertion-order) are deleted before
        the new entry is added.  This bounds cache memory in long-lived
        processes that see many distinct ``run_id:goal`` combinations.

        The ``list(cache.keys())[:n]`` snapshot is taken before iteration to
        avoid a RuntimeError from mutating the dict during a keys-view loop.
        """
        if len(cache) >= _CACHE_MAX_SIZE:
            remove_count = _CACHE_MAX_SIZE // 2
            for k in list(cache.keys())[:remove_count]:
                del cache[k]
        cache[key] = value

    # ── Phase 7.3: cross-run persistence helpers ───────────────────────

    def _persist_mission_context(self, mission_context: dict) -> None:  # type: ignore[type-arg]
        """Persist a completed mission context to Postgres via MissionContextStore and ArtifactStore.

        No-op if both self._store and self._artifact_store are None (SQLite/CI environments).
        Gracefully swallows all exceptions to avoid breaking the main graph flow.
        """
        if self._store is None and self._artifact_store is None:
            return
        try:
            goal = mission_context.get("goal", "") or ""
            summary = mission_context.get("summary", "") or ""
            tools_used = mission_context.get("used_tools", []) or []
            key_results = mission_context.get("key_results", {}) or {}
            run_id = str(mission_context.get("run_id", "unknown"))
            mission_id = str(mission_context.get("mission_id", "unknown"))

            # Generate embedding for the goal text
            if self._embedding_provider is not None:
                embedding = self._embedding_provider.embed_sync(goal)
            else:
                # Fallback zero vector if no provider — still stores without semantic search
                embedding = [0.0] * 384

            if self._store is not None:
                self._store.upsert(
                    run_id=run_id,
                    mission_id=mission_id,
                    goal=goal,
                    status="completed",
                    summary=summary,
                    tools_used=list(tools_used),
                    key_results=dict(key_results),
                    embedding=embedding,
                )

            # Phase 7.5: Persist artifacts to ArtifactStore (no-op if _artifact_store is None)
            if self._artifact_store is not None:
                artifacts = mission_context.get("artifacts", [])
                for art in artifacts:
                    try:
                        art_emb = (
                            self._embedding_provider.embed_sync(art["value"][:200])
                            if self._embedding_provider is not None
                            else [0.0] * 384
                        )
                        self._artifact_store.upsert(
                            run_id=run_id,
                            mission_id=mission_id,
                            key=art["key"],
                            value=art["value"],
                            source_tool=art["source_tool"],
                            embedding=art_emb,
                        )
                    except Exception as exc:  # noqa: BLE001
                        self._logger.warning("artifact upsert failed (non-fatal): %s", exc)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("_persist_mission_context failed (non-fatal): %s", exc)

    def _get_current_goal_text(self, state: dict[str, Any]) -> str:
        """Extract goal text from the active mission in state."""
        active_id = str(state.get("current_mission_id", 1))
        mission_contexts = state.get("mission_contexts") or {}
        ctx = mission_contexts.get(active_id)
        if isinstance(ctx, dict):
            goal = ctx.get("goal", "")
            if goal:
                return str(goal)
        # fallback: first mission
        missions = state.get("missions") or []
        if missions:
            return str(missions[0]) if isinstance(missions[0], str) else str(missions[0].get("goal", ""))
        for ctx in mission_contexts.values():
            if isinstance(ctx, dict):
                goal = ctx.get("goal", "")
                if goal:
                    return str(goal)
        return ""

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

        # Phase 7.3: persist to cross-run store (no-op if store=None)
        # Phase 7.5: include artifacts for ArtifactStore upsert wiring
        persist_ctx: dict[str, Any] = {
            "goal": ctx.goal,
            "summary": ctx.summary,
            "used_tools": ctx.tools_used,
            "key_results": ctx.key_results,
            "run_id": state.get("run_id", "unknown"),
            "mission_id": str(mission_id),
            "artifacts": [a.model_dump() for a in ctx.artifacts],
        }
        try:
            self._persist_mission_context(persist_ctx)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("on_mission_complete persist failed (non-fatal): %s", exc)

    def persist_partial_missions(self, state: dict[str, Any]) -> int:
        """Persist incomplete missions with status='partial' for cross-run continuity.

        Called from _finalize() when the run ends with incomplete missions (e.g. timeout).
        Returns the number of partial missions persisted.
        """
        if self._store is None:
            return 0

        mission_reports = state.get("mission_reports", [])
        persisted = 0
        for report in mission_reports:
            status = str(report.get("status", ""))
            if status == "completed":
                continue  # already persisted by on_mission_complete

            mission_id = str(report.get("mission_id", "unknown"))
            goal = str(report.get("mission", ""))
            used_tools = report.get("used_tools", []) or []
            tool_results = report.get("tool_results", []) or []

            # Build a partial summary from whatever tools were executed
            if tool_results:
                tool_summaries = []
                for tr in tool_results[:5]:  # cap to avoid huge summaries
                    t = tr.get("tool", "unknown")
                    r = str(tr.get("result", ""))[:200]
                    tool_summaries.append(f"{t}: {r}")
                summary = f"Partial ({len(used_tools)} tools executed: {', '.join(used_tools)}). " + "; ".join(tool_summaries)
            else:
                summary = f"Partial (no tools executed). Goal: {goal[:200]}"

            # Cap summary length
            summary = summary[:800]

            key_results: dict[str, Any] = {
                "partial": True,
                "tools_completed": used_tools,
                "subtask_statuses": report.get("subtask_statuses", []),
            }

            persist_ctx: dict[str, Any] = {
                "goal": goal,
                "summary": summary,
                "used_tools": list(used_tools),
                "key_results": key_results,
                "run_id": state.get("run_id", "unknown"),
                "mission_id": mission_id,
                "artifacts": [],
            }
            try:
                self._persist_mission_context_with_status(persist_ctx, status="partial")
                persisted += 1
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "persist_partial_missions failed mission_id=%s (non-fatal): %s",
                    mission_id, exc,
                )
        if persisted:
            self._logger.info(
                "PARTIAL PERSIST run_id=%s count=%s",
                state.get("run_id", "unknown"), persisted,
            )
        return persisted

    def _persist_mission_context_with_status(
        self, mission_context: dict, *, status: str = "completed",  # type: ignore[type-arg]
    ) -> None:
        """Persist a mission context with explicit status (completed or partial)."""
        if self._store is None and self._artifact_store is None:
            return
        try:
            goal = mission_context.get("goal", "") or ""
            summary = mission_context.get("summary", "") or ""
            tools_used = mission_context.get("used_tools", []) or []
            key_results = mission_context.get("key_results", {}) or {}
            run_id = str(mission_context.get("run_id", "unknown"))
            mission_id = str(mission_context.get("mission_id", "unknown"))

            if self._embedding_provider is not None:
                embedding = self._embedding_provider.embed_sync(goal)
            else:
                embedding = [0.0] * 384

            if self._store is not None:
                self._store.upsert(
                    run_id=run_id,
                    mission_id=mission_id,
                    goal=goal,
                    status=status,
                    summary=summary,
                    tools_used=list(tools_used),
                    key_results=dict(key_results),
                    embedding=embedding,
                )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("_persist_mission_context_with_status failed (non-fatal): %s", exc)

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
            # Fallback retroactive replacement for any tool result messages that were
            # appended before this method was called (e.g. retrieve_memo, write_file paths).
            # The primary gating path in graph.py _execute_action truncates BEFORE append,
            # so this branch fires only for code paths that bypass that gate.
            # Message format is: "TOOL_RESULT #N (tool_name): ..." (underscore, step number).
            messages: list[dict[str, Any]] = state.get("messages", [])
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                content = msg.get("content", "")
                if "TOOL_RESULT" in content and f"({tool_name})" in content:
                    messages[i] = {
                        "role": msg.get("role", "system"),
                        "content": (
                            f"[tool_result: {tool_name}, "
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

        # Re-inject cursor hints for active chunked reads after eviction
        if self._store is not None:
            run_id = state.get("run_id", "")
            if run_id:
                active = self._store.get_active_cursors(run_id)
                for cur in active:
                    hint = (
                        f"[Orchestrator] Chunked read in progress: read_file_chunk "
                        f"path={cur['key']} next_offset={cur['next_offset']} "
                        f"of {cur['total']} lines. Continue from offset={cur['next_offset']}."
                    )
                    state["messages"].append({"role": "user", "content": hint})

    def proactive_compact(self, state: dict[str, Any], ctx_limit: int) -> None:
        """Compact messages when estimated token count approaches ctx_limit.

        Called before each planner LLM call to prevent exceed_context_size_error.
        Uses len//4 token estimation (same as token_budget tracking in graph.py).
        Triggers at 80% of ctx_limit to leave headroom for the response.
        """
        messages = state.get("messages", [])
        estimated_tokens = sum(len(str(m.get("content", ""))) // 4 for m in messages)
        threshold = int(ctx_limit * 0.8)

        if estimated_tokens <= threshold:
            return

        _logger.warning(
            "PROACTIVE COMPACT triggered: estimated_tokens=%d threshold=%d ctx_limit=%d messages=%d",
            estimated_tokens, threshold, ctx_limit, len(messages),
        )

        # First try standard sliding window compaction
        self.compact(state)

        # Re-estimate after compaction
        messages = state.get("messages", [])
        estimated_tokens_after = sum(len(str(m.get("content", ""))) // 4 for m in messages)

        if estimated_tokens_after > threshold:
            # Aggressive compaction: keep system + last 5 messages
            system_msgs = [m for m in messages if m.get("role") == "system"]
            non_system = [m for m in messages if m.get("role") != "system"]
            aggressive_keep = min(5, len(non_system))
            state["messages"] = system_msgs + non_system[-aggressive_keep:]
            _logger.warning(
                "AGGRESSIVE COMPACT: reduced from %d to %d messages (estimated_tokens was %d, ctx_limit=%d)",
                len(messages), len(state["messages"]), estimated_tokens_after, ctx_limit,
            )

        # Final check -- if still over, log but do not crash
        final_tokens = sum(len(str(m.get("content", ""))) // 4 for m in state.get("messages", []))
        if final_tokens > ctx_limit:
            _logger.warning(
                "CONTEXT STILL EXCEEDS LIMIT after compaction: estimated=%d limit=%d -- provider may reject",
                final_tokens, ctx_limit,
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
            base_result = ""
        else:
            parts = [f"[Orchestrator] Prior missions: {'; '.join(summaries)}"]
            if all_artifacts:
                parts.append(f"Available artifacts: {', '.join(all_artifacts)}")
            base_result = ". ".join(parts)

        # Phase 7.3: append cross-run similar missions from cascade store
        _CONTEXT_CAP = 1500  # total chars across all injected content
        cross_run_lines: list[str] = []
        hits: list = []
        current_step = state.get("step", 0)
        if self._store is not None and current_step > 0:
            try:
                goal_text = self._get_current_goal_text(state)

                # Early-exit: skip cascade entirely for empty goals
                if not goal_text:
                    result = base_result[:_CONTEXT_CAP] if base_result else base_result
                    self._logger.info(
                        "CONTEXT INJECT missions=%d cross_run_hits=%d chars=%d cached=%s hits=[%s]",
                        len(summaries), 0, len(result), False, "-",
                    )
                    return result

                run_id = str(state.get("run_id", ""))
                cache_key = f"{run_id}:{goal_text}"

                # Cache embedding to avoid re-embedding same goal 10-25× per run
                if self._embedding_provider is not None:
                    if cache_key not in self._embed_cache:
                        self._cache_put(self._embed_cache, cache_key, self._embedding_provider.embed_sync(goal_text))
                    self._logger.debug(
                        "EMBED GEN context cached=%s goal_len=%d",
                        cache_key in self._embed_cache and cache_key in self._embed_cache,
                        len(goal_text),
                    )
                    embedding = self._embed_cache[cache_key]
                else:
                    embedding = None

                # Cache cascade result to avoid re-running SQL 10-25× per run
                if cache_key not in self._cascade_cache:
                    try:
                        executor = ThreadPoolExecutor(max_workers=1)
                        try:
                            future = executor.submit(
                                self._store.query_cascade,
                                goal_text,
                                embedding=embedding,
                                top_k=3,
                            )
                            hits_result = future.result(timeout=_CASCADE_TIMEOUT_SECONDS)
                            self._cache_put(self._cascade_cache, cache_key, hits_result)
                        except TimeoutError:
                            self._logger.warning(
                                "query_cascade timeout after %.1fs — falling back to []",
                                _CASCADE_TIMEOUT_SECONDS,
                            )
                            self._cache_put(self._cascade_cache, cache_key, [])
                        finally:
                            executor.shutdown(wait=False)
                    except Exception as exc:  # noqa: BLE001
                        self._logger.debug(
                            "cross-run cascade query failed (non-fatal): %s", exc
                        )
                        self._cache_put(self._cascade_cache, cache_key, [])
                hits = self._cascade_cache[cache_key]

                for hit in hits:
                    # Richer cross-run format with tools, status, and remaining work
                    tools_used = hit.get("used_tools") or hit.get("tools_used") or []
                    status = hit.get("status", "")
                    tools_part = f" | Tools: {', '.join(tools_used)}" if tools_used else ""
                    status_part = f" | Status: {status}" if status else ""
                    remaining_part = ""
                    if status == "partial":
                        kr = hit.get("key_results") or {}
                        subtask_sts = kr.get("subtask_statuses", [])
                        if subtask_sts:
                            remaining_tools: set[str] = set()
                            for sub in subtask_sts:
                                if not sub.get("satisfied", False):
                                    remaining_tools.update(sub.get("missing_tools", []))
                            if remaining_tools:
                                remaining_part = f" | Remaining: {', '.join(sorted(remaining_tools))}"
                    line = f'[Cross-run] Similar: "{hit["goal"]}"{tools_part}{status_part} | {hit["summary"]}'
                    if remaining_part:
                        line += remaining_part
                    cross_run_lines.append(line)

                # Phase 7.4: suppress duplicate injection for the same run+goal key
                if cross_run_lines:
                    if cache_key in self._injected_cross_run_keys:
                        # Already injected for this run+goal — return base content only
                        result = base_result[:_CONTEXT_CAP] if base_result else base_result
                        self._logger.debug("cross-run dedup skip key=%s", cache_key)
                        self._logger.info(
                            "CONTEXT INJECT missions=%d cross_run_hits=%d chars=%d cached=%s hits=[%s]",
                            len(summaries), 0, len(result), True, "-",
                        )
                        return result
                    self._injected_cross_run_keys.add(cache_key)

            except Exception as exc:  # noqa: BLE001
                self._logger.debug("cross-run cascade query failed (non-fatal): %s", exc)

        if not cross_run_lines:
            result = base_result[:_CONTEXT_CAP] if base_result else base_result
            self._logger.info(
                "CONTEXT INJECT missions=%d cross_run_hits=%d chars=%d cached=%s hits=[%s]",
                len(summaries), 0, len(result),
                f"{state.get('run_id', '')}:{self._get_current_goal_text(state)}" in self._cascade_cache,
                "-",
            )
            return result

        # Build attribution string from source_layer and score fields
        attribution_parts = [
            f"{hit.get('source_layer', '?')}:{hit.get('score', 0.0):.2f}"
            for hit in hits
        ]
        attribution = ", ".join(attribution_parts) if attribution_parts else "-"

        # Combine: existing content takes priority, cross-run hits fill remaining capacity
        remaining = _CONTEXT_CAP - len(base_result)
        cross_run_text = "\n".join(cross_run_lines)
        if remaining <= 0:
            result = base_result[:_CONTEXT_CAP]
        else:
            combined = base_result + ("\n" if base_result else "") + cross_run_text
            result = combined[:_CONTEXT_CAP]

        self._logger.info(
            "CONTEXT INJECT missions=%d cross_run_hits=%d chars=%d cached=%s hits=[%s]",
            len(summaries), len(cross_run_lines), len(result),
            f"{state.get('run_id', '')}:{self._get_current_goal_text(state)}" in self._cascade_cache,
            attribution,
        )
        return result

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
        if len(trace) > _PIPELINE_TRACE_CAP:
            del trace[: len(trace) - _PIPELINE_TRACE_CAP]
