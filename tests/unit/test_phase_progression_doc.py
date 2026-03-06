"""Smoke test: docs/architecture/PHASE_PROGRESSION.md exists and has expected phase sections."""
from __future__ import annotations

import pathlib

PHASE_PROGRESSION_PATH = pathlib.Path("docs/architecture/PHASE_PROGRESSION.md")

EXPECTED_PHASE_HEADINGS = [
    "Phase 1",
    "Phase 2",
    "Phase 3",
    "Phase 4",
]


def test_phase_progression_doc_exists():
    """docs/architecture/PHASE_PROGRESSION.md must exist."""
    assert PHASE_PROGRESSION_PATH.exists(), (
        f"Expected {PHASE_PROGRESSION_PATH} to exist — LRNG-03 architecture snapshot not created."
    )


def test_phase_progression_doc_has_all_phases():
    """PHASE_PROGRESSION.md must contain a section for each phase (Phase 1 through Phase 4)."""
    assert PHASE_PROGRESSION_PATH.exists(), "File missing — cannot check content."
    content = PHASE_PROGRESSION_PATH.read_text(encoding="utf-8")
    for heading in EXPECTED_PHASE_HEADINGS:
        assert heading in content, (
            f"'{heading}' section not found in PHASE_PROGRESSION.md. "
            f"Document must cover all phases 1-4."
        )


def test_phase_progression_doc_has_mermaid():
    """PHASE_PROGRESSION.md must contain at least one Mermaid diagram block."""
    assert PHASE_PROGRESSION_PATH.exists(), "File missing — cannot check content."
    content = PHASE_PROGRESSION_PATH.read_text(encoding="utf-8")
    assert "```mermaid" in content, (
        "No Mermaid diagram found in PHASE_PROGRESSION.md. "
        "Document must include graph topology diagrams."
    )
