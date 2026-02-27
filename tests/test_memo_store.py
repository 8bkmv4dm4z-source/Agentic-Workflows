import tempfile
import unittest

from execution.langgraph.memo_store import SQLiteMemoStore


class MemoStoreTests(unittest.TestCase):
    def test_put_and_get_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/memo.db"
            store = SQLiteMemoStore(db_path)
            result = store.put(
                run_id="run-1",
                key="write_file:fib.txt",
                value={"n": 100, "status": "ok"},
                namespace="run",
                source_tool="write_file",
                step=3,
            )
            self.assertTrue(result.inserted)
            lookup = store.get(run_id="run-1", key="write_file:fib.txt", namespace="run")
            self.assertTrue(lookup.found)
            self.assertEqual(lookup.value["n"], 100)
            self.assertEqual(result.value_hash, lookup.value_hash)

    def test_run_scoped_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f"{temp_dir}/memo.db"
            store = SQLiteMemoStore(db_path)
            store.put(run_id="run-a", key="k", value={"v": 1})
            lookup = store.get(run_id="run-b", key="k")
            self.assertFalse(lookup.found)


if __name__ == "__main__":
    unittest.main()
