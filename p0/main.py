# main.py

from p0.orchestrator import Orchestrator


def main():
    agent = Orchestrator()

    user_input = """Please complete these 4 tasks in order, one at a time:

Task 1: Use repeat_message tool to repeat this exact message: "Agent loop is working!"

Task 2: Use sort_array tool to sort these numbers in ascending order: 5, 2, 8, 1, 9, 3

Task 3: Use string_ops tool with operation "uppercase" on this text: "the quick brown fox"

Task 4: Use write_file tool to write the following content to a file named 'fib.txt':
        the fibonacci sequence until the 100th number as a comma separated string 
        exmp: 1,2,3,5,8,13,21,34,55,89
        make sure to use the best tools for the runtime execution "

After completing all 4 tasks, emit finish with a summary of all 4 results."""

    result = agent.run(user_input)

    print("\n" + "=" * 60)
    print("TOOLS USED THIS RUN:")
    for entry in result.get("tools_used", []):
        print(f"  #{entry['call']} {entry['tool']}")
        print(f"       args:   {entry['args']}")
        print(f"       result: {entry['result']}")
    print()
    print("FINAL ANSWER:")
    print(result["answer"])
    print("=" * 60)


if __name__ == "__main__":
    main()
