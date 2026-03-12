---
phase: 8
slug: multi-model-sycl-routing-and-planner-bottleneck-resolution
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-11
---

# Phase 8 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `pytest tests/unit/ -q` |
| **Full suite command** | `pytest tests/ -q` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/ -q`
- **After every plan wave:** Run `pytest tests/ -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 8-01-01 | 01 | 1 | SYCL-01 | unit | `pytest tests/unit/test_provider_port.py -q -k with_port` | ❌ W0 | ⬜ pending |
| 8-01-02 | 01 | 1 | SYCL-01 | unit | `pytest tests/unit/test_provider_port.py -q -k role_provider` | ❌ W0 | ⬜ pending |
| 8-02-01 | 02 | 2 | SYCL-01 | unit | `pytest tests/unit/test_provider_port.py -q -k with_port` | ❌ W0 | ⬜ pending |
| 8-02-02 | 02 | 2 | SYCL-01 | regression | `pytest tests/ -q` | ✅ | ⬜ pending |
| 8-03-01 | 03 | 3 | SYCL-02 | unit | `pytest tests/unit/ -q -x` | ✅ | ⬜ pending |
| 8-03-02 | 03 | 3 | SYCL-02 | regression | `pytest tests/ -q` | ✅ | ⬜ pending |
| 8-04-01 | 04 | 2 | BTLNK-02 | unit | `pytest tests/unit/test_tool_result_cache.py -q -k "pool_none or args_hash or store_and_get"` | ❌ W0 | ⬜ pending |
| 8-04-02 | 04 | 2 | BTLNK-02 | regression | `pytest tests/ -q` | ✅ | ⬜ pending |
| 8-05-01 | 05 | 4 | BTLNK-01 | unit | `pytest tests/unit/test_tool_result_cache.py -q -k "structural_health or truncation"` | ❌ W0 | ⬜ pending |
| 8-05-02 | 05 | 4 | BTLNK-01 | integration | `pytest tests/integration/test_context_overflow.py -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_provider_port.py` — stubs for SYCL-01 `with_port()` and role-specific provider factory (created in Plan 01 Task 1)
- [ ] `tests/unit/test_tool_result_cache.py` — stubs for BTLNK-02 ToolResultCache store/get/TTL/pool-none (created in Plan 01 Task 2)
- [ ] `tests/integration/test_context_overflow.py` — stubs for BTLNK-01 large-result planner context cap (created in Plan 01 Task 2)

*All test files above must be created in Wave 0 (Plan 01) as stubs before implementation tasks run.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Two llama-server processes running on different ports serve distinct roles without interference | SYCL-01 | Requires live llama-server processes | Start two llama-server instances on ports 8080/8081; run orchestrator; confirm planner hits 8080 and executor hits 8081 via server logs |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
