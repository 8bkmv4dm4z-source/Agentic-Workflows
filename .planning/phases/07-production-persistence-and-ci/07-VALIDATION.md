---
phase: 7
slug: production-persistence-and-ci
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-06
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.24+ + pytest-cov 6.x |
| **Config file** | pyproject.toml `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/ -q -x` |
| **Full suite command** | `pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/ -q -x`
- **After every plan wave:** Run `pytest tests/ -q --cov=src/agentic_workflows --cov-fail-under=80`
- **Before `/gsd:verify-work`:** Full suite must be green + Docker build green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | PROD-03 | unit | `pytest tests/unit/test_checkpoint_postgres.py -x` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 1 | PROD-03 | unit | `pytest tests/unit/test_run_store_postgres.py -x` | ❌ W0 | ⬜ pending |
| 07-01-03 | 01 | 1 | PROD-03 | unit | `pytest tests/unit/test_memo_postgres.py -x` | ❌ W0 | ⬜ pending |
| 07-01-04 | 01 | 1 | PROD-03 | unit | `pytest tests/unit/test_store_factory.py -x` | ❌ W0 | ⬜ pending |
| 07-02-01 | 02 | 2 | PROD-04 | smoke | `docker build -t test .` | ❌ W0 | ⬜ pending |
| 07-02-02 | 02 | 2 | PROD-04 | integration | `docker compose up -d && curl localhost:8000/health` | ❌ W0 | ⬜ pending |
| 07-03-01 | 03 | 2 | PROD-05 | smoke | `gh workflow run ci.yml --ref $(git branch --show-current)` | ✅ | ⬜ pending |
| 07-03-02 | 03 | 2 | PROD-05 | unit | `pytest tests/ --cov=src/agentic_workflows --cov-fail-under=80` | ❌ W0 | ⬜ pending |
| 07-04-01 | 01 | 1 | PROD-03 | integration | `pytest tests/integration/test_concurrent_postgres.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_checkpoint_postgres.py` — stubs for PROD-03 checkpoint
- [ ] `tests/unit/test_run_store_postgres.py` — stubs for PROD-03 run store
- [ ] `tests/unit/test_memo_postgres.py` — stubs for PROD-03 memo store
- [ ] `tests/unit/test_store_factory.py` — stubs for PROD-03 ENV switching
- [ ] `tests/integration/test_concurrent_postgres.py` — stubs for PROD-03 concurrency
- [ ] `pytest-cov` added to dev dependencies
- [ ] Postgres test fixtures in `tests/conftest.py` (skip if DATABASE_URL not set)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Data persists across container restart | PROD-04 | Requires Docker lifecycle | 1. `docker compose up -d` 2. POST /run 3. `docker compose restart postgres` 4. GET /runs — verify data present |
| docker-compose up starts both services | PROD-04 | Requires Docker runtime | 1. `docker compose up -d` 2. `docker compose ps` — both healthy 3. `curl localhost:8000/health` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
