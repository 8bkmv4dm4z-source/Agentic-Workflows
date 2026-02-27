from __future__ import annotations

"""CLI entrypoint for a quick Phase 1 LangGraph run demonstration."""

import sys
from pathlib import Path

# Allow running this file directly from `execution/langgraph/`:
#   python run.py
# while still supporting package execution:
#   python -m execution.langgraph.run
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from execution.langgraph.langgraph_orchestrator import LangGraphOrchestrator


def main() -> None:
    # This prompt intentionally exercises multiple deterministic tools.
    orchestrator = LangGraphOrchestrator()
    user_input = """Return exactly one JSON object per turn.
No XML tags, no markdown, and no prose outside JSON.
Use only these action schemas:
{"action":"tool","tool_name":"...","args":{...}}
{"action":"finish","answer":"..."}

Please complete these 4 tasks in order, one at a time:

Task 1: Use repeat_message tool to repeat this exact message: "Agent loop is working!"
Task 2: Use sort_array tool to sort these numbers in ascending order: 5, 2, 8, 1, 9, 3
Task 3: Use string_ops tool with operation "uppercase" on this text: "the quick brown fox"
Task 4: Use write_file tool to write the fibonacci sequence until the 100th number to fib.txt
After completing all tasks, emit finish with a summary."""
    result = orchestrator.run(user_input)
    # Run-level summary with mission and memo visibility for debugging.
    print("RUN ID:", result["run_id"])
    print("TOOLS USED:")
    for item in result["tools_used"]:
        print(f"  #{item['call']} {item['tool']} {item['result']}")
    print("MISSION REPORT:")
    for mission in result.get("mission_report", []):
        print(
            f"  mission {mission.get('mission_id')}: [{', '.join(mission.get('used_tools', []))}] "
            f"+ result={mission.get('result', '')}"
        )
    print("MEMO STORE ENTRIES:")
    for entry in result.get("memo_store_entries", []):
        print(
            "  "
            f"key={entry.get('key')} hash={entry.get('value_hash')} "
            f"source_tool={entry.get('source_tool')} step={entry.get('step')}"
        )
    print("DERIVED SNAPSHOT:", result.get("derived_snapshot", {}))
    print("ANSWER:", result["answer"])


if __name__ == "__main__":
    main()
