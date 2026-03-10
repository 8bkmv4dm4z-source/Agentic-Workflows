"""Tests for report_schema_compliance() in observability.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestReportSchemaCompliance:
    """Unit tests for report_schema_compliance Langfuse integration."""

    @patch("agentic_workflows.observability.get_langfuse_client")
    def test_success_reports_value_one(self, mock_get_client: MagicMock) -> None:
        from agentic_workflows.observability import report_schema_compliance

        client = MagicMock()
        mock_get_client.return_value = client

        report_schema_compliance(role="supervisor", first_attempt_success=True)

        client.create_score.assert_called_once()
        call_kwargs = client.create_score.call_args[1]
        assert call_kwargs["name"] == "schema_compliance"
        assert call_kwargs["value"] == 1.0
        assert call_kwargs["data_type"] == "NUMERIC"
        assert call_kwargs["comment"] == "role=supervisor"

    @patch("agentic_workflows.observability.get_langfuse_client")
    def test_failure_reports_value_zero(self, mock_get_client: MagicMock) -> None:
        from agentic_workflows.observability import report_schema_compliance

        client = MagicMock()
        mock_get_client.return_value = client

        report_schema_compliance(role="supervisor", first_attempt_success=False)

        call_kwargs = client.create_score.call_args[1]
        assert call_kwargs["value"] == 0.0

    @patch("agentic_workflows.observability.get_langfuse_client")
    def test_trace_id_passed_through(self, mock_get_client: MagicMock) -> None:
        from agentic_workflows.observability import report_schema_compliance

        client = MagicMock()
        mock_get_client.return_value = client

        report_schema_compliance(
            role="executor", first_attempt_success=True, trace_id="abc"
        )

        call_kwargs = client.create_score.call_args[1]
        assert call_kwargs["trace_id"] == "abc"

    @patch("agentic_workflows.observability.get_langfuse_client")
    def test_run_id_maps_to_session_id(self, mock_get_client: MagicMock) -> None:
        from agentic_workflows.observability import report_schema_compliance

        client = MagicMock()
        mock_get_client.return_value = client

        report_schema_compliance(
            role="supervisor", first_attempt_success=True, run_id="run-1"
        )

        call_kwargs = client.create_score.call_args[1]
        assert call_kwargs["session_id"] == "run-1"

    @patch("agentic_workflows.observability.get_langfuse_client")
    def test_no_client_is_noop(self, mock_get_client: MagicMock) -> None:
        from agentic_workflows.observability import report_schema_compliance

        mock_get_client.return_value = None

        # Should not raise
        report_schema_compliance(role="supervisor", first_attempt_success=True)

    @patch("agentic_workflows.observability.get_langfuse_client")
    def test_exception_swallowed_silently(self, mock_get_client: MagicMock) -> None:
        from agentic_workflows.observability import report_schema_compliance

        client = MagicMock()
        client.create_score.side_effect = RuntimeError("Langfuse down")
        mock_get_client.return_value = client

        # Should not raise
        report_schema_compliance(role="supervisor", first_attempt_success=True)
