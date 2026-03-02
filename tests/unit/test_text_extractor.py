"""Unit tests for pure text extraction helpers."""

from __future__ import annotations

import unittest

from agentic_workflows.orchestration.langgraph import text_extractor


class TestTextExtractor(unittest.TestCase):
    def test_extract_quoted_text(self) -> None:
        text = 'Please repeat "hello world" now'
        self.assertEqual(text_extractor.extract_quoted_text(text), "hello world")

    def test_extract_numbers_from_text(self) -> None:
        numbers = text_extractor.extract_numbers_from_text("Sort -5, 2, 11 and 0")
        self.assertEqual(numbers, [-5, 2, 11, 0])

    def test_extract_fibonacci_count_default(self) -> None:
        self.assertEqual(text_extractor.extract_fibonacci_count("Write fibonacci values"), 100)

    def test_fibonacci_csv(self) -> None:
        self.assertEqual(text_extractor.fibonacci_csv(6), "0, 1, 1, 2, 3, 5")

    def test_extract_missions_from_numbered_lines(self) -> None:
        payload = "1. Sort numbers\n2. Write output to out.txt"
        self.assertEqual(
            text_extractor.extract_missions(payload),
            ["1. Sort numbers", "2. Write output to out.txt"],
        )

    def test_extract_write_path_from_mission(self) -> None:
        mission = "Save report to ./tmp/analysis_results.txt."
        self.assertEqual(
            text_extractor.extract_write_path_from_mission(mission),
            "./tmp/analysis_results.txt",
        )

    def test_parse_csv_int_list(self) -> None:
        self.assertEqual(text_extractor.parse_csv_int_list("1, 2, -3"), [1, 2, -3])
        self.assertIsNone(text_extractor.parse_csv_int_list("1, nope, 3"))


if __name__ == "__main__":
    unittest.main()
