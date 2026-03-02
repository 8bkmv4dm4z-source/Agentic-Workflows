# Directives Guide

This folder defines role and SOP contracts for the orchestration layer.
Treat these files as behavioral specifications for planning, execution, and evaluation.

## Files

- `phase1_langgraph.md`:
  - End-to-end Phase 1 SOP (inputs, outputs, policy, run/debug workflow).
- `supervisor.md`:
  - Planning and lifecycle contract for mission routing and finish gating.
- `executor.md`:
  - Deterministic tool execution contract and argument/result invariants.
- `evaluator.md`:
  - Post-run audit contract and quality/finding rules.

## How Directives Are Used

Current runtime behavior:

- `LangGraphOrchestrator` currently assembles a strict system prompt in code
  (`orchestration/langgraph/graph.py::_build_system_prompt`).
- Directive markdown is not auto-loaded at runtime yet.

Practical usage today:

- Design and review source-of-truth for expected node behavior.
- Implementation checklist when changing orchestration logic.
- Prompt material for future specialist/subgraph orchestration.

## Applying a Directive During Development

1. Update the relevant directive contract first (or in the same PR).
2. Implement code changes in `orchestration/langgraph/` or `tools/`.
3. Add/adjust regression tests for the changed behavior.
4. Confirm contract-language still matches actual state keys and retry rules.

## Optional Prompt Composition Pattern

If you want to experiment with role-specific prompts, load directive text explicitly and inject
it into node-local prompt builders.

```python
from pathlib import Path

directive_dir = Path("src/agentic_workflows/directives")
supervisor_contract = (directive_dir / "supervisor.md").read_text(encoding="utf-8")
executor_contract = (directive_dir / "executor.md").read_text(encoding="utf-8")
```

Keep this deterministic and versioned; avoid hidden prompt sources.
