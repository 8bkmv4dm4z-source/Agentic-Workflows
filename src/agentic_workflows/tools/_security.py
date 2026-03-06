from __future__ import annotations

"""Shared security guards for filesystem, bash, HTTP, and content-size controls.

All new guardrails are **env-var gated and off by default** — existing behaviour
is preserved when the env vars are unset.  Phase 6 (HTTP service layer) will set
them to strict values.
"""

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------

def validate_path_within_cwd(path_str: str) -> tuple[Path, dict[str, Any] | None]:
    """Resolve *path_str* and verify it sits under the current working directory.

    Returns ``(resolved_path, None)`` on success, or
    ``(Path(), {"error": ...})`` when the path is invalid or escapes cwd.
    """
    if not path_str:
        return Path(), {"error": "path is required"}

    cwd = Path.cwd().resolve()
    try:
        target = Path(path_str).resolve()
    except Exception:
        return Path(), {"error": f"invalid path: {path_str}"}

    try:
        target.relative_to(cwd)
    except ValueError:
        return Path(), {"error": f"path outside working directory: {path_str}"}

    return target, None


def validate_path_within_sandbox(path_str: str) -> dict[str, Any] | None:
    """Check *path_str* against ``P1_TOOL_SANDBOX_ROOT`` when set.

    Returns ``None`` on success (or when env var is unset), or
    ``{"error": ...}`` when the path escapes the sandbox.
    """
    sandbox_root = os.getenv("P1_TOOL_SANDBOX_ROOT", "").strip()
    if not sandbox_root:
        return None  # guardrail inactive

    if not path_str:
        return {"error": "path is required"}

    try:
        sandbox = Path(sandbox_root).resolve()
        target = Path(path_str).resolve()
    except Exception:
        return {"error": f"invalid path: {path_str}"}

    try:
        target.relative_to(sandbox)
    except ValueError:
        return {"error": f"path outside sandbox ({sandbox_root}): {path_str}"}

    return None


# ---------------------------------------------------------------------------
# Bash command filtering
# ---------------------------------------------------------------------------

def check_bash_command(command: str) -> dict[str, Any] | None:
    """Filter bash commands using denylist patterns and optional allowlist.

    Env vars:
        ``P1_BASH_DENIED_PATTERNS`` — comma-separated substrings to block
            (e.g. ``rm -rf,mkfs,dd if=``).
        ``P1_BASH_ALLOWED_COMMANDS`` — comma-separated command prefixes that
            are always allowed (e.g. ``ls,cat,echo``).  When set, commands not
            matching any prefix AND matching a denied pattern are blocked.

    Returns ``None`` when the command is allowed, ``{"error": ...}`` when blocked.
    """
    denied_raw = os.getenv("P1_BASH_DENIED_PATTERNS", "").strip()
    if not denied_raw:
        return None  # guardrail inactive

    denied_patterns = [p.strip() for p in denied_raw.split(",") if p.strip()]

    # Optional allowlist — if a command starts with an allowed prefix, skip deny check.
    allowed_raw = os.getenv("P1_BASH_ALLOWED_COMMANDS", "").strip()
    if allowed_raw:
        allowed_prefixes = [p.strip() for p in allowed_raw.split(",") if p.strip()]
        cmd_stripped = command.strip()
        if any(cmd_stripped.startswith(prefix) for prefix in allowed_prefixes):
            return None

    for pattern in denied_patterns:
        if pattern in command:
            return {"error": f"command blocked by security policy (matched: {pattern!r})"}

    return None


# ---------------------------------------------------------------------------
# HTTP domain allowlist
# ---------------------------------------------------------------------------

def check_http_domain(url: str) -> dict[str, Any] | None:
    """Filter HTTP requests by domain allowlist.

    Env var:
        ``P1_HTTP_ALLOWED_DOMAINS`` — comma-separated domain names
            (e.g. ``api.github.com,httpbin.org``).

    Returns ``None`` when allowed (or when env var is unset), ``{"error": ...}``
    when the domain is not in the allowlist.
    """
    allowed_raw = os.getenv("P1_HTTP_ALLOWED_DOMAINS", "").strip()
    if not allowed_raw:
        return None  # guardrail inactive

    allowed_domains = {d.strip().lower() for d in allowed_raw.split(",") if d.strip()}
    hostname = (urlparse(url).hostname or "").lower()
    if hostname not in allowed_domains:
        return {"error": f"domain not in allowlist: {hostname}"}

    return None


# ---------------------------------------------------------------------------
# Content size cap
# ---------------------------------------------------------------------------

def check_content_size(
    content: str | bytes,
    env_var: str,
    default_max: int,
) -> dict[str, Any] | None:
    """Block content exceeding a configurable size limit.

    Args:
        content: The payload to measure.
        env_var: Name of the env var that overrides *default_max* (bytes).
        default_max: Fallback cap when env var is unset or ``0``.

    Returns ``None`` when within limits, ``{"error": ...}`` when exceeded.
    A *default_max* of ``0`` means *no limit* unless the env var provides one.
    """
    max_bytes = int(os.getenv(env_var, str(default_max)) or default_max)
    if max_bytes <= 0:
        return None  # no cap

    size = len(content) if isinstance(content, bytes) else len(content.encode("utf-8", errors="replace"))
    if size > max_bytes:
        return {"error": f"content size ({size} bytes) exceeds limit ({max_bytes} bytes)"}

    return None
