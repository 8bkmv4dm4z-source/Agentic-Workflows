"""Tests for encode_decode tool."""

import unittest

from agentic_workflows.tools.encode_decode import EncodeDecodeTool


class TestEncodeDecodeTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = EncodeDecodeTool()

    def test_base64_encode(self) -> None:
        result = self.tool.execute({"content": "hello world", "operation": "base64_encode"})
        self.assertEqual(result["result"], "aGVsbG8gd29ybGQ=")

    def test_base64_decode(self) -> None:
        result = self.tool.execute({"content": "aGVsbG8gd29ybGQ=", "operation": "base64_decode"})
        self.assertEqual(result["result"], "hello world")

    def test_url_encode(self) -> None:
        result = self.tool.execute({"content": "hello world&foo=bar", "operation": "url_encode"})
        self.assertNotIn(" ", result["result"])
        self.assertIn("%20", result["result"])

    def test_url_decode(self) -> None:
        result = self.tool.execute({"content": "hello%20world", "operation": "url_decode"})
        self.assertEqual(result["result"], "hello world")

    def test_hex_encode(self) -> None:
        result = self.tool.execute({"content": "AB", "operation": "hex_encode"})
        self.assertEqual(result["result"], "4142")

    def test_hex_decode(self) -> None:
        result = self.tool.execute({"content": "4142", "operation": "hex_decode"})
        self.assertEqual(result["result"], "AB")

    def test_html_escape(self) -> None:
        result = self.tool.execute({"content": "<b>hi</b>", "operation": "html_escape"})
        self.assertEqual(result["result"], "&lt;b&gt;hi&lt;/b&gt;")

    def test_html_unescape(self) -> None:
        result = self.tool.execute({"content": "&lt;b&gt;", "operation": "html_unescape"})
        self.assertEqual(result["result"], "<b>")

    def test_missing_content(self) -> None:
        result = self.tool.execute({"operation": "base64_encode"})
        self.assertIn("error", result)

    def test_missing_operation(self) -> None:
        result = self.tool.execute({"content": "test"})
        self.assertIn("error", result)

    def test_invalid_operation(self) -> None:
        result = self.tool.execute({"content": "test", "operation": "rot13"})
        self.assertIn("error", result)

    def test_invalid_base64_decode(self) -> None:
        result = self.tool.execute({"content": "!!!invalid!!!", "operation": "base64_decode"})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
