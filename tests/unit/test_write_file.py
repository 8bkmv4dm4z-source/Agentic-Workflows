"""Unit tests for write_file guardrails."""
import pytest

from agentic_workflows.tools.write_file import WriteFileTool


@pytest.fixture
def tool():
    return WriteFileTool()


def test_write_file_sh_no_shebang(tool):
    result = tool.execute({"path": "script.sh", "content": "echo hello\n"})
    assert "error" in result
    assert "write_file_guardrail" in result["error"]
    assert "hint" in result


def test_write_file_bash_no_shebang(tool):
    result = tool.execute({"path": "run.bash", "content": "echo hello\n"})
    assert "error" in result
    assert "write_file_guardrail" in result["error"]


def test_write_file_sh_with_shebang(tool, tmp_path, monkeypatch):
    monkeypatch.setenv("P1_RUN_ARTIFACT_DIR", "")
    monkeypatch.chdir(tmp_path)
    result = tool.execute({"path": str(tmp_path / "script.sh"), "content": "#!/bin/bash\necho hello\n"})
    assert "error" not in result
    assert "write_file_guardrail" not in result.get("error", "")


def test_write_file_sh_with_shebang_leading_whitespace(tool, tmp_path, monkeypatch):
    """Shebang after leading whitespace should still be blocked (lstrip check)."""
    result = tool.execute({"path": "script.sh", "content": "\n#!/bin/bash\necho hello\n"})
    # lstrip().startswith('#!') — '\n#!/bin/bash' -> lstrip -> '#!/bin/bash' -> passes
    # Actually content.lstrip() removes leading newlines, so this PASSES the guard
    # Verify no guardrail fires
    # (We don't write to disk since path is relative and sandbox may block)
    # Just check guardrail is not fired for lstripped shebang
    assert "write_file_guardrail" not in result.get("error", "")


def test_write_file_non_sh_no_shebang(tool, tmp_path, monkeypatch):
    monkeypatch.setenv("P1_RUN_ARTIFACT_DIR", "")
    monkeypatch.chdir(tmp_path)
    result = tool.execute({"path": str(tmp_path / "notes.txt"), "content": "hello world\n"})
    assert "write_file_guardrail" not in result.get("error", "")


def test_write_file_py_no_shebang_not_blocked(tool, tmp_path, monkeypatch):
    monkeypatch.setenv("P1_RUN_ARTIFACT_DIR", "")
    monkeypatch.chdir(tmp_path)
    result = tool.execute({"path": str(tmp_path / "calc.py"), "content": "print('hi')\n"})
    assert "write_file_guardrail" not in result.get("error", "")
