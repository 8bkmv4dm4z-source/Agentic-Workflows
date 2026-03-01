from __future__ import annotations

"""Memoization policy rules for Phase 1 orchestration."""

from dataclasses import dataclass
from typing import Any

from agentic_workflows.orchestration.langgraph.state_schema import hash_json


@dataclass(frozen=True)
class MemoizationPolicy:
    """Deterministic rules for deciding when memoization must occur."""

    max_policy_retries: int = 2

    def requires_memoization(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
    ) -> bool:
        """Return True when a tool result should be memoized before progress."""
        if tool_name != "write_file":
            return False

        path = str(args.get("path", "")).lower()
        content = str(args.get("content", ""))
        if "fib" in path:
            return True
        if len(content) >= 400:
            return True
        if content.count(",") > 20:
            return True

        # Fallback to result-based signal when content is not available.
        if "result" in result and "wrote" in str(result["result"]).lower():
            return len(content) > 0 and len(content) >= 200

        return False

    def suggested_memo_key(
        self, *, tool_name: str, args: dict[str, Any], result: dict[str, Any]
    ) -> str:
        """Generate a stable key for memo write/read consistency."""
        if tool_name == "write_file":
            path = str(args.get("path", "")).strip()
            if path:
                return f"write_file:{path}"
        return f"{tool_name}:{hash_json({'args': args, 'result': result})[:12]}"
