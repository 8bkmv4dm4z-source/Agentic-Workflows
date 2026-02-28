import unittest

from tools.task_list_parser import TaskListParserTool
from tools.text_analysis import TextAnalysisTool
from tools.data_analysis import DataAnalysisTool
from tools.json_parser import JsonParserTool
from tools.regex_matcher import RegexMatcherTool


class TaskListParserToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = TaskListParserTool()

    def test_basic_parsing(self) -> None:
        result = self.tool.execute({"text": "Task 1: Do A\nTask 2: Do B"})
        self.assertIn("tasks", result)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertIn("parsing_method", result)

    def test_empty_text_error(self) -> None:
        result = self.tool.execute({"text": ""})
        self.assertIn("error", result)

    def test_returns_flat_missions(self) -> None:
        result = self.tool.execute({"text": "Task 1: Sort\nTask 2: Write"})
        self.assertIn("flat_missions", result)
        self.assertEqual(len(result["flat_missions"]), 2)


class TextAnalysisToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = TextAnalysisTool()

    def test_word_count(self) -> None:
        result = self.tool.execute({"text": "hello world foo bar", "operation": "word_count"})
        self.assertEqual(result["word_count"], 4)

    def test_sentence_count(self) -> None:
        result = self.tool.execute({"text": "Hello world. How are you? Fine.", "operation": "sentence_count"})
        self.assertEqual(result["sentence_count"], 3)

    def test_char_count(self) -> None:
        result = self.tool.execute({"text": "abc def", "operation": "char_count"})
        self.assertEqual(result["char_count"], 7)
        self.assertEqual(result["char_count_no_spaces"], 6)

    def test_key_terms(self) -> None:
        result = self.tool.execute({"text": "python python java python java ruby", "operation": "key_terms"})
        self.assertEqual(result["key_terms"][0]["term"], "python")
        self.assertEqual(result["key_terms"][0]["count"], 3)

    def test_complexity_score(self) -> None:
        result = self.tool.execute({"text": "Simple text here.", "operation": "complexity_score"})
        self.assertIn("complexity_score", result)
        self.assertIn("level", result)

    def test_full_report(self) -> None:
        result = self.tool.execute({"text": "Hello world. Test sentence.", "operation": "full_report"})
        self.assertIn("word_count", result)
        self.assertIn("sentence_count", result)
        self.assertIn("key_terms", result)

    def test_missing_text_error(self) -> None:
        result = self.tool.execute({"operation": "word_count"})
        self.assertIn("error", result)

    def test_unknown_operation_error(self) -> None:
        result = self.tool.execute({"text": "hello", "operation": "invalid_op"})
        self.assertIn("error", result)

    def test_unique_words(self) -> None:
        result = self.tool.execute({"text": "the cat sat on the mat", "operation": "unique_words"})
        self.assertIn("cat", result["unique_words"])
        self.assertEqual(result["total_count"], 6)

    def test_paragraph_count(self) -> None:
        result = self.tool.execute({"text": "Para one.\n\nPara two.\n\nPara three.", "operation": "paragraph_count"})
        self.assertEqual(result["paragraph_count"], 3)


class DataAnalysisToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = DataAnalysisTool()

    def test_summary_stats(self) -> None:
        result = self.tool.execute({"numbers": [1, 2, 3, 4, 5], "operation": "summary_stats"})
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["mean"], 3.0)
        self.assertEqual(result["median"], 3.0)
        self.assertEqual(result["min"], 1)
        self.assertEqual(result["max"], 5)

    def test_outliers(self) -> None:
        result = self.tool.execute({"numbers": [1, 2, 3, 4, 5, 100], "operation": "outliers"})
        self.assertIn(100, result["outliers"])
        self.assertNotIn(100, result["non_outliers"])

    def test_percentiles(self) -> None:
        result = self.tool.execute({"numbers": list(range(1, 101)), "operation": "percentiles"})
        self.assertAlmostEqual(result["p50"], 50.5, places=1)

    def test_z_scores(self) -> None:
        result = self.tool.execute({"numbers": [10, 20, 30, 40, 50], "operation": "z_scores"})
        self.assertEqual(len(result["z_scores"]), 5)
        # Mean z-score should be ~0
        self.assertAlmostEqual(sum(result["z_scores"]), 0.0, places=4)

    def test_normalize(self) -> None:
        result = self.tool.execute({"numbers": [0, 50, 100], "operation": "normalize"})
        self.assertEqual(result["normalized"], [0.0, 0.5, 1.0])

    def test_distribution(self) -> None:
        result = self.tool.execute({"numbers": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "operation": "distribution"})
        self.assertIn("bins", result)
        total = sum(b["count"] for b in result["bins"])
        self.assertEqual(total, 10)

    def test_correlation(self) -> None:
        result = self.tool.execute({
            "numbers": [1, 2, 3, 4, 5],
            "numbers_b": [2, 4, 6, 8, 10],
            "operation": "correlation",
        })
        self.assertAlmostEqual(result["correlation"], 1.0, places=4)

    def test_empty_numbers_error(self) -> None:
        result = self.tool.execute({"numbers": [], "operation": "summary_stats"})
        self.assertIn("error", result)

    def test_non_numeric_error(self) -> None:
        result = self.tool.execute({"numbers": ["a", "b"], "operation": "summary_stats"})
        self.assertIn("error", result)


class JsonParserToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = JsonParserTool()

    def test_parse(self) -> None:
        result = self.tool.execute({"text": '{"key": "value"}', "operation": "parse"})
        self.assertEqual(result["parsed"], {"key": "value"})

    def test_validate_valid(self) -> None:
        result = self.tool.execute({"text": '{"a": 1}', "operation": "validate"})
        self.assertTrue(result["valid"])

    def test_validate_invalid(self) -> None:
        result = self.tool.execute({"text": "not json", "operation": "validate"})
        self.assertFalse(result["valid"])

    def test_extract_keys(self) -> None:
        result = self.tool.execute({"text": '{"name": "Alice", "age": 30}', "operation": "extract_keys"})
        self.assertIn("name", result["keys"])
        self.assertIn("age", result["keys"])

    def test_flatten(self) -> None:
        result = self.tool.execute({
            "text": '{"a": {"b": 1, "c": {"d": 2}}}',
            "operation": "flatten",
        })
        self.assertEqual(result["flattened"]["a.b"], 1)
        self.assertEqual(result["flattened"]["a.c.d"], 2)

    def test_get_path(self) -> None:
        result = self.tool.execute({
            "text": '{"users": [{"name": "Alice"}, {"name": "Bob"}]}',
            "operation": "get_path",
            "path": "users.1.name",
        })
        self.assertTrue(result["found"])
        self.assertEqual(result["value"], "Bob")

    def test_get_path_not_found(self) -> None:
        result = self.tool.execute({
            "text": '{"a": 1}',
            "operation": "get_path",
            "path": "b.c",
        })
        self.assertFalse(result["found"])

    def test_pretty_print(self) -> None:
        result = self.tool.execute({"text": '{"a":1}', "operation": "pretty_print"})
        self.assertIn("pretty", result)
        self.assertIn("\n", result["pretty"])

    def test_count_elements_array(self) -> None:
        result = self.tool.execute({"text": '[1, 2, 3]', "operation": "count_elements"})
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["type"], "array")


class RegexMatcherToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = RegexMatcherTool()

    def test_find_all(self) -> None:
        result = self.tool.execute({
            "text": "foo123bar456baz789",
            "pattern": r"\d+",
            "operation": "find_all",
        })
        self.assertEqual(result["matches"], ["123", "456", "789"])
        self.assertEqual(result["count"], 3)

    def test_find_first(self) -> None:
        result = self.tool.execute({
            "text": "hello world",
            "pattern": r"\w+",
            "operation": "find_first",
        })
        self.assertTrue(result["found"])
        self.assertEqual(result["match"], "hello")

    def test_split(self) -> None:
        result = self.tool.execute({
            "text": "a,b,,c",
            "pattern": r",",
            "operation": "split",
        })
        self.assertEqual(result["parts"], ["a", "b", "", "c"])

    def test_replace(self) -> None:
        result = self.tool.execute({
            "text": "hello world",
            "pattern": r"world",
            "replacement": "universe",
            "operation": "replace",
        })
        self.assertEqual(result["result"], "hello universe")

    def test_match_true(self) -> None:
        result = self.tool.execute({
            "text": "test123",
            "pattern": r"\d+",
            "operation": "match",
        })
        self.assertTrue(result["matches"])

    def test_match_false(self) -> None:
        result = self.tool.execute({
            "text": "hello",
            "pattern": r"\d+",
            "operation": "match",
        })
        self.assertFalse(result["matches"])

    def test_count_matches(self) -> None:
        result = self.tool.execute({
            "text": "cat bat hat mat",
            "pattern": r"\b\w+at\b",
            "operation": "count_matches",
        })
        self.assertEqual(result["count"], 4)

    def test_extract_groups(self) -> None:
        result = self.tool.execute({
            "text": "John:30, Jane:25",
            "pattern": r"(\w+):(\d+)",
            "operation": "extract_groups",
        })
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["groups"][0], ["John", "30"])
        self.assertEqual(result["groups"][1], ["Jane", "25"])

    def test_invalid_regex_error(self) -> None:
        result = self.tool.execute({
            "text": "hello",
            "pattern": r"[invalid",
            "operation": "find_all",
        })
        self.assertIn("error", result)

    def test_empty_text_error(self) -> None:
        result = self.tool.execute({
            "text": "",
            "pattern": r"\d+",
            "operation": "find_all",
        })
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
