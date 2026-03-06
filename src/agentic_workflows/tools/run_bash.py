import subprocess
from typing import Any

from agentic_workflows.tools._security import check_bash_command, validate_path_within_sandbox
from agentic_workflows.tools.base import Tool

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120
_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB per stream


class RunBashTool(Tool):
    name = "run_bash"
    description = (
        "Run a bash command and return stdout, stderr, and returncode. "
        "Required args: command (string). "
        "Optional args: timeout (int, seconds, default 30, max 120), "
        "cwd (string, working directory)."
    )

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        command: str = args.get("command", "")
        timeout: int = min(int(args.get("timeout", _DEFAULT_TIMEOUT)), _MAX_TIMEOUT)
        cwd: str | None = args.get("cwd") or None

        if not command or not command.strip():
            return {"error": "command is required"}

        # Security: command denylist/allowlist filtering
        cmd_err = check_bash_command(command)
        if cmd_err is not None:
            return cmd_err

        # Security: sandbox check on cwd when set
        if cwd is not None:
            sandbox_err = validate_path_within_sandbox(cwd)
            if sandbox_err is not None:
                return sandbox_err

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            stdout = result.stdout[:_MAX_OUTPUT_BYTES]
            stderr = result.stderr[:_MAX_OUTPUT_BYTES]
            return {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"command timed out after {timeout}s", "returncode": -1}
        except Exception as exc:
            return {"error": str(exc), "returncode": -1}
