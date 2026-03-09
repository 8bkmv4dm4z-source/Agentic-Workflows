from __future__ import annotations

"""Typed handoff schemas for multi-agent sub-task delegation.

TaskHandoff and HandoffResult define the contract between the supervisor
router and specialist agents.  These are Pydantic BaseModels with
extra="forbid" for runtime schema enforcement at handoff boundaries.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class TaskHandoff(BaseModel):
    """A sub-task routed from the supervisor to a specialist."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    specialist: Literal["supervisor", "executor", "evaluator"]
    mission_id: int
    tool_scope: list[str]
    input_context: dict[str, Any]
    token_budget: int


class HandoffResult(BaseModel):
    """Result returned from a specialist after completing a handoff."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    specialist: Literal["supervisor", "executor", "evaluator"]
    status: Literal["success", "error", "timeout"]
    output: dict[str, Any]
    tokens_used: int


def create_handoff(
    *,
    task_id: str,
    specialist: Literal["supervisor", "executor", "evaluator"],
    mission_id: int,
    tool_scope: list[str] | None = None,
    input_context: dict[str, Any] | None = None,
    token_budget: int = 4096,
) -> TaskHandoff:
    """Build a TaskHandoff with sensible defaults."""
    return TaskHandoff(
        task_id=task_id,
        specialist=specialist,
        mission_id=mission_id,
        tool_scope=tool_scope or [],
        input_context=input_context or {},
        token_budget=token_budget,
    )


def create_handoff_result(
    *,
    task_id: str,
    specialist: Literal["supervisor", "executor", "evaluator"],
    status: Literal["success", "error", "timeout"] = "success",
    output: dict[str, Any] | None = None,
    tokens_used: int = 0,
) -> HandoffResult:
    """Build a HandoffResult with sensible defaults."""
    return HandoffResult(
        task_id=task_id,
        specialist=specialist,
        status=status,
        output=output or {},
        tokens_used=tokens_used,
    )
