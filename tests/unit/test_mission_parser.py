import unittest

from agentic_workflows.orchestration.langgraph.mission_parser import (
    StructuredPlan,
    _extract_missions_regex_fallback,
    parse_missions,
)


class MissionParserTests(unittest.TestCase):
    def test_numbered_tasks_basic(self) -> None:
        text = "Task 1: Do the first thing\nTask 2: Do the second thing"
        plan = parse_missions(text)
        self.assertEqual(plan.parsing_method, "structured")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].id, "1")
        self.assertEqual(plan.steps[0].description, "Do the first thing")
        self.assertEqual(plan.steps[1].id, "2")
        self.assertEqual(plan.steps[1].description, "Do the second thing")

    def test_numbered_dot_format(self) -> None:
        text = "1. Sort the array\n2. Write to file"
        plan = parse_missions(text)
        self.assertEqual(plan.parsing_method, "structured")
        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.steps[0].description, "Sort the array")

    def test_bullet_list_parsing(self) -> None:
        text = "- task one\n- task two\n- task three"
        plan = parse_missions(text)
        self.assertEqual(plan.parsing_method, "structured")
        self.assertEqual(len(plan.steps), 3)
        self.assertEqual(plan.steps[0].description, "task one")
        self.assertEqual(plan.steps[2].description, "task three")

    def test_nested_subtasks(self) -> None:
        text = "Task 1: Main task\n  1a. First subtask\n  1b. Second subtask\nTask 2: Another task"
        plan = parse_missions(text)
        self.assertEqual(plan.parsing_method, "structured")
        # Should have 4 steps: 2 top-level + 2 sub-tasks
        self.assertEqual(len(plan.steps), 4)
        subtasks = [s for s in plan.steps if s.parent_id is not None]
        self.assertEqual(len(subtasks), 2)
        self.assertEqual(subtasks[0].id, "1a")
        self.assertEqual(subtasks[0].parent_id, "1")
        self.assertEqual(subtasks[1].id, "1b")
        self.assertEqual(subtasks[1].parent_id, "1")

    def test_dot_notation_subtasks(self) -> None:
        text = "Task 1: Main task\n  1.1 First subtask\n  1.2 Second subtask\n"
        plan = parse_missions(text)
        subtasks = [s for s in plan.steps if s.parent_id is not None]
        self.assertEqual(len(subtasks), 2)
        self.assertEqual(subtasks[0].id, "1.1")
        self.assertEqual(subtasks[1].id, "1.2")

    def test_multiline_description_merged(self) -> None:
        text = (
            "Task 1: Sort the array\n"
            "  in ascending order with duplicates removed\n"
            "Task 2: Write output"
        )
        plan = parse_missions(text)
        top_level = [s for s in plan.steps if s.parent_id is None]
        self.assertEqual(len(top_level), 2)
        self.assertIn("ascending order", top_level[0].description)

    def test_tool_suggestion_heuristics(self) -> None:
        text = "Task 1: sort the numbers\nTask 2: write to output file\nTask 3: analyze the text"
        plan = parse_missions(text)
        self.assertIn("sort_array", plan.steps[0].suggested_tools)
        self.assertIn("write_file", plan.steps[1].suggested_tools)
        self.assertTrue(
            "text_analysis" in plan.steps[2].suggested_tools
            or "data_analysis" in plan.steps[2].suggested_tools
        )

    def test_empty_input_fallback(self) -> None:
        plan = parse_missions("")
        self.assertEqual(plan.parsing_method, "regex_fallback")
        self.assertEqual(plan.flat_missions, ["Primary mission"])

    def test_flat_missions_backward_compat(self) -> None:
        text = "Task 1: Do thing A\nTask 2: Do thing B\nTask 3: Do thing C"
        plan = parse_missions(text)
        self.assertEqual(len(plan.flat_missions), 3)
        self.assertTrue(plan.flat_missions[0].startswith("Task 1:"))
        self.assertTrue(plan.flat_missions[1].startswith("Task 2:"))
        self.assertTrue(plan.flat_missions[2].startswith("Task 3:"))

    def test_structured_plan_serializable(self) -> None:
        text = "Task 1: Sort items\nTask 2: Write results"
        plan = parse_missions(text)
        d = plan.to_dict()
        self.assertIn("steps", d)
        self.assertIn("flat_missions", d)
        self.assertIn("parsing_method", d)
        self.assertEqual(len(d["steps"]), 2)
        # Round-trip
        restored = StructuredPlan.from_dict(d)
        self.assertEqual(len(restored.steps), 2)
        self.assertEqual(restored.steps[0].id, plan.steps[0].id)
        self.assertEqual(restored.parsing_method, plan.parsing_method)

    def test_regex_fallback_matches_original(self) -> None:
        text = "Task 1: Do A\nSome random text\nTask 2: Do B"
        missions = _extract_missions_regex_fallback(text)
        self.assertEqual(len(missions), 2)
        self.assertIn("Task 1:", missions[0])
        self.assertIn("Task 2:", missions[1])

    def test_dependency_detection(self) -> None:
        text = "Task 1: First\nTask 2: Second\nTask 3: Third"
        plan = parse_missions(text)
        # Top-level tasks have sequential deps
        self.assertEqual(plan.steps[0].dependencies, [])
        self.assertIn("1", plan.steps[1].dependencies)
        self.assertIn("2", plan.steps[2].dependencies)

    def test_preamble_text_ignored(self) -> None:
        text = (
            "Return exactly one JSON object per turn.\n"
            "Use only these action schemas:\n"
            '{"action":"tool"}\n\n'
            'Task 1: repeat this message: "hello"\n'
            "Task 2: sort [3,1,2]"
        )
        plan = parse_missions(text)
        self.assertEqual(len(plan.flat_missions), 2)
        self.assertIn("Task 1:", plan.flat_missions[0])


if __name__ == "__main__":
    unittest.main()
