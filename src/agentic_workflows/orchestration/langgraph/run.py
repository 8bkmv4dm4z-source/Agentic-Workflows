from __future__ import annotations

"""CLI entrypoint for a quick Phase 1 LangGraph run demonstration."""

import sys
from pathlib import Path

# Allow running this file directly while still supporting package execution:
#   python -m agentic_workflows.orchestration.langgraph.run
if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[4]
    src_root = repo_root / "src"
    for p in (str(repo_root), str(src_root)):
        if p not in sys.path:
            sys.path.insert(0, p)

from agentic_workflows.orchestration.langgraph.langgraph_orchestrator import LangGraphOrchestrator


def main() -> None:
    # This prompt intentionally exercises multiple deterministic tools.
    orchestrator = LangGraphOrchestrator()
    user_input = """Return exactly one JSON object per turn.
No XML tags, no markdown, and no prose outside JSON.
Use only these action schemas:
{"action":"tool","tool_name":"...","args":{...}}
{"action":"finish","answer":"..."}

Please complete these 5 tasks in order, one at a time.
Each task may have sub-tasks (1a, 1b, etc.) — complete them sequentially.

Task 1: Text Analysis Pipeline
  1a. Analyze this text for word count, sentence count, and key terms: "The quick brown fox jumps over the lazy dog. The dog barked loudly at the fox. Meanwhile, the brown cat watched from the fence."
  1b. Uppercase the following key terms and write them to analysis_results.txt: "fox, dog, brown"

Task 2: Data Analysis and Sorting
  2a. Analyze these numbers for summary statistics and outliers: [45, 23, 67, 12, 89, 34, 56, 78, 91, 150, 2, 33]
  2b. Sort the non-outlier values in descending order
  2c. Calculate the mean of the sorted non-outlier array

Task 3: JSON Processing
  3a. Parse and validate this JSON: '{"users":[{"name":"Alice","score":95},{"name":"Bob","score":82},{"name":"Charlie","score":91}]}'
  3b. Extract all user names using regex from: "Alice scored 95, Bob scored 82, Charlie scored 91"
  3c. Sort the names alphabetically, then write them to users_sorted.txt

Task 4: Pattern Matching and Transform
  4a. Use regex to extract all numbers from: "Order #123 has 5 items at $45.99 each, totaling $229.95 with 10% discount"
  4b. Calculate the sum and mean of the extracted numbers
  4c. Write a summary of extracted numbers and their stats to pattern_report.txt

Task 5: Fibonacci with Analysis
  5a. Write the first 50 fibonacci numbers to fib50.txt
  5b. Repeat the final summary as confirmation: "All 5 tasks completed successfully"

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
