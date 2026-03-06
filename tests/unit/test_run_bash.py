"""Unit tests for run_bash guardrails."""
import pytest

from agentic_workflows.tools.run_bash import RunBashTool


@pytest.fixture
def tool():
    return RunBashTool()


def test_run_bash_python_guard(tool):
    result = tool.execute({"command": "python -c 'print(1)'"})
    assert "error" in result
    assert "run_bash_guardrail" in result["error"]
    assert "python3" in result["error"]
    assert "hint" in result


def test_run_bash_python2_guard(tool):
    result = tool.execute({"command": "python2 -c 'print(1)'"})
    assert "error" in result
    assert "run_bash_guardrail" in result["error"]


def test_run_bash_python3_passes(tool):
    result = tool.execute({"command": "python3 -c 'print(42)'"})
    # Should not be blocked by the guardrail (may fail if python3 unavailable, but no guardrail key)
    assert "run_bash_guardrail" not in result.get("error", "")


def test_run_bash_python_in_path_not_blocked(tool):
    """'python3' in a path argument should not be blocked."""
    result = tool.execute({"command": "echo /usr/bin/python"})
    assert "run_bash_guardrail" not in result.get("error", "")


def test_run_bash_empty_command(tool):
    result = tool.execute({"command": ""})
    assert result == {"error": "command is required"}
