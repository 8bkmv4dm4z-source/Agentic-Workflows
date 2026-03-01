# CLAUDE.md

## What
Agentic Workflows -- a graph-based multi-agent orchestration platform.
Python 3.12 | LangGraph | Pydantic 2.12 | Anthropic/OpenAI/Groq providers | SQLite (dev)

## Why
Production-grade agentic AI engineering portfolio: plan-and-execute orchestration,
typed schemas, eval-driven development, cost-aware model routing, and observability.

## How

### Setup
```bash
pip install -e ".[dev]"       # install with dev tools
cp .env.example .env          # configure provider keys
```

### Run
```bash
make run                      # main agent demo
make test                     # pytest with coverage
make lint                     # ruff check
make format                   # ruff format
make typecheck                # mypy
```

### Key Commands
```bash
python -m agentic_workflows.orchestration.langgraph.run        # demo
python -m agentic_workflows.orchestration.langgraph.run_audit  # audit
pytest tests/ -q                                               # all tests
pytest tests/unit/ -q                                          # unit only
pytest tests/integration/ -q                                   # integration
```

### Project Structure
```
src/agentic_workflows/
  __init__.py
  schemas.py       -- Pydantic ToolAction/FinishAction
  errors.py        -- Exception hierarchy
  logger.py        -- Structured logging
  core/            -- P0 baseline agent
  orchestration/   -- LangGraph graphs, state, providers, checkpoints
    langgraph/     -- graph.py, state_schema.py, provider.py, ...
  tools/           -- 12 tool implementations (deterministic, no LLM calls)
  directives/      -- Agent SOPs and instruction templates
tests/
  conftest.py      -- Shared fixtures
  unit/            -- Unit tests
  integration/     -- Integration tests (ScriptedProvider, no live API)
```

### Environment
Set `P1_PROVIDER` (`ollama` | `groq` | `openai`) plus provider-specific keys.
See `.env.example` for all variables.

| Provider | Keys | Default model |
|----------|------|---------------|
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` | gpt-4.1-mini |
| Groq | `GROQ_API_KEY`, `GROQ_MODEL` | llama-3.1-8b-instant |
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | llama3.1:8b |

Tuning: `P1_PROVIDER_TIMEOUT_SECONDS` (30), `P1_PLAN_CALL_TIMEOUT_SECONDS` (45)

### Conventions
- Default to highest implemented phase unless user says otherwise
- Check existing tools before creating new ones
- Never overwrite directives without explicit user request
- Operational learnings go in `P1_WALKTHROUGH.md`

### Context Load Order
1. `ProjectCompass.md` -- roadmap and target architecture
2. `AGENTS.md` -- universal coding conventions
3. `P1_WALKTHROUGH.md` -- current phase architecture and known bugs
4. `directives/phase1_langgraph.md` -- Phase 1 SOP

### Known Constraints
- JSON contract violations: some providers emit XML-ish tool-call envelopes;
  parser recovers first balanced JSON object, non-JSON payloads retry then fail-closed
- Memoization policy: heavy deterministic writes require a `memoize` call
- Timeout mode: after planner timeout, deterministic fallback actions only
- Duplicate protection: exact duplicate tool calls blocked via `seen_tool_signatures`
