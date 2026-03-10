from __future__ import annotations

import logging
from pathlib import Path

# Messages that go to admin_log.txt — operational events worth monitoring.
_ADMIN_PREFIXES: tuple[str, ...] = (
    "RUN START",
    "RUN FINALIZE",
    "AUDIT REPORT",
    "AUDIT WARN",
    "AUDIT FAIL",
    "AUDITOR START",
    "AUDITOR MISSION",
    "AUDITOR SUMMARY",
    "MISSION REPORT",
    "MISSION STATUS",
    "MISSION CONTRACT",
    "PLANNER STEP",
    "SPECIALIST REDIRECT",
    "SPECIALIST EXECUTE",
    "SPECIALIST OUTPUT",
    "TOOL EXEC",
    "TOOL RESULT",
    "CONTEXT INJECT",
    "CASCADE QUERY",
    "CASCADE UPSERT",
    "EMBED INIT",
    "ARTIFACT STORE",
)

_setup_done: bool = False


class AdminFilter(logging.Filter):
    """Pass only records whose message starts with an _ADMIN_PREFIXES entry."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg_str = record.getMessage()
        except Exception:  # noqa: BLE001
            msg_str = str(record.msg)
        if not msg_str:
            return False
        return any(msg_str.startswith(prefix) for prefix in _ADMIN_PREFIXES)


def get_logger(name: str = "agent") -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)

        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


def setup_dual_logging(log_dir: str = ".tmp") -> None:
    """Wire verbose log.txt and filtered admin_log.txt to the root logger.

    Idempotent — safe to call multiple times; only installs handlers once.
    """
    global _setup_done  # noqa: PLW0603
    if _setup_done:
        return
    _setup_done = True

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Verbose: captures everything (DEBUG+)
    verbose_handler = logging.FileHandler(log_path / "log.txt", mode="a")
    verbose_handler.setLevel(logging.DEBUG)
    verbose_handler.setFormatter(fmt)
    root.addHandler(verbose_handler)

    # Admin: operational events only (filtered by prefix)
    admin_handler = logging.FileHandler(log_path / "admin_log.txt", mode="a")
    admin_handler.setLevel(logging.DEBUG)
    admin_handler.setFormatter(fmt)
    admin_handler.addFilter(AdminFilter())
    root.addHandler(admin_handler)

    # Server: INFO+ from all loggers → server_logs.txt
    server_handler = logging.FileHandler(log_path / "server_logs.txt", mode="a")
    server_handler.setLevel(logging.INFO)
    server_handler.setFormatter(fmt)
    root.addHandler(server_handler)

    # Provider: DEBUG+ from provider/graph/tool loggers → provider_logs.txt
    provider_handler = logging.FileHandler(log_path / "provider_logs.txt", mode="a")
    provider_handler.setLevel(logging.DEBUG)
    provider_handler.setFormatter(fmt)
    for _name in ("langgraph.provider", "agentic_workflows", "langgraph"):
        _lg = logging.getLogger(_name)
        _lg.addHandler(provider_handler)
        _lg.propagate = True

    # API debug: per-step planner debug info → api.log
    api_handler = logging.FileHandler(log_path / "api.log", mode="a")
    api_handler.setLevel(logging.DEBUG)
    api_handler.setFormatter(fmt)
    _api_lg = logging.getLogger("api_debug")
    _api_lg.addHandler(api_handler)
    _api_lg.propagate = True
