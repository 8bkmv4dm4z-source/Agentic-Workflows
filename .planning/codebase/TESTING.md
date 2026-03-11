# Testing Patterns

**Analysis Date:** 2026-03-12

## Test Framework

**Runner:**
- pytest 8.x
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`
- `testpaths = ["tests"]`, `pythonpath = ["src"]`

**Async mode:**
- `asyncio_mode = "auto"` — all `async def test_` functions run automatically without `@pytest.mark.asyncio`
- `pytest-asyncio >= 0.24` required

**Assertion Library:**
- pytest native `assert` for most tests
- `unittest.TestCase` with `self.assertEqual`, `self.assertTrue`, `self.assertFalse` in older test files

**Coverage:**
- `pytest-cov >= 6.0`
- Coverage omits legacy P0 baseline, interactive CLI scripts (see `[tool.coverage.run]` in `pyproject.toml`)

**Run Commands:**
```bash
make test                     # pytest with coverage (all tests)
pytest tests/ -q              # all tests, quiet
pytest tests/unit/ -q         # unit only
pytest tests/integration/ -q  # integration only
pytest -m "not postgres"      # skip Postgres-gated tests
```

## Test File Organization

**Location:**
- Separate `tests/` directory at repo root (not co-located with source)
- `tests/unit/` — pure unit tests (no live providers, no live DBs)
- `tests/integration/` — orchestration end-to-end with ScriptedProvider, API contract tests
- `tests/eval/` — SSE/API eval harness with AsyncClient + ASGITransport
- `tests/fixtures/` — SSE sequence fixtures (static data for fixture injection)

**Naming:**
- `test_{module_or_feature}.py` — mirrors source module name: `test_action_parser.py`, `test_mission_auditor.py`
- Feature-scoped: `test_context_manager_7_3.py`, `test_phase08_6_regressions.py`
- Contract tests: `test_tool_contracts.py`, `test_schema_compliance.py`

**Structure:**
```
tests/
├── conftest.py                    # Shared fixtures: ScriptedProvider, memo_store, checkpoint_store, pg_pool
├── unit/                          # ~100 test files; pure pytest + some unittest.TestCase
├── integration/                   # ~10 test files; ScriptedProvider + httpx AsyncClient
├── eval/                          # eval harness (async, SSE-oriented)
│   └── conftest.py
└── fixtures/
    └── sse_sequences/             # Static SSE event sequences for fixture use
```

## Test Structure

**Pure pytest style (preferred for new tests):**
```python
"""Unit tests for mission_auditor.py — each check type covered."""
from __future__ import annotations

import pytest
from agentic_workflows.orchestration.langgraph.mission_auditor import _check_tool_presence

def test_no_warning_when_tool_used() -> None:
    findings = _check_tool_presence(1, "Sort the array", ["sort_array"])
    assert not any(f.level == "warn" for f in findings)

def test_warn_when_tool_missing() -> None:
    findings = _check_tool_presence(1, "Sort the array", [])
    assert any(f.check == "tool_presence" and f.level == "warn" for f in findings)
```

**unittest.TestCase style (in older files):**
```python
class TestActionParser(unittest.TestCase):
    def test_parse_action_json_recovers_first_object(self) -> None:
        raw = 'noise {"action":"finish","answer":"done"} trailing'
        parsed, _ = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["action"], "finish")
```

**Class grouping without unittest.TestCase (common in newer tests):**
```python
class TestTaskHandoff:
    def test_create_handoff_defaults(self) -> None:
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        assert h.task_id == "t1"

class TestHandoffResult:
    def test_create_result_defaults(self) -> None:
        r = create_handoff_result(task_id="t1", specialist="executor")
        assert r.status == "success"
```

**Section separators:** Used consistently within large test files:
```python
# ---------------------------------------------------------------------------
# _check_tool_presence
# ---------------------------------------------------------------------------
```

## Mocking

**Frameworks:**
- `unittest.mock.MagicMock` and `patch` for interface mocking
- `pytest.monkeypatch` (preferred for env vars, cwd, module attributes)
- `ScriptedProvider` (custom — in `tests/conftest.py`) for LLM provider mocking

**ScriptedProvider pattern** — the primary integration mocking strategy:
```python
class ScriptedProvider:
    """Test provider that returns pre-scripted JSON responses."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self._index = 0

    def context_size(self) -> int:
        return 32768

    def generate(self, messages, response_schema=None):
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]  # replay last response indefinitely
```

**MagicMock for dependency injection:**
```python
mock_orch = MagicMock()
mock_orch.tools = {str(i): MagicMock() for i in range(5)}
mock_run_store = MagicMock()
mock_run_store.close = MagicMock()
```

**monkeypatch for env var control:**
```python
def test_inactive_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("P1_TOOL_SANDBOX_ROOT", raising=False)
    assert validate_path_within_sandbox("/any/path") is None
```

**What to Mock:**
- LLM provider calls — always via `ScriptedProvider`
- Environment variables — always via `monkeypatch.setenv/delenv`
- FastAPI orchestrator state — via `MagicMock()` injected into `app.state`
- External databases — via SQLite in-memory (`:memory:`) or `tmp_path`

**What NOT to Mock:**
- Tool `execute()` methods — tested with real implementations
- SQLite storage — use in-memory or `tmp_path` instead of mocking
- Pydantic schema validation — always tested against real models

## Fixtures and Factories

**Shared fixtures** in `tests/conftest.py`:
```python
@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    return tmp_path

@pytest.fixture
def memo_store(tmp_path: Path) -> SQLiteMemoStore:
    return SQLiteMemoStore(db_path=str(tmp_path / "memo.db"))

@pytest.fixture
def checkpoint_store(tmp_path: Path) -> SQLiteCheckpointStore:
    return SQLiteCheckpointStore(db_path=str(tmp_path / "checkpoints.db"))
```

**Postgres fixtures** in `tests/conftest.py` — guarded by `DATABASE_URL`:
```python
@pytest.fixture(scope="session")
def pg_pool():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("DATABASE_URL not set")
    # ... opens psycopg ConnectionPool, runs migrations, yields pool
```

**State factory for orchestration tests:**
```python
def _make_state(self) -> dict:
    from agentic_workflows.orchestration.langgraph.state_schema import new_run_state
    state = new_run_state("system", "test input")
    state["missions"] = ["test mission"]
    # ... populate required mission_reports fields
    return state
```

**Orchestrator builder pattern (integration tests):**
```python
def _make_orch(responses, checkpoint_store=None, memo_store=None) -> LangGraphOrchestrator:
    provider = ScriptedProvider(responses=responses)
    return LangGraphOrchestrator(provider=provider, max_steps=20, ...)
```

**FastAPI app builder pattern:**
```python
def _build_test_app(responses=None, tmp_dir=None) -> FastAPI:
    # Bypass lifespan — set app.state directly
    test_app.state.orchestrator = orchestrator
    test_app.state.run_store = run_store
    test_app.state.active_streams = {}
    return test_app
```

**Location:** All shared fixtures in `tests/conftest.py`. Eval-specific fixtures in `tests/eval/conftest.py`.

## Coverage

**Requirements:** No enforced minimum threshold in config.

**Excluded from coverage** (`[tool.coverage.run]` omit list):
- `src/agentic_workflows/core/main.py` — legacy P0 baseline
- `src/agentic_workflows/core/orchestrator.py` — legacy P0 baseline
- `src/agentic_workflows/agents/local_agent.py` — legacy P0 baseline
- `src/agentic_workflows/orchestration/langgraph/user_run.py` — interactive CLI
- `src/agentic_workflows/orchestration/langgraph/run.py` — interactive CLI
- `src/agentic_workflows/cli/user_run.py` — interactive CLI

**View Coverage:**
```bash
pytest tests/ --cov=src/agentic_workflows --cov-report=html
```

## Test Types

**Unit Tests** (`tests/unit/`):
- ~1,200+ test functions across ~100 files
- Test individual functions/classes in isolation
- No live LLM calls; no live network; SQLite in-memory or `tmp_path`
- Cover tools, parsers, state schema, storage, auditor, provider, API app structure

**Integration Tests** (`tests/integration/`):
- Use `ScriptedProvider` for full orchestrator runs without live LLM
- Use `httpx.AsyncClient` with `ASGITransport` for FastAPI HTTP contract tests
- PostgreSQL tests gated by `@pytest.mark.postgres` and `requires_postgres` (skipif `DATABASE_URL` unset)
- Test multi-mission flows, checkpoint replay, SSE streaming, concurrent writes

**Eval Tests** (`tests/eval/`):
- Async FastAPI end-to-end via SSE event parsing
- Uses `ScriptedProvider` for deterministic agent behavior
- Verify SSE event types (`run_complete`), run status via `GET /run/{id}`

**Parametrized Contract Tests** (`tests/unit/test_tool_contracts.py`):
```python
_ALL_TOOLS = list(_build_all_tools().items())

@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_has_name(tool_name, tool):
    assert isinstance(tool.name, str) and len(tool.name) > 0
```
- Every registered tool tested against `name`, `description`, `execute()`, `args_schema` contracts

## Postgres-Gated Tests

**Pattern for optional infrastructure tests:**
```python
requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)

@requires_postgres
@pytest.mark.postgres
def test_concurrent_save_run(self, pg_pool, clean_pg):
    ...
```

**`clean_pg` fixture** truncates all tables between tests for isolation:
```python
@pytest.fixture
def clean_pg(pg_pool):
    with pg_pool.connection() as conn:
        conn.execute("TRUNCATE graph_checkpoints, runs, memo_entries")
    yield
```

## Common Patterns

**Async Testing (API):**
```python
async def test_health() -> None:
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
```

**Error Testing (Pydantic):**
```python
def test_handoff_extra_field_raises(self) -> None:
    with pytest.raises(ValidationError):
        TaskHandoff(..., unexpected_extra="x")
```

**Log Capture:**
```python
def test_fallback_emits_warning(self, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="langgraph.action_parser"):
        action_parser.parse_action_json(raw, step=3)
    assert any("PARSER FALLBACK" in r.message for r in caplog.records)
```

**Return-tuple Testing:**
```python
def test_fallback_returns_true_flag(self) -> None:
    raw = 'noise {"action":"finish","answer":"done"}'
    _, used_fallback = action_parser.parse_action_json(raw, step=0)
    assert used_fallback is True
```

**Tool Result Dict Testing:**
```python
def test_write_file_sh_no_shebang(tool):
    result = tool.execute({"path": "script.sh", "content": "echo hello\n"})
    assert "error" in result
    assert "write_file_guardrail" in result["error"]
    assert "hint" in result
```

---

*Testing analysis: 2026-03-12*
