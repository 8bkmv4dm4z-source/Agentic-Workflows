# Phase 1 -- Foundation Cleanup

**Duration:** Week 1-2
**Prerequisites:** None
**Status:** In Progress

## Goal
Transform the prototype repo into a properly packaged, testable, lintable Python project with observability hooks.

## Sub-phases

### 1A: Package & Build
- [x] Create `pyproject.toml` with setuptools, ruff, pytest, mypy config
- [x] `pip install -e ".[dev]"` works

### 1B: Restructure
- [x] Create `src/agentic_workflows/` package tree
- [x] Move all modules (core, orchestration, tools, directives)
- [x] Fix all imports (25+ files)
- [x] Verify 94 tests pass under new structure

### 1C: Cleanup
- [x] Delete `fib.txt` artifacts
- [x] Delete `p2/` ghost directory
- [x] Delete `package.json`, `package-lock.json`
- [x] Delete duplicate `test/` directory
- [x] Add MIT `LICENSE`
- [x] Consolidate tests into `unit/` and `integration/`
- [x] Create `tests/conftest.py` with shared fixtures

### 1D: Tooling
- [x] Create `Makefile` (run, test, lint, format, typecheck, audit)
- [x] Create `.pre-commit-config.yaml` (ruff check + format)
- [x] Create `.github/workflows/claude.yml` (Claude Code Action)
- [x] Create `.env.example`
- [x] Update `.gitignore`

### 1E: Documentation
- [x] Rewrite `CLAUDE.md` (What/Why/How, <150 lines)
- [x] Rewrite `AGENTS.md` (6 areas, no duplication with CLAUDE.md)
- [ ] Update `README.md` with setup instructions

### 1F: Observability
- [x] Create `src/agentic_workflows/observability.py` (Langfuse)
- [ ] Add `@observe()` to orchestrator `run()` and provider `generate()`
- [ ] Verify Langfuse traces for demo run (if configured)

## Industry Tools
- setuptools (packaging)
- ruff (lint + format)
- pytest (testing)
- mypy (type checking)
- Langfuse (observability)
- pre-commit (git hooks)

## Acceptance Criteria
- [x] `pip install -e .` works
- [x] All 94+ tests pass under new structure
- [ ] `ruff check` clean
- [ ] Langfuse traces visible for demo run (if configured)
- [x] `CLAUDE.md` < 150 lines
- [x] No content duplication between `CLAUDE.md` and `AGENTS.md`

## Risks
| Risk | Severity | Mitigation |
|------|----------|------------|
| Import breakage during restructure | High | Copy-then-delete approach; run tests after each batch |
| `provider.py` ROOT_DIR path depth change | Medium | Update `parents[N]` count |
| Notebook `sys.path` hacks break | Medium | Update notebook bootstrap cells after restructure |
