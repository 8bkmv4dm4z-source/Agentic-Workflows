"""Tests for validate_data tool."""

import unittest

from agentic_workflows.tools.validate_data import ValidateDataTool


class TestValidateDataTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = ValidateDataTool()

    def test_required_pass(self) -> None:
        result = self.tool.execute({
            "data": {"name": "Alice"},
            "rules": {"name": [{"rule": "required"}]},
        })
        self.assertTrue(result["valid"])
        self.assertEqual(result["errors"], [])

    def test_required_fail(self) -> None:
        result = self.tool.execute({
            "data": {"name": ""},
            "rules": {"name": [{"rule": "required"}]},
        })
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["errors"]), 1)

    def test_type_check(self) -> None:
        result = self.tool.execute({
            "data": {"age": "twenty"},
            "rules": {"age": [{"rule": "type_check", "expected": "int"}]},
        })
        self.assertFalse(result["valid"])

    def test_min_max(self) -> None:
        result = self.tool.execute({
            "data": {"score": 150},
            "rules": {"score": [{"rule": "min", "value": 0}, {"rule": "max", "value": 100}]},
        })
        self.assertFalse(result["valid"])
        self.assertEqual(len(result["errors"]), 1)

    def test_range_pass(self) -> None:
        result = self.tool.execute({
            "data": {"value": 50},
            "rules": {"value": [{"rule": "range", "min": 0, "max": 100}]},
        })
        self.assertTrue(result["valid"])

    def test_regex(self) -> None:
        result = self.tool.execute({
            "data": {"code": "ABC123"},
            "rules": {"code": [{"rule": "regex", "pattern": r"^[A-Z]{3}\d{3}$"}]},
        })
        self.assertTrue(result["valid"])

    def test_email_valid(self) -> None:
        result = self.tool.execute({
            "data": {"email": "user@example.com"},
            "rules": {"email": [{"rule": "email"}]},
        })
        self.assertTrue(result["valid"])

    def test_email_invalid(self) -> None:
        result = self.tool.execute({
            "data": {"email": "not-an-email"},
            "rules": {"email": [{"rule": "email"}]},
        })
        self.assertFalse(result["valid"])

    def test_enum(self) -> None:
        result = self.tool.execute({
            "data": {"status": "active"},
            "rules": {"status": [{"rule": "enum", "values": ["active", "inactive"]}]},
        })
        self.assertTrue(result["valid"])

    def test_length(self) -> None:
        result = self.tool.execute({
            "data": {"name": "Al"},
            "rules": {"name": [{"rule": "length", "min": 3}]},
        })
        self.assertFalse(result["valid"])

    def test_data_not_dict(self) -> None:
        result = self.tool.execute({"data": "string", "rules": {}})
        self.assertIn("error", result)

    def test_string_rule_shorthand(self) -> None:
        result = self.tool.execute({
            "data": {"name": "Alice"},
            "rules": {"name": "required"},
        })
        self.assertTrue(result["valid"])


if __name__ == "__main__":
    unittest.main()
