# agent_phase0

Graph-based agentic workflows project using a deterministic tool layer and LangGraph orchestration.

## Quick start

```bash
pip install -e ".[dev]"
pytest tests/ -q
python -m agentic_workflows.orchestration.langgraph.run
```

## Package docs

- `src/agentic_workflows/README.md` - package architecture and runtime flow
- `src/agentic_workflows/directives/README.md` - directive catalog and usage guide

## Runtime artifacts

Demo/audit runs can generate local artifacts. These are treated as ephemeral and are ignored in git:

- `lastRun.txt`
- `analysis_results.txt`
- `pattern_report.txt`
- `users_sorted.txt`
- `fib*.txt`

Prefer using `.tmp/` or `tests/fixtures/` for reusable samples.
