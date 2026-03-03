"""Tests for summarize_text tool."""

import unittest

from agentic_workflows.tools.summarize_text import SummarizeTextTool


class TestSummarizeTextTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = SummarizeTextTool()
        self.long_text = (
            "The quick brown fox jumps over the lazy dog. "
            "Python is a popular programming language. "
            "Machine learning algorithms can process large datasets. "
            "Natural language processing helps computers understand text. "
            "Data science combines statistics and programming. "
            "Artificial intelligence is transforming many industries. "
            "Deep learning models require significant computing power. "
            "Cloud computing provides scalable infrastructure. "
            "Open source software powers most of the internet. "
            "Version control systems help teams collaborate effectively."
        )

    def test_basic_summarize(self) -> None:
        result = self.tool.execute({"text": self.long_text, "max_sentences": 3})
        self.assertIn("summary", result)
        self.assertEqual(result["sentences"], 3)
        self.assertIn("key_topics", result)
        self.assertLess(result["compression_ratio"], 1.0)

    def test_short_text_no_compression(self) -> None:
        result = self.tool.execute({"text": "Hello world.", "max_sentences": 5})
        self.assertEqual(result["compression_ratio"], 1.0)

    def test_frequency_method(self) -> None:
        result = self.tool.execute({"text": self.long_text, "method": "frequency", "max_sentences": 2})
        self.assertEqual(result["sentences"], 2)

    def test_position_method(self) -> None:
        result = self.tool.execute({"text": self.long_text, "method": "position", "max_sentences": 2})
        self.assertEqual(result["sentences"], 2)

    def test_combined_method(self) -> None:
        result = self.tool.execute({"text": self.long_text, "method": "combined", "max_sentences": 3})
        self.assertEqual(result["sentences"], 3)

    def test_key_topics_extracted(self) -> None:
        result = self.tool.execute({"text": self.long_text})
        self.assertIsInstance(result["key_topics"], list)
        self.assertGreater(len(result["key_topics"]), 0)

    def test_empty_text_error(self) -> None:
        result = self.tool.execute({"text": ""})
        self.assertIn("error", result)

    def test_invalid_method(self) -> None:
        result = self.tool.execute({"text": "test", "method": "neural"})
        self.assertIn("error", result)

    def test_max_sentences_capped(self) -> None:
        result = self.tool.execute({"text": self.long_text, "max_sentences": 100})
        self.assertLessEqual(result["sentences"], 10)


if __name__ == "__main__":
    unittest.main()
