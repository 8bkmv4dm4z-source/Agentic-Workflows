# orchestrator.py

import json
from typing import Any

from pydantic import ValidationError

from agentic_workflows.core.agent_state import AgentState
from agentic_workflows.core.llm_provider import LLMProvider
from agentic_workflows.errors import (
    FatalAgentError,
    InvalidJSONError,
    MissingActionError,
    RetryableAgentError,
    SchemaValidationError,
    UnknownActionError,
    UnknownToolError,
)
from agentic_workflows.logger import get_logger
from agentic_workflows.schemas import FinishAction, ToolAction
from agentic_workflows.tools.echo import EchoTool
from agentic_workflows.tools.math_stats import MathStatsTool
from agentic_workflows.tools.memoize import MemoizeTool
from agentic_workflows.tools.sort_array import SortArrayTool
from agentic_workflows.tools.string_ops import StringOpsTool
from agentic_workflows.tools.write_file import WriteFileTool


class Orchestrator:
    def __init__(self):
        self.llm = LLMProvider()
        self.logger = get_logger("orchestrator")
        self.tools = {
            "repeat_message": EchoTool(),
            "sort_array": SortArrayTool(),
            "string_ops": StringOpsTool(),
            "math_stats": MathStatsTool(),
            "write_file": WriteFileTool(),
            "memoize": MemoizeTool(),
        }
        self.max_steps = 20  # raised to handle multi-task sequences

        available_tools = list(self.tools.keys())
        tool_list_str = "\n".join(
            f"- {name}: {tool.description}" for name, tool in self.tools.items()
        )
        tool_names_str = ", ".join(available_tools)

        self.system_prompt = f"""
You are a deterministic tool-using agent.
You MUST respond ONLY with valid JSON. No markdown, no explanations, no extra text.

------------------------------------------------------------
CRITICAL: ONE JSON OBJECT PER RESPONSE
------------------------------------------------------------

You MUST return EXACTLY ONE JSON object per response.
Never output multiple JSON objects or a list of actions.
One response = one action = one JSON object.

------------------------------------------------------------
OUTPUT FORMAT
------------------------------------------------------------

To call a tool:
{{
  "action": "tool",
  "tool_name": "<one of: {tool_names_str}>",
  "args": {{ ... }}
}}

To finish (after ALL tasks are done):
{{
  "action": "finish",
  "answer": "<complete summary of all task results>"
}}

No other action values are allowed.

------------------------------------------------------------
AVAILABLE TOOLS (with exact arg names)
------------------------------------------------------------

{tool_list_str}

TOOL ARG REFERENCE — use these EXACT field names, no others:

  echo
    "message": "<string>"

  sort_array
    "items": [<list of numbers or strings>]
    "order": "asc" or "desc"  (optional, default: "asc")

  string_ops
    "text": "<string>"
    "operation": one of: uppercase, lowercase, reverse, length, trim,
                         replace, split, count_words, startswith, endswith, contains
    For replace: also add  "old": "<str>",  "new": "<str>"
    For split:   also add  "delimiter": "<str>"
    For startswith: also add "prefix": "<str>"
    For endswith:   also add "suffix": "<str>"
    For contains:   also add "substring": "<str>"

  math_stats
    For arithmetic (two numbers):
      "operation": add | subtract | multiply | divide | power
      "a": <number>,  "b": <number>
    For single number:
      "operation": sqrt | abs
      "a": <number>
    For list statistics:
      "operation": mean | median | mode | stdev | variance | min | max | sum
      "numbers": [<list of numbers>]

  write_file
    "path": "<filepath>",  "content": "<string to write>"

  memoize
    "key": "<filepath>",  "value": "<string value>"

------------------------------------------------------------
MULTI-TASK EXECUTION — SEQUENTIAL APPROACH
------------------------------------------------------------

When the user asks for multiple tasks, execute them ONE AT A TIME:

  Step 1: Call the tool for task 1.
  Step 2: After TOOL_RESULT arrives, note task 1 is done. Call tool for task 2.
  Step 3: After TOOL_RESULT arrives, note task 2 is done. Call tool for task 3.
  ... continue until all tasks are done ...
  Final step: Emit "finish" with a summary of ALL results.

IMPORTANT: Do NOT finish until ALL tasks from the user request are complete.

------------------------------------------------------------
FINISH RECOGNITION
------------------------------------------------------------

Only emit {{"action": "finish"}} when:
  - ALL tasks in the user request have been completed and have TOOL_RESULTs.

Do NOT finish after just one task if the user asked for multiple tasks.
Do NOT call the same tool with the same args twice.
Do NOT output multiple JSON objects — ONE object per response, always.

------------------------------------------------------------
TOOL RESULT HANDLING
------------------------------------------------------------

When you receive a TOOL_RESULT:
  - Note which task it completes.
  - Identify the next uncompleted task.
  - Call the appropriate tool for that next task.
  - Only emit "finish" when there are NO more tasks remaining.

------------------------------------------------------------
STRICT RULES
------------------------------------------------------------

- Always return valid JSON (one object).
- Never return empty output.
- Never return free-form text.
- Never invent new schema fields or arg names.
- Use ONLY the "args" field names shown in TOOL ARG REFERENCE.
"""

    def run(self, user_input: str):

        state = AgentState(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_input},
            ]
        )

        tool_call_count = 0  # track how many tool calls have succeeded
        tools_used: list = []  # ordered log of every tool call: (name, result_snippet)

        for step in range(self.max_steps):
            self.logger.info(f"Step {step + 1}/{self.max_steps}")
            state.step = step

            try:
                #  Call LLM
                model_output = self.llm.generate(state.messages).strip()
                self.logger.info(f"MODEL OUTPUT:\n{model_output}")

                # Add model's output to conversation history as assistant turn
                # This is critical — without it the model has no memory of what it said
                state.add_message(role="assistant", content=model_output)

                #  Validate
                action = self._validate_input(model_output)

                #  Tool handling
                if isinstance(action, ToolAction):
                    is_new = state.register_tool_call(action.tool_name, action.args)

                    if not is_new:
                        # Give model a chance to recover rather than hard crash
                        state.add_message(
                            role="system",
                            content=(
                                f"ERROR: You just called '{action.tool_name}' with the same "
                                f"arguments as a previous call. This is a duplicate — do NOT repeat it.\n"
                                f"You have completed {tool_call_count} tool call(s) so far.\n"
                                "Move on to the NEXT uncompleted task. Respond with ONE valid JSON object."
                            ),
                        )
                        continue

                    tool_result = self._handle_tool(action)
                    tool_call_count += 1

                    # Record in the run-level tools_used log
                    result_snippet = str(tool_result)[:120]
                    tools_used.append(
                        {
                            "call": tool_call_count,
                            "tool": action.tool_name,
                            "args": action.args,
                            "result": result_snippet,
                        }
                    )

                    state.add_message(
                        role="system",
                        content=(
                            f"TOOL_RESULT — Tool call #{tool_call_count} completed "
                            f"(tool: '{action.tool_name}'):\n"
                            f"{json.dumps(tool_result)}\n\n"
                            f"You have now completed {tool_call_count} tool call(s).\n"
                            "What is the NEXT task? Call the appropriate tool for it.\n"
                            "If ALL tasks from the user request are done, emit finish.\n"
                            "Respond with ONE valid JSON object only."
                        ),
                    )

                    continue

                #  Finish
                if isinstance(action, FinishAction):
                    # Log the full run summary
                    self.logger.info("=" * 60)
                    self.logger.info(f"RUN SUMMARY — {tool_call_count} tool call(s) used:")
                    for entry in tools_used:
                        self.logger.info(f"  #{entry['call']} {entry['tool']} → {entry['result']}")
                    self.logger.info(f"FINAL ANSWER: {action.answer}")
                    self.logger.info("=" * 60)
                    result = action.model_dump()
                    result["tools_used"] = tools_used
                    return result

            except RetryableAgentError as e:
                self.logger.warning(f"Retryable error: {e}")

                state.add_message(
                    role="system",
                    content=(
                        f"Previous output was invalid: {str(e)}.\n"
                        "Return exactly ONE valid JSON object. "
                        "Do not output multiple JSON objects."
                    ),
                )
                continue

            except FatalAgentError as e:
                self.logger.error(f"Fatal error: {e}")
                raise

        self.logger.warning("Max steps reached.")
        raise FatalAgentError("Max steps exceeded")

    def _handle_tool(self, action: ToolAction) -> dict[str, Any]:

        tool = self.tools.get(action.tool_name)

        if tool is None:
            available = list(self.tools.keys())
            raise UnknownToolError(
                f"Unknown tool '{action.tool_name}'. Valid tool_name values are: {available}"
            )

        result = tool.execute(action.args)

        self.logger.info(f"TOOL RESULT: {result}")

        return result

    def _validate_input(self, text: str) -> ToolAction | FinishAction:

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise InvalidJSONError(
                "Invalid JSON from model. You must return ONE JSON object only."
            ) from exc

        if "action" not in data:
            raise MissingActionError("Missing 'action' field.")

        action_type = data["action"]

        try:
            if action_type == "tool":
                return ToolAction(**data)

            elif action_type == "finish":
                return FinishAction(**data)

            else:
                raise UnknownActionError(f"Unknown action type: {action_type}")

        except ValidationError as e:
            raise SchemaValidationError(str(e)) from e
