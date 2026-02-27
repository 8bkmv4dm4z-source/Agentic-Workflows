# schemas.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Dict, Any, Literal


class ToolAction(BaseModel):
    model_config = ConfigDict(extra="forbid")  # no unexpected fields

    action: Literal["tool"]
    tool_name: str
    args: Dict[str, Any]


class FinishAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["finish"]
    answer: str