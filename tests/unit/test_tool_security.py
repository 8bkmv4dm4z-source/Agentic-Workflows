"""Tests for security guardrails in _security.py and tool integrations.

All guardrails are env-var gated.  Tests use monkeypatch.setenv() so
existing tests are unaffected (env vars unset = guardrails inactive).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agentic_workflows.tools._security import (
    check_bash_command,
    check_content_size,
    check_http_domain,
    validate_path_within_sandbox,
)

# ---------------------------------------------------------------------------
# validate_path_within_sandbox
# ---------------------------------------------------------------------------

class TestValidatePathWithinSandbox:
    def test_inactive_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("P1_TOOL_SANDBOX_ROOT", raising=False)
        assert validate_path_within_sandbox("/any/path") is None

    def test_allows_path_inside_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(tmp_path))
        inner = tmp_path / "sub" / "file.txt"
        inner.parent.mkdir(parents=True, exist_ok=True)
        inner.touch()
        assert validate_path_within_sandbox(str(inner)) is None

    def test_blocks_path_outside_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(sandbox))
        outside = tmp_path / "outside.txt"
        outside.touch()
        result = validate_path_within_sandbox(str(outside))
        assert result is not None
        assert "error" in result
        assert "outside sandbox" in result["error"]

    def test_blocks_traversal_attack(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(sandbox))
        traversal = str(sandbox / ".." / "etc" / "passwd")
        result = validate_path_within_sandbox(traversal)
        assert result is not None
        assert "error" in result

    def test_blocks_empty_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(tmp_path))
        result = validate_path_within_sandbox("")
        assert result is not None
        assert "error" in result


# ---------------------------------------------------------------------------
# check_bash_command
# ---------------------------------------------------------------------------

class TestCheckBashCommand:
    def test_inactive_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("P1_BASH_DENIED_PATTERNS", raising=False)
        assert check_bash_command("rm -rf /") is None

    def test_blocks_denied_pattern(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_DENIED_PATTERNS", "rm -rf,mkfs")
        result = check_bash_command("rm -rf /tmp/test")
        assert result is not None
        assert "blocked" in result["error"]

    def test_blocks_second_denied_pattern(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_DENIED_PATTERNS", "rm -rf,mkfs")
        result = check_bash_command("mkfs.ext4 /dev/sda1")
        assert result is not None
        assert "blocked" in result["error"]

    def test_allows_safe_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_DENIED_PATTERNS", "rm -rf,mkfs")
        assert check_bash_command("ls -la") is None

    def test_allowlist_overrides_denylist(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_DENIED_PATTERNS", "rm")
        monkeypatch.setenv("P1_BASH_ALLOWED_COMMANDS", "rm -f temp")
        # Starts with allowed prefix → passes despite "rm" in denied
        assert check_bash_command("rm -f temp_file.txt") is None

    def test_denylist_active_without_allowlist_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_DENIED_PATTERNS", "rm -rf")
        monkeypatch.setenv("P1_BASH_ALLOWED_COMMANDS", "ls,cat")
        result = check_bash_command("rm -rf /tmp")
        assert result is not None
        assert "blocked" in result["error"]


# ---------------------------------------------------------------------------
# check_http_domain
# ---------------------------------------------------------------------------

class TestCheckHttpDomain:
    def test_inactive_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("P1_HTTP_ALLOWED_DOMAINS", raising=False)
        assert check_http_domain("https://evil.com/steal") is None

    def test_allows_listed_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_HTTP_ALLOWED_DOMAINS", "api.github.com,httpbin.org")
        assert check_http_domain("https://api.github.com/repos") is None

    def test_blocks_unlisted_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_HTTP_ALLOWED_DOMAINS", "api.github.com")
        result = check_http_domain("https://evil.com/steal")
        assert result is not None
        assert "not in allowlist" in result["error"]

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_HTTP_ALLOWED_DOMAINS", "API.Github.COM")
        assert check_http_domain("https://api.github.com/repos") is None


# ---------------------------------------------------------------------------
# check_content_size
# ---------------------------------------------------------------------------

class TestCheckContentSize:
    def test_no_limit_when_default_zero(self) -> None:
        assert check_content_size("x" * 10_000_000, "UNUSED_VAR", 0) is None

    def test_allows_within_limit(self) -> None:
        assert check_content_size("hello", "UNUSED_VAR", 100) is None

    def test_blocks_over_limit(self) -> None:
        result = check_content_size("x" * 200, "UNUSED_VAR", 100)
        assert result is not None
        assert "exceeds limit" in result["error"]

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_SIZE_CAP", "10")
        result = check_content_size("x" * 20, "TEST_SIZE_CAP", 1000)
        assert result is not None
        assert "exceeds limit" in result["error"]

    def test_bytes_input(self) -> None:
        result = check_content_size(b"x" * 200, "UNUSED_VAR", 100)
        assert result is not None
        assert "exceeds limit" in result["error"]


# ---------------------------------------------------------------------------
# Tool integration: RunBashTool
# ---------------------------------------------------------------------------

class TestRunBashToolSecurity:
    def test_blocks_denied_command(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_ENABLED", "true")
        monkeypatch.setenv("P1_BASH_DENIED_PATTERNS", "rm -rf")
        from agentic_workflows.tools.run_bash import RunBashTool
        tool = RunBashTool()
        result = tool.execute({"command": "rm -rf /tmp/test"})
        assert "error" in result
        assert "blocked" in result["error"]

    def test_allows_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_BASH_ENABLED", "true")
        monkeypatch.delenv("P1_BASH_DENIED_PATTERNS", raising=False)
        from agentic_workflows.tools.run_bash import RunBashTool
        tool = RunBashTool()
        result = tool.execute({"command": "echo hello"})
        assert result.get("returncode") == 0
        assert "hello" in result.get("stdout", "")


# ---------------------------------------------------------------------------
# Tool integration: WriteFileTool
# ---------------------------------------------------------------------------

class TestWriteFileToolSecurity:
    def test_blocks_oversized_content(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("P1_WRITE_FILE_MAX_BYTES", "10")
        from agentic_workflows.tools.write_file import WriteFileTool
        tool = WriteFileTool()
        result = tool.execute({"path": str(tmp_path / "big.txt"), "content": "x" * 100})
        assert "error" in result
        assert "exceeds limit" in result["error"]

    def test_blocks_path_outside_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(sandbox))
        from agentic_workflows.tools.write_file import WriteFileTool
        tool = WriteFileTool()
        result = tool.execute({"path": str(tmp_path / "outside.txt"), "content": "data"})
        assert "error" in result
        assert "outside sandbox" in result["error"]


# ---------------------------------------------------------------------------
# Tool integration: ReadFileTool
# ---------------------------------------------------------------------------

class TestReadFileToolSecurity:
    def test_blocks_path_outside_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(sandbox))
        # Create a file outside sandbox
        outside = tmp_path / "secret.txt"
        outside.write_text("secret data")
        from agentic_workflows.tools.read_file import ReadFileTool
        tool = ReadFileTool()
        result = tool.execute({"path": str(outside)})
        assert "error" in result
        assert "outside sandbox" in result["error"]

    def test_truncates_when_cap_set(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("P1_READ_FILE_MAX_BYTES", "5")
        target = tmp_path / "big.txt"
        target.write_text("hello world this is a long file")
        from agentic_workflows.tools.read_file import ReadFileTool
        tool = ReadFileTool()
        result = tool.execute({"path": str(target)})
        assert result.get("content") == "hello"


# ---------------------------------------------------------------------------
# Tool integration: HttpRequestTool (domain check only — no real HTTP)
# ---------------------------------------------------------------------------

class TestHttpRequestToolSecurity:
    def test_blocks_unlisted_domain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("P1_HTTP_ALLOWED_DOMAINS", "api.github.com")
        from agentic_workflows.tools.http_request import HttpRequestTool
        tool = HttpRequestTool()
        result = tool.execute({"url": "https://evil.com/steal"})
        assert "error" in result
        # Domain check might fail before or after DNS — either "not in allowlist" or DNS error
        assert "not in allowlist" in result.get("error", "") or "DNS" in result.get("error", "")
