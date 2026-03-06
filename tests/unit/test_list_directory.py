"""Tests for list_directory tool."""

import unittest

from agentic_workflows.tools.list_directory import ListDirectoryTool


class TestListDirectoryTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = ListDirectoryTool()

    def test_list_current_dir(self) -> None:
        result = self.tool.execute({"path": "."})
        self.assertIn("entries", result)
        self.assertGreater(result["total_count"], 0)
        self.assertFalse(result["truncated"])

    def test_list_with_pattern(self) -> None:
        result = self.tool.execute({"path": ".", "pattern": "*.py"})
        for entry in result["entries"]:
            self.assertTrue(entry["name"].endswith(".py"))

    def test_entry_has_metadata(self) -> None:
        result = self.tool.execute({"path": "."})
        if result["entries"]:
            entry = result["entries"][0]
            self.assertIn("name", entry)
            self.assertIn("path", entry)
            self.assertIn("type", entry)
            self.assertIn("size_bytes", entry)
            self.assertIn("modified", entry)

    def test_recursive_listing(self) -> None:
        result_flat = self.tool.execute({"path": ".", "pattern": "*.py"})
        result_recursive = self.tool.execute({"path": ".", "recursive": True, "pattern": "*.py"})
        self.assertGreaterEqual(result_recursive["total_count"], result_flat["total_count"])

    def test_max_results_cap(self) -> None:
        result = self.tool.execute({"path": ".", "recursive": True, "max_results": 3})
        self.assertLessEqual(result["total_count"], 3)

    def test_not_a_directory(self) -> None:
        result = self.tool.execute({"path": "pyproject.toml"})
        self.assertIn("error", result)

    def test_path_traversal_blocked(self) -> None:
        result = self.tool.execute({"path": "/etc"})
        self.assertIn("error", result)

    def test_hidden_files_excluded_by_default(self) -> None:
        result = self.tool.execute({"path": "."})
        for entry in result["entries"]:
            self.assertFalse(entry["name"].startswith("."))

    def test_include_hidden(self) -> None:
        result = self.tool.execute({"path": ".", "include_hidden": True})
        names = [e["name"] for e in result["entries"]]
        # .git or .gitignore likely exists
        has_hidden = any(n.startswith(".") for n in names)
        self.assertTrue(has_hidden)


if __name__ == "__main__":
    unittest.main()
