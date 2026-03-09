"""Wave 0 stub tests for structural_health in audit_report.

All tests raise NotImplementedError — RED state until plan 07.6-04 implements
the structural_health sub-dict in the audit report and json_parse_fallback counter.
"""
from __future__ import annotations

import pytest

from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from tests.conftest import ScriptedProvider


class TestStructuralHealthKey:
    def test_audit_report_has_structural_health_key(self) -> None:
        """RunResult audit_report contains 'structural_health' key."""
        raise NotImplementedError("stub — implement in plan 07.6-04")

    def test_schema_mismatch_counter_present(self) -> None:
        """audit_report['structural_health']['schema_mismatch'] exists and is int."""
        raise NotImplementedError("stub — implement in plan 07.6-04")


class TestFallbackCounter:
    def test_json_parse_fallback_counter_increments(self) -> None:
        """A run with malformed JSON increments the json_parse_fallback counter."""
        raise NotImplementedError("stub — implement in plan 07.6-04")
