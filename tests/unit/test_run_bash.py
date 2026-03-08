"""Unit tests for run_bash guardrails."""
import pytest

from agentic_workflows.tools.run_bash import RunBashTool


@pytest.fixture
def tool():
    return RunBashTool()


def test_run_bash_disabled_by_default(monkeypatch, tool):
    """W3-8: run_bash must be disabled unless P1_BASH_ENABLED=true."""
    monkeypatch.delenv("P1_BASH_ENABLED", raising=False)
    result = tool.execute({"command": "echo hello"})
    assert "error" in result
    assert "P1_BASH_ENABLED" in result["error"]


def test_run_bash_python_guard(monkeypatch, tool):
    monkeypatch.setenv("P1_BASH_ENABLED", "true")
    result = tool.execute({"command": "python -c 'print(1)'"})
    assert "error" in result
    assert "run_bash_guardrail" in result["error"]
    assert "python3" in result["error"]
    assert "hint" in result


def test_run_bash_python2_guard(monkeypatch, tool):
    monkeypatch.setenv("P1_BASH_ENABLED", "true")
    result = tool.execute({"command": "python2 -c 'print(1)'"})
    assert "error" in result
    assert "run_bash_guardrail" in result["error"]


def test_run_bash_python3_passes(monkeypatch, tool):
    monkeypatch.setenv("P1_BASH_ENABLED", "true")
    result = tool.execute({"command": "python3 -c 'print(42)'"})
    # Should not be blocked by the guardrail (may fail if python3 unavailable, but no guardrail key)
    assert "run_bash_guardrail" not in result.get("error", "")


def test_run_bash_python_in_path_not_blocked(monkeypatch, tool):
    """'python3' in a path argument should not be blocked."""
    monkeypatch.setenv("P1_BASH_ENABLED", "true")
    result = tool.execute({"command": "echo /usr/bin/python"})
    assert "run_bash_guardrail" not in result.get("error", "")


def test_run_bash_empty_command(monkeypatch, tool):
    monkeypatch.setenv("P1_BASH_ENABLED", "true")
    result = tool.execute({"command": ""})
    assert result == {"error": "command is required"}
