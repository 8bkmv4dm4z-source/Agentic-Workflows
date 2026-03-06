"""Tests for compare_texts tool."""

import unittest
from pathlib import Path

from agentic_workflows.tools.compare_texts import CompareTextsTool


class TestCompareTextsTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = CompareTextsTool()

    def test_identical_texts(self) -> None:
        result = self.tool.execute({"text1": "hello world", "text2": "hello world"})
        self.assertEqual(result["similarity"], 1.0)
        self.assertEqual(result["changes"], 0)

    def test_different_texts_line_mode(self) -> None:
        result = self.tool.execute({"text1": "line one\nline two", "text2": "line one\nline three"})
        self.assertLess(result["similarity"], 1.0)
        self.assertGreater(result["changes"], 0)
        self.assertIn("diff", result)

    def test_word_mode(self) -> None:
        result = self.tool.execute({"text1": "the quick fox", "text2": "the slow fox", "mode": "word"})
        self.assertEqual(result["mode"], "word")
        self.assertGreater(result["deletions"], 0)
        self.assertGreater(result["additions"], 0)

    def test_char_mode(self) -> None:
        result = self.tool.execute({"text1": "abc", "text2": "adc", "mode": "char"})
        self.assertEqual(result["mode"], "char")
        self.assertLess(result["similarity"], 1.0)

    def test_file_inputs(self, tmp_path: Path | None = None) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f1 = Path(tmp) / "a.txt"
            f2 = Path(tmp) / "b.txt"
            f1.write_text("hello", encoding="utf-8")
            f2.write_text("world", encoding="utf-8")
            result = self.tool.execute({"file1": str(f1), "file2": str(f2)})
            self.assertIn("similarity", result)
            self.assertLess(result["similarity"], 1.0)

    def test_missing_text1(self) -> None:
        result = self.tool.execute({"text2": "hello"})
        self.assertIn("error", result)

    def test_missing_text2(self) -> None:
        result = self.tool.execute({"text1": "hello"})
        self.assertIn("error", result)

    def test_invalid_mode(self) -> None:
        result = self.tool.execute({"text1": "a", "text2": "b", "mode": "sentence"})
        self.assertIn("error", result)

    def test_empty_texts(self) -> None:
        result = self.tool.execute({"text1": "", "text2": ""})
        self.assertEqual(result["similarity"], 1.0)


if __name__ == "__main__":
    unittest.main()
