"""Tests for search_content tool."""

import unittest

from agentic_workflows.tools.search_content import SearchContentTool


class TestSearchContentTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = SearchContentTool()

    def test_find_pattern_in_source(self) -> None:
        result = self.tool.execute({"pattern": "def execute", "path": "src", "file_pattern": "*.py"})
        self.assertIn("matches", result)
        self.assertGreater(len(result["matches"]), 0)

    def test_match_has_line_info(self) -> None:
        result = self.tool.execute({"pattern": "class Tool", "path": "src", "max_results": 1})
        if result["matches"]:
            match = result["matches"][0]
            self.assertIn("file", match)
            self.assertIn("line_number", match)
            self.assertIn("line", match)

    def test_context_lines(self) -> None:
        result = self.tool.execute({
            "pattern": "class Tool",
            "path": "src",
            "context_lines": 2,
            "max_results": 1,
        })
        if result["matches"]:
            match = result["matches"][0]
            self.assertIn("context_before", match)
            self.assertIn("context_after", match)

    def test_case_insensitive(self) -> None:
        result = self.tool.execute({
            "pattern": "CLASS TOOL",
            "path": "src",
            "case_sensitive": False,
            "max_results": 1,
        })
        self.assertGreater(len(result["matches"]), 0)

    def test_regex_mode(self) -> None:
        result = self.tool.execute({
            "pattern": r"def \w+_\w+",
            "path": "src",
            "is_regex": True,
            "max_results": 1,
        })
        self.assertGreater(len(result["matches"]), 0)

    def test_missing_pattern(self) -> None:
        result = self.tool.execute({"path": "."})
        self.assertIn("error", result)

    def test_no_matches(self) -> None:
        result = self.tool.execute({"pattern": "XYZZY_NONEXISTENT_STRING_12345", "path": "src"})
        self.assertEqual(len(result["matches"]), 0)

    def test_max_results_capped(self) -> None:
        result = self.tool.execute({"pattern": "import", "path": "src", "max_results": 3})
        self.assertLessEqual(len(result["matches"]), 3)

    def test_path_traversal_blocked(self) -> None:
        result = self.tool.execute({"pattern": "test", "path": "/etc"})
        self.assertIn("error", result)

    def test_files_with_matches_count(self) -> None:
        result = self.tool.execute({"pattern": "def execute", "path": "src", "file_pattern": "*.py"})
        self.assertGreater(result["files_with_matches"], 0)


if __name__ == "__main__":
    unittest.main()
