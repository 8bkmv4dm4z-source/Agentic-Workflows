# schemas.py

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no unexpected fields

    action: Literal["tool"]
    tool_name: str
    args: dict[str, Any]


class FinishAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["finish"]
    answer: str
