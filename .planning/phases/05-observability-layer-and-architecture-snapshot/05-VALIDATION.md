---
phase: 5
slug: observability-layer-and-architecture-snapshot
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-04
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| **Quick run command** | `pytest tests/unit/test_observability.py -x -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_observability.py -x -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 5-W0-01 | W0 | 0 | OBSV-01 | unit stub | `pytest tests/unit/test_observability.py -x -q` | ❌ W0 | ⬜ pending |
| 5-W0-02 | W0 | 0 | LRNG-03 | smoke stub | `pytest tests/unit/test_phase_progression_doc.py -x -q` | ❌ W0 | ⬜ pending |
| 5-01-01 | 01 | 1 | OBSV-01 | unit | `pytest tests/unit/test_observability.py::test_langfuse_available_with_3x -x` | ❌ W0 | ⬜ pending |
| 5-01-02 | 01 | 1 | OBSV-01 | unit | `pytest tests/unit/test_observability.py::test_callback_handler_wired -x` | ❌ W0 | ⬜ pending |
| 5-01-03 | 01 | 1 | OBSV-01 | unit | `pytest tests/unit/test_observability.py::test_ollama_generate_has_observe_decorator -x` | ❌ W0 | ⬜ pending |
| 5-02-01 | 02 | 1 | LRNG-03 | smoke | `pytest tests/unit/test_phase_progression_doc.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_observability.py` — stubs for OBSV-01: `test_langfuse_available_with_3x`, `test_callback_handler_wired`, `test_ollama_generate_has_observe_decorator`, `test_get_langfuse_callback_handler_none_guard`
- [ ] `tests/unit/test_phase_progression_doc.py` — smoke test: `docs/architecture/PHASE_PROGRESSION.md` exists and contains expected phase sections (H2 markers for Phase 1–4)

*Existing infrastructure (pytest, conftest.py) covers all other phase requirements.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Langfuse trace appears in cloud UI with node spans | OBSV-01 SC#1 | Requires live LANGFUSE_PUBLIC_KEY + cloud account | Set LANGFUSE_PUBLIC_KEY in .env, run `make run`, check cloud.langfuse.com for trace with ≥1 span per graph node |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
