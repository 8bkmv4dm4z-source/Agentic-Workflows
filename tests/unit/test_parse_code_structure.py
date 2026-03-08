from __future__ import annotations

import pytest

from agentic_workflows.tools.parse_code_structure import OutlineCodeTool


@pytest.fixture()
def tool():
    return OutlineCodeTool()


class TestPythonAST:
    def test_extracts_functions_classes_imports(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "sample.py"
        src.write_text(
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "class Foo(Bar):\n"
            "    pass\n"
            "\n"
            "def hello(x, y):\n"
            "    return x + y\n"
        )
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src)})

        assert result["language"] == "python"
        assert result["line_count"] == 8

        assert len(result["functions"]) == 1
        fn = result["functions"][0]
        assert fn["name"] == "hello"
        assert fn["line"] == 7
        assert fn["args"] == ["x", "y"]

        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["name"] == "Foo"
        assert "Bar" in cls["bases"]

        assert len(result["imports"]) == 2

    def test_async_function(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "async_sample.py"
        src.write_text("async def fetch(url):\n    pass\n")
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src)})
        assert result["functions"][0]["name"] == "fetch"
        assert result["functions"][0]["args"] == ["url"]

    def test_decorators(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "deco.py"
        src.write_text("@staticmethod\ndef greet():\n    pass\n")
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src)})
        assert result["functions"][0]["decorators"] == ["staticmethod"]


class TestRegexFallback:
    def test_js_file_regex(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "app.js"
        src.write_text(
            "function foo() {\n"
            "  return 1;\n"
            "}\n"
            "class Bar {\n"
            "}\n"
        )
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src)})

        assert result["language"] == "other"
        assert any(f["name"] == "foo" for f in result["functions"])
        assert any(c["name"] == "Bar" for c in result["classes"])

    def test_python_syntax_error_falls_back(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "bad.py"
        src.write_text("def foo(:\n    pass\n")
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src)})
        # Should not error out; falls back to regex
        assert "error" not in result
        assert result["language"] == "python"


class TestSizeGuard:
    def test_truncated_flag(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "big.py"
        src.write_text("x = 1\n" * 200_000)  # > 500KB
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src)})
        assert result.get("truncated") is True


class TestErrorCases:
    def test_file_not_found(self, tool, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": "nonexistent.py"})
        assert "error" in result

    def test_path_traversal_absolute(self, tool, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": "/etc/passwd"})
        assert "error" in result

    def test_path_traversal_relative(self, tool, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": "../../../etc/passwd"})
        assert "error" in result

    def test_empty_path(self, tool):
        result = tool.execute({"path": ""})
        assert result == {"error": "path is required"}

    def test_directory_not_file(self, tool, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = tool.execute({"path": str(subdir)})
        assert "error" in result


class TestOperationsFilter:
    def test_only_functions(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "filtered.py"
        src.write_text(
            "import os\n"
            "class Foo:\n"
            "    pass\n"
            "def bar():\n"
            "    pass\n"
        )
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src), "operations": ["functions"]})
        assert "functions" in result
        assert "classes" not in result
        assert "imports" not in result

    def test_operations_as_string(self, tool, tmp_path, monkeypatch):
        src = tmp_path / "single_op.py"
        src.write_text("class A:\n    pass\n")
        monkeypatch.chdir(tmp_path)
        result = tool.execute({"path": str(src), "operations": "classes"})
        assert "classes" in result
        assert len(result["classes"]) == 1
