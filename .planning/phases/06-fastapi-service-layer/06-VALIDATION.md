---
phase: 6
slug: fastapi-service-layer
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-05
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24 |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/ -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/ -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | PROD-01 | integration | `pytest tests/integration/test_api_service.py::test_post_run_sse -x` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | PROD-01 | integration | `pytest tests/integration/test_api_service.py::test_get_run_completed -x` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | PROD-01 | integration | `pytest tests/integration/test_api_service.py::test_get_run_in_progress -x` | ❌ W0 | ⬜ pending |
| 06-01-04 | 01 | 1 | PROD-01 | integration | `pytest tests/integration/test_api_service.py::test_health -x` | ❌ W0 | ⬜ pending |
| 06-01-05 | 01 | 1 | PROD-01 | integration | `pytest tests/integration/test_api_service.py::test_tools_list -x` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 1 | PROD-02 | integration | `pytest tests/integration/test_api_service.py::test_get_run_stream -x` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 1 | PROD-02 | integration | `pytest tests/integration/test_api_service.py::test_sse_events_stream -x` | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 1 | PROD-02 | unit | `pytest tests/unit/test_api_lifespan.py::test_graph_compiled_once -x` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 2 | PROD-01+02 | integration | `pytest tests/integration/test_api_service.py::test_concurrent_runs -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/integration/test_api_service.py` — all PROD-01/PROD-02 contract tests
- [ ] `tests/unit/test_api_lifespan.py` — lifespan singleton tests
- [ ] `tests/eval/__init__.py` + `tests/eval/test_eval_harness.py` — 3+ ScriptedProvider scenarios
- [ ] `tests/eval/conftest.py` — eval fixtures (ScriptedProvider variants)
- [ ] Add `sse-starlette`, `fastapi`, `uvicorn`, `httpx-sse` to pyproject.toml

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| curl SSE stream shows events before run completes | PROD-02 | Real-time observation | `curl -N http://localhost:8000/run/{id}/stream` during active run |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
