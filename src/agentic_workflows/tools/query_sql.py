from __future__ import annotations

"""General-purpose SQL query tool supporting SQLite (now) and Postgres (Phase 7).

Operations: list_tables, get_schema, run_query, count_rows.
Read-only by default; DML/DDL blocked unless allow_writes=True.
"""

import sqlite3
from typing import Any
from urllib.parse import urlparse

from ._security import validate_path_within_cwd
from .base import Tool

_WRITE_KEYWORDS = frozenset({
    "DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "CREATE", "TRUNCATE",
})

_MAX_TIMEOUT = 30
_DEFAULT_TIMEOUT = 5
_DEFAULT_MAX_ROWS = 1000


class QuerySqlTool(Tool):
    name = "query_sql"
    _args_schema = {
        "operation": {"type": "string", "required": "true"},
        "db_uri": {"type": "string"},
        "path": {"type": "string"},
        "table": {"type": "string"},
        "sql": {"type": "string"},
        "max_rows": {"type": "number"},
        "allow_writes": {"type": "boolean"},
        "timeout": {"type": "number"},
    }
    description = (
        "Execute SQL queries against SQLite or Postgres databases. "
        "Required args: operation ('list_tables'|'get_schema'|'run_query'|'count_rows'). "
        "Optional: db_uri (str), path (str, SQLite shorthand), table (str), "
        "sql (str, for run_query), max_rows (int, default 1000), "
        "allow_writes (bool, default false), timeout (int, default 5, max 30)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        operation = str(args.get("operation", "")).strip()
        if not operation:
            return {"error": "operation is required (list_tables|get_schema|run_query|count_rows)"}

        if operation not in ("list_tables", "get_schema", "run_query", "count_rows"):
            return {"error": f"unknown operation: {operation}. Use list_tables|get_schema|run_query|count_rows"}

        db_uri = str(args.get("db_uri", "")).strip()
        path_str = str(args.get("path", "")).strip()

        if not db_uri and not path_str:
            return {"error": "db_uri or path is required"}

        if db_uri:
            parsed = urlparse(db_uri)
            scheme = parsed.scheme.lower()
            if scheme in ("postgresql", "postgres"):
                return self._handle_postgres(args, operation, db_uri)
            elif scheme == "sqlite":
                # sqlite:///path -> parsed.path="/path"
                # Convention: sqlite:/// + relative  OR  sqlite://// + absolute
                raw_path = parsed.path
                if not raw_path or raw_path == "/":
                    return {"error": "sqlite URI must include a path, e.g. sqlite:///mydb.db"}
                # Strip single leading slash; both absolute and relative use [1:]
                db_path = raw_path[1:]
            else:
                return {"error": f"unsupported db_uri scheme: {scheme}. Use sqlite:/// or postgresql://"}
        else:
            db_path = path_str

        target, err = validate_path_within_cwd(db_path)
        if err:
            return err

        timeout = min(int(args.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
        if timeout <= 0:
            timeout = _DEFAULT_TIMEOUT

        try:
            conn = sqlite3.connect(str(target), timeout=timeout)
            conn.execute(f"PRAGMA busy_timeout = {timeout * 1000}")
            try:
                return self._dispatch_sqlite(conn, args, operation)
            finally:
                conn.close()
        except sqlite3.Error as exc:
            return {"error": f"sqlite error: {exc}"}

    def _dispatch_sqlite(
        self, conn: sqlite3.Connection, args: dict[str, Any], operation: str,
    ) -> dict[str, Any]:
        if operation == "list_tables":
            return self._sqlite_list_tables(conn)
        elif operation == "get_schema":
            return self._sqlite_get_schema(conn, args)
        elif operation == "run_query":
            return self._sqlite_run_query(conn, args)
        elif operation == "count_rows":
            return self._sqlite_count_rows(conn, args)
        return {"error": f"unknown operation: {operation}"}

    @staticmethod
    def _sqlite_list_tables(conn: sqlite3.Connection) -> dict[str, Any]:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        return {"tables": tables, "count": len(tables), "db_type": "sqlite"}

    @staticmethod
    def _sqlite_get_schema(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
        table = str(args.get("table", "")).strip()
        if not table:
            return {"error": "table is required for get_schema"}

        cursor = conn.execute(f"PRAGMA table_info([{table}])")  # noqa: S608
        rows = cursor.fetchall()
        if not rows:
            return {"error": f"table not found: {table}"}

        columns = []
        for row in rows:
            columns.append({
                "name": row[1],
                "type": row[2],
                "is_pk": bool(row[5]),
            })

        count_cursor = conn.execute(f"SELECT COUNT(*) FROM [{table}]")  # noqa: S608
        row_count = count_cursor.fetchone()[0]

        return {"table": table, "columns": columns, "row_count": row_count}

    def _sqlite_run_query(self, conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
        sql = str(args.get("sql", "")).strip()
        if not sql:
            return {"error": "sql is required for run_query"}

        allow_writes = bool(args.get("allow_writes", False))
        max_rows = min(int(args.get("max_rows", _DEFAULT_MAX_ROWS)), _DEFAULT_MAX_ROWS)

        write_err = self._check_write_safety(sql, allow_writes)
        if write_err:
            return write_err

        try:
            cursor = conn.execute(sql)
            if cursor.description is None:
                conn.commit()
                return {"rows": [], "count": 0, "columns": [], "truncated": False}

            col_names = [desc[0] for desc in cursor.description]
            all_rows = cursor.fetchmany(max_rows + 1)
            truncated = len(all_rows) > max_rows
            result_rows = all_rows[:max_rows]

            rows_as_dicts = [dict(zip(col_names, row, strict=False)) for row in result_rows]
            return {
                "rows": rows_as_dicts,
                "count": len(rows_as_dicts),
                "columns": col_names,
                "truncated": truncated,
            }
        except sqlite3.Error as exc:
            return {"error": f"query error: {exc}"}

    @staticmethod
    def _sqlite_count_rows(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
        table = str(args.get("table", "")).strip()
        if not table:
            return {"error": "table is required for count_rows"}

        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM [{table}]")  # noqa: S608
            count = cursor.fetchone()[0]
            return {"table": table, "count": count}
        except sqlite3.Error as exc:
            return {"error": f"count error: {exc}"}

    @staticmethod
    def _check_write_safety(sql: str, allow_writes: bool) -> dict[str, Any] | None:
        if allow_writes:
            return None
        upper = sql.upper().strip()
        for kw in _WRITE_KEYWORDS:
            if upper.startswith(kw) or f" {kw} " in f" {upper} ":
                return {"error": f"write operation blocked: {kw} not allowed without allow_writes=True"}
        return None

    @staticmethod
    def _handle_postgres(
        args: dict[str, Any], operation: str, db_uri: str,
    ) -> dict[str, Any]:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            return {
                "error": (
                    "psycopg2 not installed — install for Postgres support: "
                    "pip install psycopg2-binary"
                )
            }
        return {"error": "Postgres operations not yet implemented (planned for Phase 7)"}
