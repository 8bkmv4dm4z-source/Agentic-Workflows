"""Tests for dual-file logging: AdminFilter and setup_dual_logging."""

import logging

import pytest

import agentic_workflows.logger as logger_mod
from agentic_workflows.logger import _ADMIN_PREFIXES, AdminFilter, setup_dual_logging


@pytest.fixture(autouse=True)
def _reset_logging_state(tmp_path):
    """Reset the module-level guard and clean root handlers after each test."""
    logger_mod._setup_done = False
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    yield tmp_path
    # Restore root logger
    root.handlers = original_handlers
    root.setLevel(original_level)


class TestAdminFilter:
    def test_passes_admin_prefix(self):
        f = AdminFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "MISSION STATUS changed to complete", (), None
        )
        assert f.filter(record) is True

    def test_blocks_non_admin_message(self):
        f = AdminFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "PARSER extracted 3 actions", (), None
        )
        assert f.filter(record) is False

    def test_passes_audit_warn(self):
        f = AdminFilter()
        record = logging.LogRecord(
            "test", logging.WARNING, "", 0, "AUDIT WARN chain_integrity", (), None
        )
        assert f.filter(record) is True

    def test_handles_percent_style_args(self):
        f = AdminFilter()
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "TOOL EXEC %s called with %d args", ("sort_array", 2), None
        )
        assert f.filter(record) is True

    def test_blocks_empty_message(self):
        f = AdminFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        assert f.filter(record) is False


class TestSetupDualLogging:
    def test_creates_both_files(self, _reset_logging_state):
        tmp = _reset_logging_state
        setup_dual_logging(log_dir=str(tmp))

        logger = logging.getLogger("test.dual")
        logger.info("TOOL EXEC sort_array")
        logger.info("PARSER internal debug line")

        # Flush handlers
        for h in logging.getLogger().handlers:
            h.flush()

        verbose = (tmp / "log.txt").read_text()
        admin = (tmp / "admin_log.txt").read_text()

        assert "TOOL EXEC sort_array" in verbose
        assert "PARSER internal debug line" in verbose
        assert "TOOL EXEC sort_array" in admin
        assert "PARSER internal debug line" not in admin

    def test_idempotent(self, _reset_logging_state):
        tmp = _reset_logging_state
        setup_dual_logging(log_dir=str(tmp))
        handler_count = len(logging.getLogger().handlers)
        setup_dual_logging(log_dir=str(tmp))
        assert len(logging.getLogger().handlers) == handler_count

    def test_verbose_captures_debug(self, _reset_logging_state):
        tmp = _reset_logging_state
        setup_dual_logging(log_dir=str(tmp))

        logger = logging.getLogger("test.verbose")
        logger.setLevel(logging.DEBUG)
        logger.debug("low-level debug info")

        for h in logging.getLogger().handlers:
            h.flush()

        verbose = (tmp / "log.txt").read_text()
        assert "low-level debug info" in verbose

    def test_admin_filters_all_prefixes(self, _reset_logging_state):
        tmp = _reset_logging_state
        setup_dual_logging(log_dir=str(tmp))

        logger = logging.getLogger("test.prefixes")
        for prefix in _ADMIN_PREFIXES:
            logger.info("%s some detail", prefix.strip())

        for h in logging.getLogger().handlers:
            h.flush()

        admin = (tmp / "admin_log.txt").read_text()
        for prefix in _ADMIN_PREFIXES:
            assert prefix.strip() in admin, f"Missing admin prefix: {prefix!r}"

    def test_console_handlers_unchanged(self, _reset_logging_state):
        tmp = _reset_logging_state
        root = logging.getLogger()
        stream_handlers_before = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
        setup_dual_logging(log_dir=str(tmp))
        stream_handlers_after = [h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)]
        assert len(stream_handlers_before) == len(stream_handlers_after)
