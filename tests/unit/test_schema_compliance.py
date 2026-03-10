"""Tests for report_schema_compliance() in observability.py."""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import MagicMock, patch


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


class TestSchemaComplianceWiring:
    """Integration test: graph.py calls report_schema_compliance after parse."""

    @patch("agentic_workflows.orchestration.langgraph.graph.report_schema_compliance")
    def test_graph_calls_compliance_on_parse(  # noqa: PLR6301
        self, mock_report: MagicMock
    ) -> None:
        """Verify _plan_next_action triggers report_schema_compliance."""
        from agentic_workflows.orchestration.langgraph.checkpoint_store import (
            SQLiteCheckpointStore,
        )
        from agentic_workflows.orchestration.langgraph.graph import (
            LangGraphOrchestrator,
        )
        from tests.conftest import ScriptedProvider

        db_path = pathlib.Path(tempfile.mkdtemp()) / "test.db"

        provider = ScriptedProvider([
            {"action": "tool", "tool_name": "sort_array", "args": {"array": [3, 1, 2]}},
            {"action": "finish", "answer": "done"},
        ])
        checkpoint_store = SQLiteCheckpointStore(db_path=str(db_path))
        orch = LangGraphOrchestrator(
            provider=provider,
            checkpoint_store=checkpoint_store,
        )
        orch.run("Sort the array [3,1,2]")

        # report_schema_compliance should have been called at least once
        assert mock_report.call_count >= 1
        # First call should report success (ScriptedProvider emits clean JSON)
        first_call = mock_report.call_args_list[0]
        assert first_call[1]["first_attempt_success"] is True
        assert first_call[1]["role"] == "supervisor"
