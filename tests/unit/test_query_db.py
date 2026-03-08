"""Tests for QueryDBTool — in-memory SQLite via tmp_path."""
from __future__ import annotations

from agentic_workflows.tools.query_db import QueryDBTool

tool = QueryDBTool()


def execute(op, tmp_path, **kwargs):
    db = str(tmp_path / "test.db")
    return tool.execute({"operation": op, "db_path": db, **kwargs})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_invalid_operation(tmp_path):
    r = execute("explode", tmp_path)
    assert "error" in r


# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------

def test_insert_basic(tmp_path):
    r = execute("insert", tmp_path, question="What is 2+2?", answer="4")
    assert r["inserted"] is True
    assert "id" in r


def test_insert_missing_question(tmp_path):
    r = execute("insert", tmp_path, answer="4")
    assert "error" in r


def test_insert_missing_answer(tmp_path):
    r = execute("insert", tmp_path, question="What?")
    assert "error" in r


def test_insert_returns_id(tmp_path):
    r = execute("insert", tmp_path, question="Q1", answer="A1")
    assert isinstance(r["id"], int)
    assert r["id"] >= 1


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

def test_query_finds_inserted(tmp_path):
    execute("insert", tmp_path, question="Python version", answer="3.12")
    r = execute("query", tmp_path, question="Python")
    assert r["count"] >= 1
    assert any("Python" in row["question"] for row in r["results"])


def test_query_case_insensitive(tmp_path):
    execute("insert", tmp_path, question="What is Python?", answer="A language")
    r = execute("query", tmp_path, question="python")
    assert r["count"] >= 1


def test_query_no_match(tmp_path):
    execute("insert", tmp_path, question="What is 2+2?", answer="4")
    r = execute("query", tmp_path, question="zzzznotfound")
    assert r["count"] == 0


def test_query_missing_question(tmp_path):
    r = execute("query", tmp_path)
    assert "error" in r


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_empty(tmp_path):
    r = execute("list", tmp_path)
    assert r["count"] == 0
    assert r["rows"] == []


def test_list_after_inserts(tmp_path):
    execute("insert", tmp_path, question="Q1", answer="A1")
    execute("insert", tmp_path, question="Q2", answer="A2")
    r = execute("list", tmp_path)
    assert r["count"] == 2


# ---------------------------------------------------------------------------
# count
# ---------------------------------------------------------------------------

def test_count_empty(tmp_path):
    r = execute("count", tmp_path)
    assert r["count"] == 0


def test_count_after_inserts(tmp_path):
    execute("insert", tmp_path, question="Q1", answer="A1")
    execute("insert", tmp_path, question="Q2", answer="A2")
    r = execute("count", tmp_path)
    assert r["count"] == 2


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def test_delete_existing(tmp_path):
    ins = execute("insert", tmp_path, question="To delete", answer="yes")
    qid = ins["id"]
    r = execute("delete", tmp_path, question_id=qid)
    assert r["deleted"] == 1
    assert r["id"] == qid


def test_delete_nonexistent(tmp_path):
    r = execute("delete", tmp_path, question_id=9999)
    assert r["deleted"] == 0


def test_delete_missing_id(tmp_path):
    r = execute("delete", tmp_path)
    assert "error" in r


def test_delete_reduces_count(tmp_path):
    ins = execute("insert", tmp_path, question="Q", answer="A")
    execute("delete", tmp_path, question_id=ins["id"])
    r = execute("count", tmp_path)
    assert r["count"] == 0
