import os
import sqlite3
from typing import Any

from agentic_workflows.tools.base import Tool

_DEFAULT_DB_PATH = ".tmp/qa_store.db"
_VALID_OPS = {"insert", "query", "list", "delete", "count"}


class QueryDBTool(Tool):
    name = "query_db"
    description = (
        "Q&A store backed by SQLite. "
        "Operations: insert, query (LIKE search), list, delete, count."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        operation: str = args.get("operation", "")
        question: str = args.get("question", "")
        answer: str = args.get("answer", "")
        question_id = args.get("question_id")
        db_path: str = args.get("db_path", _DEFAULT_DB_PATH)

        if operation not in _VALID_OPS:
            return {"error": f"operation must be one of {sorted(_VALID_OPS)}"}

        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            _ensure_table(conn)

            if operation == "insert":
                return _insert(conn, question, answer)
            if operation == "query":
                return _query(conn, question)
            if operation == "list":
                return _list(conn)
            if operation == "delete":
                return _delete(conn, question_id)
            # count
            return _count(conn)
        except sqlite3.Error as exc:
            return {"error": f"Database error: {str(exc)}"}
        finally:
            if conn is not None:
                conn.close()


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS qa_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def _insert(conn: sqlite3.Connection, question: str, answer: str) -> dict[str, Any]:
    if not question:
        return {"error": "question is required for insert"}
    if not answer:
        return {"error": "answer is required for insert"}
    cur = conn.execute(
        "INSERT INTO qa_entries (question, answer) VALUES (?, ?)", (question, answer)
    )
    conn.commit()
    return {"inserted": True, "id": cur.lastrowid, "question": question}


def _query(conn: sqlite3.Connection, question: str) -> dict[str, Any]:
    if not question:
        return {"error": "question is required for query"}
    cur = conn.execute(
        "SELECT id, question, answer, created_at FROM qa_entries WHERE LOWER(question) LIKE ?",
        (f"%{question.lower()}%",),
    )
    rows = [dict(r) for r in cur.fetchall()]
    return {"results": rows, "count": len(rows), "query_term": question}


def _list(conn: sqlite3.Connection) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT id, question, answer, created_at FROM qa_entries ORDER BY id"
    )
    rows = [dict(r) for r in cur.fetchall()]
    return {"rows": rows, "count": len(rows)}


def _delete(conn: sqlite3.Connection, question_id: Any) -> dict[str, Any]:
    if question_id is None:
        return {"error": "question_id is required for delete"}
    cur = conn.execute("DELETE FROM qa_entries WHERE id = ?", (int(question_id),))
    conn.commit()
    return {"deleted": cur.rowcount, "id": int(question_id)}


def _count(conn: sqlite3.Connection) -> dict[str, Any]:
    cur = conn.execute("SELECT COUNT(*) FROM qa_entries")
    return {"count": cur.fetchone()[0]}
