from __future__ import annotations

import sqlite3

import pytest

from agentic_workflows.tools.describe_db_schema import DescribeDbSchemaTool


@pytest.fixture()
def tool():
    return DescribeDbSchemaTool()


class TestSQLite:
    def test_inspects_sqlite_db(self, tool, tmp_path, monkeypatch):
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users VALUES (1, 'Alice')")
        conn.execute("INSERT INTO users VALUES (2, 'Bob')")
        conn.commit()
        conn.close()

        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(db_path)})

        assert result["type"] == "sqlite"
        assert "users" in result["tables"]
        assert result["row_counts"]["users"] == 2

        cols = result["columns"]["users"]
        col_names = [c["name"] for c in cols]
        assert "id" in col_names
        assert "name" in col_names
        # id should be primary key
        id_col = next(c for c in cols if c["name"] == "id")
        assert id_col["pk"] is True

    def test_multiple_tables(self, tool, tmp_path, monkeypatch):
        db_path = tmp_path / "multi.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t1 (a TEXT)")
        conn.execute("CREATE TABLE t2 (b INTEGER)")
        conn.commit()
        conn.close()

        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(db_path)})
        assert len(result["tables"]) == 2


class TestCSV:
    def test_inspects_csv(self, tool, tmp_path, monkeypatch):
        csv_path = tmp_path / "data.csv"
        csv_path.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,SF\nDave,28,CHI\n")

        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(csv_path)})

        assert result["type"] == "csv"
        assert result["columns"] == ["name", "age", "city"]
        assert result["row_count"] == 4
        assert len(result["sample"]) == 3  # first 3 data rows

    def test_empty_csv(self, tool, tmp_path, monkeypatch):
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("")

        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(csv_path)})
        assert "error" in result


class TestErrorCases:
    def test_path_traversal(self, tool, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": "/etc/passwd"})
        assert "error" in result

    def test_unsupported_extension(self, tool, tmp_path, monkeypatch):
        json_file = tmp_path / "data.json"
        json_file.write_text("{}")
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(json_file)})
        assert "error" in result
        assert "unsupported" in result["error"]

    def test_file_not_found(self, tool, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": "nonexistent.db"})
        assert "error" in result

    def test_empty_path(self, tool):
        result = tool.execute({"path": ""})
        assert result == {"error": "path is required"}
