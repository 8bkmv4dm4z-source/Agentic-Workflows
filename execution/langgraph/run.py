from __future__ import annotations

from execution.langgraph.graph import LangGraphOrchestrator


def main() -> None:
    orchestrator = LangGraphOrchestrator()
    user_input = """Please complete these 4 tasks in order, one at a time:

Task 1: Use repeat_message tool to repeat this exact message: "Agent loop is working!"
Task 2: Use sort_array tool to sort these numbers in ascending order: 5, 2, 8, 1, 9, 3
Task 3: Use string_ops tool with operation "uppercase" on this text: "the quick brown fox"
Task 4: Use write_file tool to write the fibonacci sequence until the 100th number to fib.txt
After completing all tasks, emit finish with a summary."""
    result = orchestrator.run(user_input)
    print("RUN ID:", result["run_id"])
    print("TOOLS USED:")
    for item in result["tools_used"]:
        print(f"  #{item['call']} {item['tool']} {item['result']}")
    print("ANSWER:", result["answer"])


if __name__ == "__main__":
    main()
