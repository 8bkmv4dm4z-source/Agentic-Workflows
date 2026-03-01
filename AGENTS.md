# AGENTS.md

## 1. Commands
```bash
pip install -e ".[dev]"                                          # build
pytest tests/ -q                                                 # all tests
pytest tests/unit/ -q                                            # unit only
pytest tests/integration/ -q                                     # integration
ruff check src/ tests/                                           # lint
ruff format src/ tests/                                          # format
mypy src/                                                        # typecheck
python -m agentic_workflows.orchestration.langgraph.run          # run demo
python -m agentic_workflows.orchestration.langgraph.run_audit    # audit
```

## 2. Architecture
3-layer model:
- **Directive** (`directives/`) -- SOPs defining goals, inputs, outputs, edge cases
- **Orchestration** (`orchestration/`) -- LangGraph state machines, retries, recovery
- **Execution** (`tools/`) -- Deterministic Python, same input = same output

Graph node flow: `plan -> execute -> policy -> finalize`

Key abstractions:
- `RunState` (TypedDict) -- Typed state flowing through graph nodes
- `ChatProvider` (Protocol) -- Unified provider contract (`generate -> JSON`)
- `Tool` (base class) -- Tool interface (`name`, `description`, `execute`)
- `MemoizationPolicy` -- Enforces memo-before-write invariant
- `StructuredPlan` -- Hierarchical mission decomposition

## 3. Testing
- pytest for all tests (not unittest)
- Tests mirror src/ layout: `tests/unit/`, `tests/integration/`
- Integration tests use `ScriptedProvider` (no live API calls in CI)
- `conftest.py` provides shared fixtures (temp dirs, memo stores, providers)
- Every bug fix includes a regression test

## 4. Code Style
- Python 3.12+, type hints on all public APIs
- Pydantic v2 for data models (`ConfigDict`, not `class Config`)
- Ruff for lint + format (config in `pyproject.toml`)
- No bare `except`; specific exception types only
- Import order: stdlib, third-party, local (isort via ruff)
- Max line length: 100

## 5. Git Workflow
- Branch: `type/description` (`feat/add-langfuse`, `fix/memo-policy`)
- Commits: imperative mood, <72 char subject
- One logical change per PR
- Pre-commit hooks: ruff check, ruff format
- Never commit: `.env`, `*.db`, `.tmp/`, `__pycache__/`

## 6. Boundaries
- LLM calls only in `orchestration/` layer
- Tools are deterministic: no LLM calls in `tools/`
- Config via env vars (`.env`), never hardcoded
- New tools must extend `Tool` base class
- Heavy writes require memoize call (policy enforced)
- Phase isolation: P0 `core/` and P1 `orchestration/` do not cross-import
