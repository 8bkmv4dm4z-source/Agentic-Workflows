"""Tests for query_sql tool."""

import contextlib
import os
import sqlite3
import unittest
from pathlib import Path

from agentic_workflows.tools.query_sql import QuerySqlTool


class TestQuerySqlTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = QuerySqlTool()
        # Create DB inside CWD so validate_path_within_cwd passes
        self.db_path = str(Path(os.getcwd()) / "_test_query_sql.db")
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, total REAL)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice', 'alice@example.com')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob', 'bob@example.com')")
        conn.execute("INSERT INTO users VALUES (3, 'Charlie', 'charlie@example.com')")
        conn.execute("INSERT INTO orders VALUES (1, 1, 99.99)")
        conn.execute("INSERT INTO orders VALUES (2, 2, 49.50)")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(self.db_path)

    def _uri(self) -> str:
        # sqlite:// + empty host + absolute path -> sqlite:// + / + /abs/path
        return f"sqlite:////{self.db_path}"

    def test_list_tables(self) -> None:
        result = self.tool.execute({"operation": "list_tables", "db_uri": self._uri()})
        self.assertNotIn("error", result)
        self.assertEqual(result["db_type"], "sqlite")
        self.assertIn("users", result["tables"])
        self.assertIn("orders", result["tables"])
        self.assertEqual(result["count"], 2)

    def test_get_schema(self) -> None:
        result = self.tool.execute({"operation": "get_schema", "db_uri": self._uri(), "table": "users"})
        self.assertNotIn("error", result)
        self.assertEqual(result["table"], "users")
        col_names = [c["name"] for c in result["columns"]]
        self.assertIn("id", col_names)
        self.assertIn("name", col_names)
        self.assertIn("email", col_names)
        pk_col = next(c for c in result["columns"] if c["name"] == "id")
        self.assertTrue(pk_col["is_pk"])
        self.assertEqual(result["row_count"], 3)

    def test_run_query(self) -> None:
        result = self.tool.execute({
            "operation": "run_query",
            "db_uri": self._uri(),
            "sql": "SELECT id, name FROM users ORDER BY id",
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["count"], 3)
        self.assertEqual(result["columns"], ["id", "name"])
        self.assertEqual(result["rows"][0]["name"], "Alice")
        self.assertFalse(result["truncated"])

    def test_count_rows(self) -> None:
        result = self.tool.execute({"operation": "count_rows", "db_uri": self._uri(), "table": "users"})
        self.assertNotIn("error", result)
        self.assertEqual(result["table"], "users")
        self.assertEqual(result["count"], 3)

    def test_read_only_blocks_dml(self) -> None:
        for stmt in [
            "DELETE FROM users WHERE id = 1",
            "INSERT INTO users VALUES (4, 'Dan', 'dan@x.com')",
            "UPDATE users SET name = 'X' WHERE id = 1",
            "DROP TABLE users",
        ]:
            result = self.tool.execute({"operation": "run_query", "db_uri": self._uri(), "sql": stmt})
            self.assertIn("error", result, f"Expected block for: {stmt}")
            self.assertIn("blocked", result["error"])

    def test_allow_writes_enables_dml(self) -> None:
        result = self.tool.execute({
            "operation": "run_query",
            "db_uri": self._uri(),
            "sql": "INSERT INTO users VALUES (4, 'Dan', 'dan@x.com')",
            "allow_writes": True,
        })
        self.assertNotIn("error", result)
        count = self.tool.execute({"operation": "count_rows", "db_uri": self._uri(), "table": "users"})
        self.assertEqual(count["count"], 4)

    def test_row_limit(self) -> None:
        result = self.tool.execute({
            "operation": "run_query",
            "db_uri": self._uri(),
            "sql": "SELECT * FROM users",
            "max_rows": 1,
        })
        self.assertNotIn("error", result)
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["truncated"])

    def test_missing_db_uri_error(self) -> None:
        result = self.tool.execute({"operation": "list_tables"})
        self.assertIn("error", result)
        self.assertIn("db_uri or path is required", result["error"])

    def test_invalid_sql_error(self) -> None:
        result = self.tool.execute({
            "operation": "run_query",
            "db_uri": self._uri(),
            "sql": "SELCT * FORM users",
        })
        self.assertIn("error", result)

    def test_postgres_uri_without_driver(self) -> None:
        result = self.tool.execute({
            "operation": "list_tables",
            "db_uri": "postgresql://user:pass@localhost/mydb",
        })
        self.assertIn("error", result)
        self.assertIn("psycopg2", result["error"])

    def test_path_arg_sqlite_shorthand(self) -> None:
        result = self.tool.execute({"operation": "list_tables", "path": self.db_path})
        self.assertNotIn("error", result)
        self.assertIn("users", result["tables"])

    def test_get_schema_missing_table(self) -> None:
        result = self.tool.execute({"operation": "get_schema", "db_uri": self._uri()})
        self.assertIn("error", result)

    def test_missing_operation(self) -> None:
        result = self.tool.execute({"db_uri": self._uri()})
        self.assertIn("error", result)

    def test_unknown_operation(self) -> None:
        result = self.tool.execute({"operation": "drop_all", "db_uri": self._uri()})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
