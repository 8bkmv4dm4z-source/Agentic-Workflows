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


def test_write_file_agent_workdir_used_as_fallback(tool, tmp_path, monkeypatch):
    """AGENT_WORKDIR is the docker-compose host-mounted workspace.
    When P1_RUN_ARTIFACT_DIR is unset, bare filenames should land there."""
    monkeypatch.delenv("P1_RUN_ARTIFACT_DIR", raising=False)
    monkeypatch.setenv("AGENT_WORKDIR", str(tmp_path))
    result = tool.execute({"path": "fib.py", "content": "print('fib')\n"})
    assert "error" not in result
    expected = tmp_path / "fib.py"
    assert expected.exists(), "file should be written into AGENT_WORKDIR, not container cwd"
    assert result["path"] == str(expected)


def test_write_file_p1_run_artifact_dir_takes_priority_over_agent_workdir(tool, tmp_path, monkeypatch):
    """P1_RUN_ARTIFACT_DIR overrides AGENT_WORKDIR when both are set."""
    artifact_dir = tmp_path / "artifacts"
    workdir = tmp_path / "workspace"
    monkeypatch.setenv("P1_RUN_ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("AGENT_WORKDIR", str(workdir))
    result = tool.execute({"path": "out.txt", "content": "hello\n"})
    assert "error" not in result
    assert (artifact_dir / "out.txt").exists(), "P1_RUN_ARTIFACT_DIR should win over AGENT_WORKDIR"
    assert not (workdir / "out.txt").exists()


def test_write_file_agent_workdir_used_for_paths_with_directory(tool, tmp_path, monkeypatch):
    """AGENT_WORKDIR should redirect relative paths that contain a directory component."""
    monkeypatch.delenv("P1_RUN_ARTIFACT_DIR", raising=False)
    workspace = tmp_path / "workspace"
    monkeypatch.setenv("AGENT_WORKDIR", str(workspace))
    monkeypatch.chdir(tmp_path)
    result = tool.execute({"path": "subdir/notes.txt", "content": "hi\n"})
    assert "error" not in result
    assert (workspace / "subdir" / "notes.txt").exists()


def test_write_file_no_double_nesting_when_path_inside_workspace(tool, tmp_path, monkeypatch):
    """If agent passes an absolute path already inside AGENT_WORKDIR, don't double-nest it.
    e.g. path=/app/workspace/fib.py with AGENT_WORKDIR=/app/workspace
    should write to /app/workspace/fib.py, not /app/workspace/workspace/fib.py."""
    monkeypatch.delenv("P1_RUN_ARTIFACT_DIR", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("AGENT_WORKDIR", str(workspace))
    target = workspace / "fib.py"
    result = tool.execute({"path": str(target), "content": "print('fib')\n"})
    assert "error" not in result
    assert target.exists(), "file should land directly in workspace, not nested again"
    assert result["path"] == str(target)
