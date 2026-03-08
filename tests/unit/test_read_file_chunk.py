from __future__ import annotations

import pytest

from agentic_workflows.tools.read_file_chunk import ReadFileChunkTool


@pytest.fixture()
def tool():
    return ReadFileChunkTool()


@pytest.fixture()
def sample_file(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("\n".join(f"line {i}" for i in range(1, 51)) + "\n")
    return p


def test_first_chunk(tool, sample_file, monkeypatch):
    monkeypatch.setenv("AGENT_ROOT", str(sample_file.parent))
    monkeypatch.setenv("AGENT_WORKDIR", str(sample_file.parent))
    result = tool.execute({"path": str(sample_file), "offset": 0, "limit": 10})
    assert result["lines_returned"] == 10
    assert result["total_lines"] == 50
    assert result["has_more"] is True
    assert result["next_offset"] == 10
    assert "line 1" in result["content"]
    assert "line 10" in result["content"]
    assert "line 11" not in result["content"]


def test_last_chunk(tool, sample_file, monkeypatch):
    monkeypatch.setenv("AGENT_ROOT", str(sample_file.parent))
    monkeypatch.setenv("AGENT_WORKDIR", str(sample_file.parent))
    result = tool.execute({"path": str(sample_file), "offset": 45, "limit": 10})
    assert result["lines_returned"] == 5
    assert result["has_more"] is False
    assert result["next_offset"] is None


def test_default_limit(tool, sample_file, monkeypatch):
    monkeypatch.setenv("AGENT_ROOT", str(sample_file.parent))
    monkeypatch.setenv("AGENT_WORKDIR", str(sample_file.parent))
    result = tool.execute({"path": str(sample_file)})
    # default limit=150, file has 50 lines — should return all
    assert result["lines_returned"] == 50
    assert result["has_more"] is False


def test_missing_path(tool):
    result = tool.execute({})
    assert "error" in result


def test_file_not_found(tool, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ROOT", str(tmp_path))
    monkeypatch.setenv("AGENT_WORKDIR", str(tmp_path))
    result = tool.execute({"path": str(tmp_path / "nope.txt")})
    assert "error" in result
