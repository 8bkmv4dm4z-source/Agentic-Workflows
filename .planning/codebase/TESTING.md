# Testing Patterns

**Analysis Date:** 2026-03-12

## Test Framework

**Runner:**
- pytest 8.0+
- Config: `pyproject.toml` `[tool.pytest.ini_options]`
- `asyncio_mode = "auto"` — all async tests run automatically without `@pytest.mark.asyncio`

**Assertion Library:**
- `unittest.TestCase` assertions (`assertEqual`, `assertIn`, `assertIsInstance`) for `unittest.TestCase` subclasses
- pytest `assert` statements for standalone pytest-style functions and classes

**Additional plugins:**
- `pytest-asyncio` 0.24+ — async test support
- `pytest-cov` 6.0+ — coverage reporting

**Run Commands:**
```bash
pytest tests/ -q                   # Run all tests
pytest tests/unit/ -q              # Unit tests only
pytest tests/integration/ -q       # Integration tests only
make test                          # All tests (via Makefile)
make test-unit                     # Unit tests only
make test-integration              # Integration tests only
```

## Test File Organization

**Location:**
- All tests in `tests/` directory at project root
- Unit tests in `tests/unit/`
- Integration tests in `tests/integration/`
- Eval harness in `tests/eval/`
- Shared fixtures in `tests/fixtures/`

**Naming:**
- All test files: `test_{module_or_feature}.py`
- One test file per source module in most cases
- Feature-specific test files: `test_phase08_6_regressions.py`, `test_context_manager_7_3.py`

**Structure:**
```
tests/
├── conftest.py                      # Shared fixtures: ScriptedProvider, memo_store, checkpoint_store, pg_pool, clean_pg
├── fixtures/
│   ├── __init__.py
│   └── sse_sequences/               # SSE event sequence fixtures
├── unit/
│   ├── __init__.py
│   └── test_*.py                    # ~95 unit test files
├── integration/
│   ├── __init__.py
│   └── test_*.py                    # ~10 integration test files
└── eval/
    ├── conftest.py
    └── test_eval_harness.py
```

## Test Structure

**Two coexisting test styles:**

1. `unittest.TestCase` subclasses (16 test files, primarily older modules):
```python
class TestActionParser(unittest.TestCase):
    def test_parse_action_json_recovers_first_object(self) -> None:
        raw = 'noise {"action":"finish","answer":"done"} trailing'
        parsed, _ = action_parser.parse_action_json(raw)
        self.assertEqual(parsed["action"], "finish")
```

2. Pytest-style plain functions and classes (preferred for newer tests):
```python
class TestTaskHandoff:
    def test_create_handoff_defaults(self) -> None:
        h = create_handoff(task_id="t1", specialist="executor", mission_id=1)
        assert h.task_id == "t1"
        assert h.tool_scope == []

def test_tool_history_has_annotated_reducer():
    """RunState.tool_history must be Annotated[list[ToolRecord], operator.add]."""
    hints = typing.get_type_hints(RunState, include_extras=True)
    hint = hints["tool_history"]
    assert hasattr(hint, "__metadata__"), "tool_history must be Annotated with reducer"
```

**Patterns:**
- Return type annotations on all test methods: `def test_foo(self) -> None:`
- Single-line docstrings in pytest-style tests describe the invariant being tested
- Comments in `unittest.TestCase` tests replace docstrings: `# Test 1: _deterministic_classify returns "simple" for 1-2 step plans`
- Guard for optional dependency (langgraph): `@unittest.skipUnless(LANGGRAPH_AVAILABLE, "langgraph not installed")`

## Mocking

**Framework:** Mix of `unittest.mock` and custom mock classes

**Custom ScriptedProvider (primary mock for LLM provider):**
```python
# Defined in tests/conftest.py — also locally redefined in integration tests
class ScriptedProvider:
    """Test provider that returns pre-scripted JSON responses."""
    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self._index = 0

    def generate(self, messages, response_schema=None):
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]  # replay last response on exhaustion
```

**Custom inline mock classes for focused tests:**
```python
class _MockProvider:
    """Minimal ChatProvider mock for intent classification tests."""
    def __init__(self, response: str | None = None, delay: float = 0.0):
        self._response = response
        self._delay = delay

    def generate(self, messages, system=None, response_schema=None) -> str:
        if self._delay > 0:
            time.sleep(self._delay)
        if self._response is None:
            raise RuntimeError("provider error")
        return self._response
```

**`unittest.mock.MagicMock` and `patch`** for FastAPI app tests:
```python
from unittest.mock import MagicMock, patch
mock_orch = MagicMock()
mock_orch.tools = {str(i): MagicMock() for i in range(5)}
with patch.object(app.router, "lifespan_context", patched_lifespan):
    ...
```

**`monkeypatch` fixture** for environment variable manipulation:
```python
def test_tool_node_constructed_for_anthropic_path(monkeypatch) -> None:
    monkeypatch.setenv("P1_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
```

**What to Mock:**
- LLM provider calls — always use `ScriptedProvider` for deterministic responses
- Environment variables — use `monkeypatch.setenv`/`monkeypatch.delenv`
- FastAPI lifespan context — patch `app.router.lifespan_context`

**What NOT to Mock:**
- Tool `execute()` methods — tools are deterministic, test them directly
- SQLite stores — use `:memory:` or `tmp_path` instead of mocking
- The graph state machine itself — use `ScriptedProvider` to drive it

## Fixtures and Factories

**Shared fixtures (`tests/conftest.py`):**
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

@pytest.fixture(scope="session")
def pg_pool():
    """Session-scoped Postgres pool. Skipped when DATABASE_URL not set."""
    ...

@pytest.fixture
def clean_pg(pg_pool):
    """Truncate all Postgres tables between tests."""
    ...
```

**Local helper factories (module-scoped, prefixed `_make_` or `_build_`):**
```python
def _make_state(run_id: str, mission_id: int = 1, goal: str = "test goal") -> dict:
    ...

def _build_test_app(responses=None, tmp_dir=None) -> FastAPI:
    ...

def _make_orchestrator(provider, *, fast_provider=None, max_steps=10) -> LangGraphOrchestrator:
    ...
```

**Instance method helpers in `unittest.TestCase` subclasses:**
```python
class IntentClassificationTests(unittest.TestCase):
    def _make_simple_plan(self) -> StructuredPlan:
        steps = [MissionStep(id="1", description="sort the numbers", suggested_tools=["sort_array"])]
        return StructuredPlan(steps=steps, flat_missions=["Task 1: sort the numbers"], parsing_method="structured")
```

**Fixtures location:**
- `tests/fixtures/sse_sequences/` — SSE event sequence data for API tests: `happy_path.py`, `error_event.py`, `reconnect.py`

## Coverage

**Configuration (`pyproject.toml`):**
```toml
[tool.coverage.run]
omit = [
    "src/agentic_workflows/core/main.py",       # Legacy P0 baseline
    "src/agentic_workflows/core/orchestrator.py",
    "src/agentic_workflows/agents/local_agent.py",
    "src/agentic_workflows/orchestration/langgraph/user_run.py",  # Interactive TTY
    "src/agentic_workflows/orchestration/langgraph/run.py",
    "src/agentic_workflows/cli/user_run.py",
]
```

**Requirements:** No numeric coverage threshold enforced. 657 tests passing (all unit + integration).

**View Coverage:**
```bash
pytest tests/ --cov=src/ --cov-report=term-missing
```

## Test Types

**Unit Tests (`tests/unit/`):**
- Test individual functions, classes, and modules in isolation
- Use `:memory:` SQLite or `tmp_path` for storage
- No live LLM calls — use `ScriptedProvider` or `_MockProvider`
- Parametrized contract tests for all registered tools via `pytest.mark.parametrize`

**Integration Tests (`tests/integration/`):**
- Test full graph execution flows with `LangGraphOrchestrator` + `ScriptedProvider`
- Test HTTP contracts via `httpx.AsyncClient` with `ASGITransport` against real FastAPI app
- Postgres tests gated by `requires_postgres` marker (skip when `DATABASE_URL` not set)

**Postgres guard pattern:**
```python
requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set -- skipping Postgres tests",
)

@requires_postgres
class TestConcurrentPostgres(unittest.IsolatedAsyncioTestCase):
    ...
```

**Eval Tests (`tests/eval/`):**
- Separate eval harness with its own `conftest.py`
- Not part of the standard `make test` run

## Common Patterns

**Async Testing:**
```python
# asyncio_mode = "auto" means no decorator needed
async def test_health() -> None:
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
```

**Error/Exception Testing:**
```python
# Pydantic validation
def test_handoff_extra_field_raises(self) -> None:
    with pytest.raises(ValidationError):
        TaskHandoff(..., unexpected_extra="x")

# Value error with match
with pytest.raises(ValueError, match="schema mismatch"):
    ...

# unittest style
def test_something(self) -> None:
    with self.assertRaises(SomeError):
        ...
```

**Log assertion testing:**
```python
def test_fallback_emits_warning(self, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="langgraph.action_parser"):
        action_parser.parse_action_json(raw, step=3)
    assert any("PARSER FALLBACK" in r.message for r in caplog.records)
```

**Parametrized tests:**
```python
_ALL_TOOLS = list(_build_all_tools().items())

@pytest.mark.parametrize("tool_name,tool", _ALL_TOOLS, ids=[t[0] for t in _ALL_TOOLS])
def test_tool_has_name(tool_name, tool):
    assert isinstance(tool.name, str) and len(tool.name) > 0
```

**State dict construction for graph tests:**
```python
state = {"messages": msgs, "policy_flags": {}, "step": 0}
cm.compact(state)
assert len(state["messages"]) <= 40
```

**ScriptedProvider-driven orchestrator tests:**
```python
responses = [
    {"action": "tool", "tool_name": "sort_array", "args": {"items": [3, 1, 2]}},
    {"action": "finish", "answer": "Sorted."},
]
provider = ScriptedProvider(responses=responses)
orch = LangGraphOrchestrator(provider=provider, max_steps=10)
result = orch.run(user_input="Sort [3,1,2]")
assert result["answer"] == "Sorted."
```

---

*Testing analysis: 2026-03-12*
