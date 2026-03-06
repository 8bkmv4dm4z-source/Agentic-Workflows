"""Tests for search_files tool."""

import unittest

from agentic_workflows.tools.search_files import SearchFilesTool


class TestSearchFilesTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = SearchFilesTool()

    def test_find_python_files(self) -> None:
        result = self.tool.execute({"pattern": "*.py", "path": "src"})
        self.assertIn("matches", result)
        self.assertGreater(result["count"], 0)
        for m in result["matches"]:
            self.assertTrue(m["name"].endswith(".py"))

    def test_match_metadata(self) -> None:
        result = self.tool.execute({"pattern": "*.py", "path": "src", "max_results": 1})
        if result["matches"]:
            match = result["matches"][0]
            self.assertIn("path", match)
            self.assertIn("name", match)
            self.assertIn("size_bytes", match)

    def test_max_results_capped(self) -> None:
        result = self.tool.execute({"pattern": "*.py", "path": "src", "max_results": 2})
        self.assertLessEqual(result["count"], 2)

    def test_missing_pattern(self) -> None:
        result = self.tool.execute({"path": "."})
        self.assertIn("error", result)

    def test_path_traversal_blocked(self) -> None:
        result = self.tool.execute({"pattern": "*.py", "path": "/tmp"})
        self.assertIn("error", result)

    def test_no_matches(self) -> None:
        result = self.tool.execute({"pattern": "*.nonexistent_extension_xyz", "path": "."})
        self.assertEqual(result["count"], 0)

    def test_not_a_directory(self) -> None:
        result = self.tool.execute({"pattern": "*.py", "path": "pyproject.toml"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
