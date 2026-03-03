"""Tests for classify_intent tool."""

import unittest

from agentic_workflows.tools.classify_intent import ClassifyIntentTool


class TestClassifyIntentTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = ClassifyIntentTool()

    def test_question_intent(self) -> None:
        result = self.tool.execute({"text": "What is the weather today?"})
        self.assertEqual(result["top_intent"], "question")
        self.assertGreater(result["confidence"], 0)

    def test_command_intent(self) -> None:
        result = self.tool.execute({"text": "Run the deployment script and restart the server"})
        self.assertEqual(result["top_intent"], "command")

    def test_search_intent(self) -> None:
        result = self.tool.execute({"text": "Search for all Python files and find the main module"})
        self.assertEqual(result["top_intent"], "search")

    def test_file_operation_intent(self) -> None:
        result = self.tool.execute({"text": "Create a new file and save the report"})
        self.assertEqual(result["top_intent"], "file_operation")

    def test_custom_categories(self) -> None:
        result = self.tool.execute({
            "text": "deploy to production",
            "categories": {"deployment": ["deploy", "release", "production"]},
        })
        self.assertIn("deployment", result["scores"])

    def test_matched_keywords_present(self) -> None:
        result = self.tool.execute({"text": "What is the meaning of life?"})
        self.assertIn("question", result["matched_keywords"])

    def test_ambiguity_detection(self) -> None:
        result = self.tool.execute({"text": "find and read the log file"})
        self.assertIn("is_ambiguous", result)

    def test_empty_text_error(self) -> None:
        result = self.tool.execute({"text": ""})
        self.assertIn("error", result)

    def test_no_match_returns_unknown(self) -> None:
        result = self.tool.execute({"text": "xyzzy plugh"})
        self.assertEqual(result["top_intent"], "unknown")


if __name__ == "__main__":
    unittest.main()
