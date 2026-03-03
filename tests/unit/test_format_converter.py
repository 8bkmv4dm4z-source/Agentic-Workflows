"""Tests for format_converter tool."""

import json
import unittest

from agentic_workflows.tools.format_converter import FormatConverterTool


class TestFormatConverterTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = FormatConverterTool()

    def test_json_to_csv(self) -> None:
        data = json.dumps([{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}])
        result = self.tool.execute({"content": data, "from_format": "json", "to_format": "csv"})
        self.assertNotIn("error", result)
        self.assertIn("name", result["result"])
        self.assertIn("Alice", result["result"])

    def test_csv_to_json(self) -> None:
        csv_text = "name,age\nAlice,30\nBob,25"
        result = self.tool.execute({"content": csv_text, "from_format": "csv", "to_format": "json"})
        self.assertNotIn("error", result)
        parsed = json.loads(result["result"])
        self.assertEqual(len(parsed), 2)

    def test_json_to_yaml(self) -> None:
        data = json.dumps({"name": "Alice", "active": True})
        result = self.tool.execute({"content": data, "from_format": "json", "to_format": "yaml"})
        self.assertNotIn("error", result)
        self.assertIn("name", result["result"])

    def test_ini_to_json(self) -> None:
        ini = "[database]\nhost = localhost\nport = 5432"
        result = self.tool.execute({"content": ini, "from_format": "ini", "to_format": "json"})
        self.assertNotIn("error", result)
        parsed = json.loads(result["result"])
        self.assertIn("database", parsed)

    def test_auto_detect_json(self) -> None:
        result = self.tool.execute({"content": '{"key": "value"}', "to_format": "yaml"})
        self.assertEqual(result["from_format"], "json")

    def test_same_format_passthrough(self) -> None:
        content = '{"a": 1}'
        result = self.tool.execute({"content": content, "from_format": "json", "to_format": "json"})
        self.assertEqual(result["result"], content)

    def test_missing_content(self) -> None:
        result = self.tool.execute({"to_format": "json"})
        self.assertIn("error", result)

    def test_missing_to_format(self) -> None:
        result = self.tool.execute({"content": "{}"})
        self.assertIn("error", result)

    def test_unsupported_format(self) -> None:
        result = self.tool.execute({"content": "data", "from_format": "xml", "to_format": "json"})
        self.assertIn("error", result)

    def test_invalid_json_input(self) -> None:
        result = self.tool.execute({"content": "not json", "from_format": "json", "to_format": "csv"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
