"""Tests for UpdateFileSectionTool."""
from __future__ import annotations

from agentic_workflows.tools.update_file_section import UpdateFileSectionTool

tool = UpdateFileSectionTool()


def execute(**kwargs):
    return tool.execute(kwargs)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_missing_path():
    r = execute(section_marker="## Section", new_content="content")
    assert "error" in r


def test_missing_section_marker():
    r = execute(path="/tmp/x.md", new_content="content")
    assert "error" in r


# ---------------------------------------------------------------------------
# File not found
# ---------------------------------------------------------------------------

def test_file_not_found_no_create():
    r = execute(path="/nonexistent/file.md", section_marker="## Sec", new_content="x")
    assert "error" in r


def test_file_not_found_create_if_missing(tmp_path):
    p = tmp_path / "new.md"
    r = execute(path=str(p), section_marker="## New", new_content="hello", create_if_missing=True)
    assert "error" not in r
    assert p.exists()
    content = p.read_text()
    assert "## New" in content
    assert "hello" in content


# ---------------------------------------------------------------------------
# Section found — replace content
# ---------------------------------------------------------------------------

def test_section_replaced(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("# Title\n## Section\nold content\n## Next\nmore\n")
    r = execute(path=str(p), section_marker="## Section", new_content="new content")
    assert "error" not in r
    assert r["section_found"] is True
    result_text = p.read_text()
    assert "new content" in result_text
    assert "old content" not in result_text
    assert "## Next" in result_text


def test_section_replaced_eof(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("## Section\nold content\n")
    r = execute(path=str(p), section_marker="## Section", new_content="replaced")
    assert r["section_found"] is True
    assert "replaced" in p.read_text()


def test_section_with_end_marker(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("## Section\nold\n<!-- end -->\nafter\n")
    r = execute(
        path=str(p),
        section_marker="## Section",
        new_content="new",
        end_marker="<!-- end -->",
    )
    assert r["section_found"] is True
    text = p.read_text()
    assert "new" in text
    assert "old" not in text
    assert "after" in text


# ---------------------------------------------------------------------------
# Section not found
# ---------------------------------------------------------------------------

def test_section_not_found_no_create(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("no section here\n")
    r = execute(path=str(p), section_marker="## Missing", new_content="x")
    assert r["section_found"] is False
    assert r["lines_replaced"] == 0


def test_section_not_found_with_create(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("existing content\n")
    r = execute(
        path=str(p),
        section_marker="## New Section",
        new_content="appended",
        create_if_missing=True,
    )
    assert "error" not in r
    text = p.read_text()
    assert "## New Section" in text
    assert "appended" in text


# ---------------------------------------------------------------------------
# Artifact dir resolution
# ---------------------------------------------------------------------------

def test_artifact_dir_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("P1_RUN_ARTIFACT_DIR", str(tmp_path))
    # filename only (no directory component) → gets placed in artifact dir
    r = execute(path="output.md", section_marker="## Sec", new_content="hi", create_if_missing=True)
    assert "error" not in r
    expected = tmp_path / "output.md"
    assert expected.exists()


# ---------------------------------------------------------------------------
# lines_replaced count
# ---------------------------------------------------------------------------

def test_lines_replaced_count(tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("## Section\nline1\nline2\nline3\n## End\n")
    r = execute(path=str(p), section_marker="## Section", new_content="replaced")
    assert r["lines_replaced"] == 3
