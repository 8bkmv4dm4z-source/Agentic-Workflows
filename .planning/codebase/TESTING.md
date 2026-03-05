# Testing Patterns

**Analysis Date:** 2026-03-05

## Test Framework

**Runner:**
- `pytest>=8.0` with `pytest-asyncio>=0.24`, configured in `pyproject.toml`.
- Global pytest config lives in `pyproject.toml` with `testpaths = ["tests"]`, `pythonpath = ["src"]`, and `asyncio_mode = "auto"`.
- CI runs `pytest tests/ -q` in `.github/workflows/ci.yml`.
- Current state mixes pytest-style tests with `unittest.TestCase` suites collected by pytest (`tests/unit/test_mission_parser.py`, `tests/integration/test_langgraph_flow.py`) even though `AGENTS.md` prefers pytest over raw unittest execution.

**Assertion Library:**
- Primary assertion style is plain Python `assert` plus `pytest.raises(...)` (`tests/unit/test_api_models.py`, `tests/unit/test_run_store.py`, `tests/unit/test_tool_security.py`).
- Legacy/class-based suites use `unittest.TestCase` assertion helpers such as `self.assertEqual`, `self.assertIn`, and `self.assertLess` (`tests/unit/test_mission_parser.py`, `tests/integration/test_langgraph_flow.py`).
- Custom matcher libraries: Not detected.

**Run Commands:**
```bash
pip install -e ".[dev]"                # install dev/test dependencies
pytest tests/ -q                       # run all tests
pytest tests/unit/ -q                  # unit tests
pytest tests/integration/ -q           # integration tests
pytest tests/eval/ -q                  # eval scenarios
pytest tests/unit/test_run_store.py -q # single file pattern
```

## Test File Organization

**Location:**
- Tests live in a separate `tests/` tree, not alongside `src/`.
- Shared fixtures live in `tests/conftest.py`.
- Eval-only fixtures live in `tests/eval/conftest.py`.
- Tests are split by intent into `tests/unit/`, `tests/integration/`, and `tests/eval/`.

**Naming:**
- All current test files use the `test_*.py` naming pattern (`tests/unit/test_logger.py`, `tests/integration/test_api_service.py`, `tests/eval/test_eval_harness.py`).
- Unit vs. integration is communicated by directory, not by suffix such as `.integration.py`.
- Browser/E2E-specific filename convention: Not detected.

**Structure:**
```text
tests/
  conftest.py
  unit/
    test_run_store.py
    test_tool_security.py
    test_mission_parser.py
  integration/
    test_api_service.py
    test_langgraph_flow.py
    test_multi_mission_subgraph.py
  eval/
    conftest.py
    test_eval_harness.py
```

## Test Structure

**Suite Organization:**
```python
def test_save_and_get_run(store):
    ...


class MissionParserTests(unittest.TestCase):
    def test_numbered_tasks_basic(self) -> None:
        ...
```

**Patterns:**
- The suite uses both function-based pytest tests and class-based `unittest.TestCase` containers, often in the same subsystem.
- Setup is fixture-heavy: `@pytest.fixture`, `tmp_path`, `monkeypatch`, and app/client builders are standard (`tests/conftest.py`, `tests/unit/test_run_bash.py`, `tests/eval/conftest.py`).
- Teardown is handled with `yield` fixtures, context managers, and explicit cleanup helpers (`tests/unit/test_run_store.py`, `tests/unit/test_logger.py`, `tests/integration/test_api_service.py`).
- Tests usually follow arrange/act/assert flow, but that structure is implicit rather than enforced with section comments.
- Async tests are plain `async def` under `asyncio_mode=auto`; some files still add `@pytest.mark.asyncio` explicitly (`tests/unit/test_run_store.py`).

## Mocking

**Framework:**
- The dominant pattern is lightweight fakes plus pytest `monkeypatch`, not a central mocking framework.
- Import-level mocking via `unittest.mock.patch(...)`: Not detected as a common repo-wide pattern.

**Patterns:**
```python
class ScriptedProvider:
    def generate(self, messages):
        return ...


monkeypatch.setenv("P1_TOOL_SANDBOX_ROOT", str(tmp_path))
monkeypatch.chdir(tmp_path)
```

**What to Mock:**
- LLM/provider behavior is replaced with deterministic fakes such as `ScriptedProvider` in `tests/conftest.py` and inline provider doubles in `tests/integration/test_langgraph_flow.py`.
- Environment variables and feature flags are controlled with `monkeypatch.setenv()` / `monkeypatch.delenv()` (`tests/unit/test_tool_security.py`, `tests/unit/test_state_schema.py`, `tests/unit/test_observability.py`).
- Filesystem state is isolated through `tmp_path` and `TemporaryDirectory()` (`tests/unit/test_parse_code_structure.py`, `tests/integration/test_langgraph_flow.py`).
- HTTP integration tests use a real FastAPI app plus `httpx.AsyncClient` with `httpx.ASGITransport`, so network calls are avoided without mocking the route layer (`tests/integration/test_api_service.py`, `tests/eval/conftest.py`).

**What NOT to Mock:**
- Internal route wiring, orchestrator flow, and SQLite behavior are exercised with real objects in integration tests (`tests/integration/test_api_service.py`, `tests/integration/test_multi_mission_subgraph.py`, `tests/unit/test_run_store.py`).
- Pure helper logic is usually tested directly without stubbing intermediate functions.
- Live provider API calls in tests/CI: Not applicable. `.github/workflows/ci.yml` sets `P1_PROVIDER=scripted`.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def memo_store(tmp_path):
    return SQLiteMemoStore(db_path=str(tmp_path / "memo.db"))


def _build_test_app(responses=None, tmp_dir=None):
    ...
```

**Location:**
- Shared cross-suite fixtures live in `tests/conftest.py` (`tmp_dir`, `memo_store`, `checkpoint_store`, `ScriptedProvider`).
- Scenario builders and client fixtures for eval runs live in `tests/eval/conftest.py` (`simple_app`, `multi_app`, `chain_app`, and matching clients).
- File-local fixtures are common for tools/stores (`tests/unit/test_run_bash.py`, `tests/unit/test_parse_code_structure.py`, `tests/unit/test_run_store.py`).
- A dedicated `tests/factories/` or `tests/fixtures/` directory: Not detected.

## Coverage

**Requirements:**
- Numeric coverage target: Not detected.
- Coverage gating in CI: Not detected.

**Configuration:**
- CI enforces lint, typecheck, and full test pass in `.github/workflows/ci.yml`.
- Coverage plugin/configuration in `pyproject.toml`: Not detected.
- Coverage exclusions config: Not detected.

**View Coverage:**
```bash
# Not detected: no coverage command or report path is configured in current repo files
```

## Test Types

**Unit Tests:**
- Scope: single tool, model, helper, or store behavior in isolation (`tests/unit/test_write_file.py`, `tests/unit/test_api_models.py`, `tests/unit/test_run_store.py`).
- Mocking: heavy use of temp dirs, env patching, and fake providers; dependencies are kept local and deterministic.
- Speed/strict runtime budget: Not detected.

**Integration Tests:**
- Scope: multiple modules wired together, especially orchestration flow and HTTP API behavior (`tests/integration/test_api_service.py`, `tests/integration/test_langgraph_flow.py`, `tests/integration/test_multi_mission_subgraph.py`).
- Mocking: external providers are scripted, but internal routers, orchestrator objects, and SQLite stores are real.
- Setup: test apps often bypass FastAPI lifespan intentionally because `httpx.ASGITransport` does not trigger it; state is assigned directly on `app.state` (`tests/integration/test_api_service.py`, `tests/eval/conftest.py`).

**E2E / Eval Tests:**
- End-to-end API scenarios live in `tests/eval/test_eval_harness.py`, backed by fixtures from `tests/eval/conftest.py`.
- These tests validate POST `/run` SSE output plus follow-up GET `/run/{id}` status retrieval through deterministic scripted responses.
- Browser/UI automation framework: Not detected.

## Common Patterns

**Async Testing:**
```python
async with httpx.AsyncClient(
    transport=httpx.ASGITransport(app=app), base_url="http://test"
) as client:
    resp = await client.get("/health")
```
- This pattern is used in `tests/integration/test_api_service.py` and `tests/eval/test_eval_harness.py`.

**Error Testing:**
```python
with pytest.raises(ValidationError):
    RunRequest(user_input="hello", surprise="boom")

result = tool.execute({"command": ""})
assert result == {"error": "command is required"}
```
- Structured error-dict assertions are common for tools (`tests/unit/test_run_bash.py`, `tests/unit/test_tool_security.py`).
- Exception assertions are used mainly for model validation or true exceptional control flow (`tests/unit/test_api_models.py`, `tests/unit/test_output_schemas.py`).

**Snapshot Testing:**
- Snapshot testing: Not detected.
- Golden-file fixture directories: Not detected.

*Testing analysis: 2026-03-05*
*Update when test patterns change*
