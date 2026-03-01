# agent_state.py

import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal, TypedDict


class AgentMessage(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None


@dataclass
class AgentState:
    messages: list[AgentMessage]
    step: int = 0
    seen_tool_calls: set[str] = field(default_factory=set)

    def add_message(
        self,
        role: Literal["system", "user", "assistant", "tool"],
        content: str,
        name: str | None = None,
    ) -> None:

        message: AgentMessage = {
            "role": role,
            "content": content,
        }

        if name is not None:
            message["name"] = name

        self.messages.append(message)

    def register_tool_call(self, tool_name: str, args: dict):
        signature_raw = tool_name + json.dumps(args, sort_keys=True)
        signature = hashlib.sha256(signature_raw.encode()).hexdigest()

        if signature in self.seen_tool_calls:
            return False

        self.seen_tool_calls.add(signature)
        return True
