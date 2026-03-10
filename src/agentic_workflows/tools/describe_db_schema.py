from __future__ import annotations

"""Tool for introspecting SQLite databases and CSV files to return schema metadata."""

import csv
import sqlite3
from pathlib import Path
from typing import Any

from .base import Tool


class DescribeDbSchemaTool(Tool):
    name = "describe_db_schema"
    _args_schema = {
        "path": {"type": "string", "required": "true"},
        "operation": {"type": "string"},
    }
    description = (
        "Introspect a SQLite .db file or CSV file to return schema metadata. "
        "Required args: path (str). "
        "Optional: operation (str, default 'columns')."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        path_str = str(args.get("path", "")).strip()
        operation = str(args.get("operation", "columns")).strip()

        if not path_str:
            return {"error": "path is required"}

        # Path traversal protection
        cwd = Path.cwd().resolve()
        try:
            target = Path(path_str).resolve()
        except Exception:
            return {"error": f"invalid path: {path_str}"}
        try:
            target.relative_to(cwd)
        except ValueError:
            return {"error": f"path outside working directory: {path_str}"}

        if not target.exists():
            return {"error": f"file not found: {path_str}"}

        suffix = target.suffix.lower()
        if suffix in (".db", ".sqlite", ".sqlite3"):
            return _inspect_sqlite(target, operation)
        elif suffix == ".csv":
            return _inspect_csv(target, operation)
        else:
            return {"error": f"unsupported file type: {suffix}. Use .db, .sqlite, .sqlite3, or .csv"}


def _inspect_sqlite(path: Path, operation: str) -> dict[str, Any]:
    """Introspect a SQLite database file."""
    try:
        conn = sqlite3.connect(str(path))
        cursor = conn.cursor()

        # Get table names
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        columns: dict[str, list[dict[str, Any]]] = {}
        row_counts: dict[str, int] = {}

        for table in tables:
            # Get column info
            cursor.execute(f"PRAGMA table_info([{table}])")  # noqa: S608
            cols = []
            for col_row in cursor.fetchall():
                cols.append({
                    "name": col_row[1],
                    "type": col_row[2],
                    "pk": bool(col_row[5]),
                })
            columns[table] = cols

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM [{table}]")  # noqa: S608
            row_counts[table] = cursor.fetchone()[0]

        conn.close()

        return {
            "type": "sqlite",
            "tables": tables,
            "columns": columns,
            "row_counts": row_counts,
        }
    except Exception as e:
        return {"error": f"sqlite error: {e}"}


def _inspect_csv(path: Path, operation: str) -> dict[str, Any]:
    """Introspect a CSV file."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
            except StopIteration:
                return {"error": "empty CSV file"}

            sample: list[list[str]] = []
            row_count = 0
            for row in reader:
                row_count += 1
                if len(sample) < 3:
                    sample.append(row)

        return {
            "type": "csv",
            "columns": headers,
            "row_count": row_count,
            "sample": sample,
        }
    except Exception as e:
        return {"error": f"csv error: {e}"}
