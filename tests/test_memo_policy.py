import unittest

from execution.langgraph.policy import MemoizationPolicy


class MemoPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = MemoizationPolicy(max_policy_retries=2)

    def test_requires_memoization_for_fibonacci_write(self) -> None:
        args = {"path": "fib.txt", "content": ",".join(str(i) for i in range(120))}
        result = {"result": "Successfully wrote 800 characters to fib.txt"}
        self.assertTrue(
            self.policy.requires_memoization(
                tool_name="write_file",
                args=args,
                result=result,
            )
        )

    def test_does_not_require_for_small_write(self) -> None:
        args = {"path": "note.txt", "content": "ok"}
        result = {"result": "Successfully wrote 2 characters to note.txt"}
        self.assertFalse(
            self.policy.requires_memoization(
                tool_name="write_file",
                args=args,
                result=result,
            )
        )

    def test_suggested_key_uses_write_path(self) -> None:
        key = self.policy.suggested_memo_key(
            tool_name="write_file",
            args={"path": "fib.txt"},
            result={"result": "done"},
        )
        self.assertEqual(key, "write_file:fib.txt")


if __name__ == "__main__":
    unittest.main()
