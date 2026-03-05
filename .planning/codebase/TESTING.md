# Testing Patterns

**Analysis Date:** 2026-03-05

## Test Framework

**Runner:**
- `pytest` is the test runner, configured in `pyproject.toml`.
- Pytest configuration is in `[tool.pytest.ini_options]` in `pyproject.toml` with `testpaths = ["tests"]`, `pythonpath = ["src"]`, and `asyncio_mode = "auto"`.
- Current-state note: many tests are still written as `unittest.TestCase` classes and are collected by pytest, for example `tests/integration/test_langgraph_flow.py` and `tests/unit/test_mission_auditor.py`.

**Assertion Library:**
- Plain pytest assertion rewriting is widely used, for example `tests/unit/test_api_models.py` and `tests/integration/test_api_service.py`.
- `pytest.raises(...)` is used for exception assertions, for example `tests/unit/test_api_models.py` and `tests/unit/test_output_schemas.py`.
- `unittest` assertions are also present in `unittest.TestCase` suites, for example `self.assertEqual(...)` and `self.assertIn(...)` in `tests/integration/test_langgraph_flow.py`.

**Run Commands:**
```bash
pytest tests/ -q                              # Run all tests
pytest tests/unit/ -q                         # Unit tests
pytest tests/integration/ -q                  # Integration tests
pytest tests/eval/ -q                         # Eval scenarios
pytest tests/unit/test_run_store.py -q        # Single file
```

## Test File Organization

**Location:**
- Tests live in a separate `tests/` tree rather than beside source files.
- Shared fixtures live in `tests/conftest.py`; eval-specific fixtures live in `tests/eval/conftest.py`.

**Naming:**
- Unit, integration, and eval files all follow `test_<subject>.py`, for example `tests/unit/test_write_file.py`, `tests/integration/test_model_router_integration.py`, and `tests/eval/test_eval_harness.py`.
- A separate `.integration.test.py` or `.e2e.py` suffix pattern was not detected.
- Browser-style E2E test files were not detected.

**Structure:**
```text
tests/
  conftest.py
  unit/
    test_api_models.py
    test_run_store.py
    test_tool_security.py
  integration/
    test_api_service.py
    test_langgraph_flow.py
    test_model_router_integration.py
  eval/
    conftest.py
    test_eval_harness.py
```

## Test Structure

**Suite Organization:**
```python
def test_run_request_extra_field_rejected():
    with pytest.raises(ValidationError):
        RunRequest(user_input="hello", surprise="boom")


class TestWriteFileToolSecurity:
    def test_blocks_oversized_content(self, monkeypatch, tmp_path):
        monkeypatch.setenv("P1_WRITE_FILE_MAX_BYTES", "10")
        tool = WriteFileTool()
        result = tool.execute({"path": str(tmp_path / "big.txt"), "content": "x" * 100})
        assert "error" in result
```

**Patterns:**
- The suite is mixed-style: plain pytest functions, pytest classes, and `unittest.TestCase` classes all coexist.
- Arrange/act/assert is the dominant structure, usually without heavy helper abstraction.
- Shared setup is done with fixtures such as `memo_store`, `checkpoint_store`, and `tool` in `tests/conftest.py`, `tests/unit/test_run_bash.py`, and `tests/unit/test_write_file.py`.
- Cleanup uses `yield` fixtures, `TemporaryDirectory`, and explicit `.close()` calls, for example `tests/unit/test_run_store.py` and `tests/integration/test_langgraph_flow.py`.
- Async tests use either plain `async def` with global `asyncio_mode = "auto"` or explicit `@pytest.mark.asyncio`, as seen in `tests/integration/test_api_service.py` and `tests/unit/test_run_store.py`.

## Mocking

**Framework:**
- The suite favors lightweight fakes and monkeypatching over heavy mock frameworks.
- `pytest` fixtures plus `monkeypatch` are common, for example `tests/unit/test_tool_security.py` and `tests/unit/test_observability.py`.
- `unittest.mock.patch.dict` is used for environment manipulation in `tests/unit/test_provider_config.py`.

**Patterns:**
```python
class ScriptedProvider:
    def __init__(self, responses: list[dict]) -> None:
        self._responses = [json.dumps(item) for item in responses]
        self._index = 0

    def generate(self, messages):
        if self._index < len(self._responses):
            value = self._responses[self._index]
            self._index += 1
            return value
        return self._responses[-1]
```

**What to Mock:**
- LLM/provider behavior is faked with `ScriptedProvider` or inline stub providers in `tests/conftest.py`, `tests/integration/test_langgraph_flow.py`, and `tests/integration/test_model_router_integration.py`.
- Environment variables are frequently controlled with `monkeypatch.setenv()` and `monkeypatch.delenv()`, especially in `tests/unit/test_tool_security.py`.
- Filesystem and SQLite state use `tmp_path` and temporary directories rather than mocked file/database layers, for example `tests/unit/test_parse_code_structure.py` and `tests/unit/test_run_store.py`.
- HTTP integration is tested in-process with `httpx.AsyncClient` plus `httpx.ASGITransport` against a real FastAPI app in `tests/integration/test_api_service.py` and `tests/eval/conftest.py`.

**What NOT to Mock:**
- Core tool logic is usually exercised directly instead of mocked, for example `WriteFileTool` in `tests/unit/test_write_file.py` and `ParseCodeStructureTool` in `tests/unit/test_parse_code_structure.py`.
- Internal orchestration flows are typically run end-to-end with fake providers rather than mocked node methods, for example `tests/integration/test_langgraph_flow.py`.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture
def memo_store(tmp_path: Path) -> SQLiteMemoStore:
    return SQLiteMemoStore(db_path=str(tmp_path / "memo.db"))


SIMPLE_MISSION_RESPONSES = [
    {"action": "tool", "tool_name": "write_file", "args": {"path": "/tmp/eval_hello.txt", "content": "hello world"}},
    {"action": "finish", "answer": "Wrote hello world to /tmp/eval_hello.txt"},
]
```

**Location:**
- Cross-suite fixtures and the shared `ScriptedProvider` live in `tests/conftest.py`.
- Eval scenario fixtures and scripted response sequences live in `tests/eval/conftest.py`.
- One-off factories and inline provider classes are defined inside individual test files such as `tests/integration/test_langgraph_flow.py`.
- A dedicated `tests/fixtures/` or `tests/factories/` directory was not detected.

## Coverage

**Requirements:**
- No coverage target or minimum threshold was detected in `pyproject.toml` or `AGENTS.md`.
- Coverage enforcement in CI was not detected from repository-local configuration.

**Configuration:**
- A `pytest-cov` configuration or coverage config file was not detected.
- Coverage exclusions beyond ad hoc `# pragma: no cover` markers were not detected.

**View Coverage:**
```bash
Not detected
```

## Test Types

**Unit Tests:**
- Located under `tests/unit/`.
- Focus on a single tool, model, helper, or policy in isolation, for example `tests/unit/test_api_models.py`, `tests/unit/test_run_bash.py`, and `tests/unit/test_output_schemas.py`.
- Use direct object construction, temp paths, and environment patching instead of networked dependencies.

**Integration Tests:**
- Located under `tests/integration/`.
- Exercise multiple modules together, including LangGraph orchestration and FastAPI routing, for example `tests/integration/test_langgraph_flow.py` and `tests/integration/test_api_service.py`.
- Use real internal components with fake providers and temporary SQLite stores instead of live external APIs.

**E2E Tests:**
- Browser or external-system E2E tests were not detected.
- `tests/eval/` acts as deterministic scenario/eval coverage through the API rather than browser automation.

## Common Patterns

**Async Testing:**
```python
async def test_health() -> None:
    app = _build_test_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
```

**Error Testing:**
```python
with pytest.raises(ValidationError):
    RunRequest(user_input="hello", surprise="boom")

result = tool.execute({"path": ""})
assert result == {"error": "path is required"}
```

**Snapshot Testing:**
- Not detected.

*Testing analysis: 2026-03-05*
*Update when test patterns change*
