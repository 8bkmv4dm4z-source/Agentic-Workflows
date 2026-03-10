import json
import time
import unittest

from agentic_workflows.orchestration.langgraph.mission_parser import (
    IntentClassification,
    MissionStep,
    StructuredPlan,
    _classify_intent,
    _deterministic_classify,
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


    def test_prose_clause_splitting_then(self) -> None:
        """Single-line prose with 'then' and 'and <verb>' splits into steps."""
        text = (
            "Sort the array [42, 7, 19, 3, 88, 15, 31] in ascending order, "
            "then calculate the mean and median of the sorted result, "
            "and write a summary to results.txt"
        )
        plan = parse_missions(text, timeout_seconds=0)
        self.assertEqual(len(plan.steps), 3)
        self.assertIn("sort_array", plan.steps[0].suggested_tools)
        self.assertIn("math_stats", plan.steps[1].suggested_tools)
        self.assertIn("write_file", plan.steps[2].suggested_tools)
        # Sequential dependencies
        self.assertEqual(plan.steps[0].dependencies, [])
        self.assertIn("1", plan.steps[1].dependencies)
        self.assertIn("2", plan.steps[2].dependencies)

    def test_prose_clause_no_split_on_noun_and(self) -> None:
        """'and' connecting nouns (not action verbs) should NOT split."""
        text = "Calculate the mean and median of [1, 2, 3]"
        plan = parse_missions(text, timeout_seconds=0)
        self.assertEqual(len(plan.steps), 1)

    def test_prose_clause_semicolons(self) -> None:
        """Semicolons split into separate steps."""
        text = "Sort [3,1,2]; write the result to output.txt"
        plan = parse_missions(text, timeout_seconds=0)
        self.assertEqual(len(plan.steps), 2)
        self.assertIn("sort_array", plan.steps[0].suggested_tools)
        self.assertIn("write_file", plan.steps[1].suggested_tools)

    def test_prose_clause_and_then(self) -> None:
        """'and then' splits into separate steps."""
        text = "Sort the numbers and then write them to a file"
        plan = parse_missions(text, timeout_seconds=0)
        self.assertEqual(len(plan.steps), 2)

    def test_prose_no_tool_matches_stays_single(self) -> None:
        """Prose with conjunctions but no tool-keyword matches stays single."""
        text = "Think about the problem, then explain it, and summarize your thoughts"
        plan = parse_missions(text, timeout_seconds=0)
        # 'summarize' matches summarize_text but no second tool => stays single
        # Actually 'explain' has no tool match, 'think' has no tool match
        # Only 'summarize' matches => tool_hits < 2 => single
        self.assertEqual(len(plan.steps), 1)


class _MockProvider:
    """Minimal ChatProvider mock for intent classification tests."""

    def __init__(self, response: str | None = None, delay: float = 0.0):
        self._response = response
        self._delay = delay

    def generate(
        self,
        messages: list[dict],
        system: str | None = None,
        response_schema: dict | None = None,
    ) -> str:
        if self._delay > 0:
            time.sleep(self._delay)
        if self._response is None:
            raise RuntimeError("provider error")
        return self._response


class IntentClassificationTests(unittest.TestCase):
    """Tests for intent classification in mission_parser."""

    def _make_simple_plan(self) -> StructuredPlan:
        """Plan with 1 step, simple tools."""
        steps = [MissionStep(id="1", description="sort the numbers", suggested_tools=["sort_array"])]
        return StructuredPlan(steps=steps, flat_missions=["Task 1: sort the numbers"], parsing_method="structured")

    def _make_complex_plan(self) -> StructuredPlan:
        """Plan with 3+ steps."""
        steps = [
            MissionStep(id="1", description="analyze data", suggested_tools=["data_analysis"]),
            MissionStep(id="2", description="write results", suggested_tools=["write_file"]),
            MissionStep(id="3", description="summarize", suggested_tools=["summarize_text"]),
        ]
        return StructuredPlan(
            steps=steps,
            flat_missions=["Task 1: analyze data", "Task 2: write results", "Task 3: summarize"],
            parsing_method="structured",
        )

    # Test 1: _deterministic_classify returns "simple" for 1-2 step plans with simple tools
    def test_deterministic_simple_plan(self) -> None:
        plan = self._make_simple_plan()
        result = _deterministic_classify(plan)
        self.assertIsInstance(result, IntentClassification)
        self.assertEqual(result.complexity, "simple")
        self.assertEqual(result.source, "deterministic_fallback")
        self.assertGreater(result.confidence, 0.0)

    # Test 2: _deterministic_classify returns "complex" for 3+ step plans
    def test_deterministic_complex_many_steps(self) -> None:
        plan = self._make_complex_plan()
        result = _deterministic_classify(plan)
        self.assertEqual(result.complexity, "complex")
        self.assertEqual(result.source, "deterministic_fallback")

    # Test 3: _deterministic_classify returns "complex" when parsing_method is "regex_fallback"
    def test_deterministic_complex_regex_fallback(self) -> None:
        steps = [MissionStep(id="1", description="do something")]
        plan = StructuredPlan(steps=steps, flat_missions=["do something"], parsing_method="regex_fallback")
        result = _deterministic_classify(plan)
        self.assertEqual(result.complexity, "complex")

    # Test 4: _deterministic_classify returns "complex" when complex tools are suggested
    def test_deterministic_complex_tools(self) -> None:
        steps = [MissionStep(id="1", description="analyze", suggested_tools=["data_analysis"])]
        plan = StructuredPlan(steps=steps, flat_missions=["analyze"], parsing_method="structured")
        result = _deterministic_classify(plan)
        self.assertEqual(result.complexity, "complex")

    # Test 5: _classify_intent with mock provider returning valid JSON sets source="llm"
    def test_classify_intent_llm_success(self) -> None:
        plan = self._make_simple_plan()
        response = json.dumps({"complexity": "simple", "mission_type": "tool_call"})
        provider = _MockProvider(response=response)
        result = _classify_intent("sort [3,1,2]", plan, provider, timeout=2.0)
        self.assertEqual(result.source, "llm")
        self.assertEqual(result.complexity, "simple")
        self.assertEqual(result.mission_type, "tool_call")

    # Test 6: _classify_intent with timeout falls back to deterministic
    def test_classify_intent_timeout_fallback(self) -> None:
        plan = self._make_simple_plan()
        response = json.dumps({"complexity": "simple", "mission_type": "tool_call"})
        provider = _MockProvider(response=response, delay=3.0)
        result = _classify_intent("sort [3,1,2]", plan, provider, timeout=0.1)
        self.assertEqual(result.source, "deterministic_fallback")

    # Test 7: _classify_intent with invalid JSON falls back to deterministic
    def test_classify_intent_invalid_json_fallback(self) -> None:
        plan = self._make_simple_plan()
        provider = _MockProvider(response="not valid json at all")
        result = _classify_intent("sort [3,1,2]", plan, provider, timeout=2.0)
        self.assertEqual(result.source, "deterministic_fallback")

    # Test 8: StructuredPlan.to_dict() includes intent_classification; from_dict() restores it
    def test_structured_plan_serialization_with_intent(self) -> None:
        plan = self._make_simple_plan()
        plan.intent_classification = IntentClassification(
            complexity="simple", mission_type="tool_call", confidence=0.8, source="llm"
        )
        d = plan.to_dict()
        self.assertIn("intent_classification", d)
        self.assertEqual(d["intent_classification"]["complexity"], "simple")

        restored = StructuredPlan.from_dict(d)
        self.assertIsNotNone(restored.intent_classification)
        self.assertEqual(restored.intent_classification.complexity, "simple")
        self.assertEqual(restored.intent_classification.source, "llm")

    # Test 9: from_dict() with old data (no intent_classification key) returns None
    def test_structured_plan_from_dict_old_data(self) -> None:
        old_data = {
            "steps": [{"id": "1", "description": "test"}],
            "flat_missions": ["test"],
            "parsing_method": "structured",
        }
        restored = StructuredPlan.from_dict(old_data)
        self.assertIsNone(restored.intent_classification)


if __name__ == "__main__":
    unittest.main()
