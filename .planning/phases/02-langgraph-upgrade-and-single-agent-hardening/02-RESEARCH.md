# Phase 2: LangGraph Upgrade and Single-Agent Hardening - Research

**Researched:** 2026-03-02
**Domain:** LangGraph 1.0 upgrade, ToolNode/tools_condition, Annotated reducers, message compaction, Langfuse @observe(), GitHub Actions CI
**Confidence:** HIGH (decisions are locked in CONTEXT.md; code is inspected directly)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Provider Migration Strategy**
- Keep `ChatProvider` protocol and `ScriptedProvider` in place — they are the test safety net for all 208 existing tests and must not be removed
- Add `langchain-anthropic` as a parallel path alongside `ChatProvider`, not a replacement
- `ScriptedProvider` remains the default for all tests; no live LLM calls in the test suite
- The XML/JSON envelope parser in `graph.py` can be retired only for the Anthropic path once `ToolNode` is confirmed working

**ToolNode Scope**
- Anthropic path first — wire `langchain-anthropic` + `ToolNode` for the Anthropic provider only in Phase 2
- OpenAI and Groq provider paths stay on the existing `ChatProvider` pattern for now
- Ollama (primary dev provider) stays on existing pattern — Ollama does not need langchain-anthropic
- Rationale: one migration at a time; Anthropic path has the most parser fragility

**RunState Reducers**
- All four plain list fields must get `Annotated[list[T], operator.add]` reducers: `tool_history`, `mission_reports`, `memo_events`, `seen_tool_signatures`
- `ensure_state_defaults()` must remain — it repairs state at each node entry and is independent of reducer annotations
- Add an integration test that asserts no branch results are dropped after a two-branch merge
- Existing sequential tests must pass unchanged after reducer annotations are added

**Message Compaction**
- Sliding window / drop oldest — when `messages` list exceeds 40 entries, drop the oldest messages to bring it back to the threshold
- No LLM summarization (adds latency and a live-LLM dependency in what should be deterministic state management)
- Threshold is configurable via env var `P1_MESSAGE_COMPACTION_THRESHOLD` (default 40)
- Compaction fires at node entry in `ensure_state_defaults()` so it is automatic and centralized

**Observability Wiring**
- `@observe()` decorator goes on `run()` in `run.py` and `generate()` in `provider.py`
- The existing `observability.py` graceful-degradation stub is already correct — just wire the decorator
- Langfuse `CallbackHandler` is Phase 5 (graph-level tracing); Phase 2 only closes the open `@observe()` item
- No Langfuse account required in CI — graceful degradation means it's a no-op when `LANGFUSE_PUBLIC_KEY` is absent

**ADR Log**
- Location: `docs/ADR/` directory, one file per decision
- Format: simple markdown with sections: **Status**, **Context**, **Decision**, **Consequences**
- First ADR: `ADR-001-langgraph-version-upgrade.md` documenting the `<1.0` pin removal
- Each subsequent significant architectural decision in Phase 2 gets its own ADR

**CI Pipeline**
- Full suite gate: `ruff check src/ tests/` + `mypy src/` + `pytest tests/ -q` — all three must pass
- Uses `ScriptedProvider` — zero live LLM calls, no provider API keys required in CI secrets
- Trigger: push to any branch + pull request to `main`
- File: `.github/workflows/ci.yml` (separate from existing `claude.yml`)
- Python version: 3.12 (matches dev environment)
- No caching in v1 — keep it simple, add pip cache in Phase 7

**LangGraph Upgrade Safety**
- Set `handle_tool_errors=True` explicitly when constructing `ToolNode` (langgraph-prebuilt >=1.0.1 disables this by default — GitHub Issue #6486)
- Pin to `langgraph==1.0.6, langgraph-prebuilt==1.0.1` initially (stable combination confirmed in research), then move to latest after 208 tests pass
- `seen_tool_signatures` deduplication logic must be preserved — `ToolNode` has no built-in deduplication

### Claude's Discretion

All implementation areas delegated to Claude based on research findings. Constraints above are hard requirements; everything else is Claude's call.

### Deferred Ideas (OUT OF SCOPE)

- Langfuse `CallbackHandler` for graph-level node tracing — Phase 5
- OpenAI and Groq provider paths to `ToolNode` — future phase
- Human-in-the-loop `interrupt()` API — v2 requirements
- Parallel mission `Send()` map-reduce — Phase 4 (after reducers are in place)
- Stress testing framework — v2 requirements
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LGUP-01 | Remove `langgraph<1.0` pin and upgrade to `>=1.0.9` without breaking 208 existing tests | Pin strategy (1.0.6 first), backwards-compat notes, pyproject.toml change pattern |
| LGUP-02 | Use `ToolNode` + `tools_condition` via `langchain-anthropic`, replacing manual XML/JSON envelope parser in `graph.py` | ToolNode construction pattern, handle_tool_errors flag, Anthropic-path-only scope |
| LGUP-03 | All `RunState` list fields use `Annotated[list[T], operator.add]` reducers | Annotated reducer syntax, impact on TypedDict, ensure_state_defaults() stays |
| LGUP-04 | Message history compacted when exceeding configurable threshold (default 40) | Sliding-window compaction in `ensure_state_defaults()`, env var pattern |
| OBSV-02 | `@observe()` decorator wired on `run()` in `run.py` and `generate()` in `provider.py` | `observability.py` already correct — just apply decorator; no-op when unconfigured |
| LRNG-02 | `docs/ADR/` directory with ADRs for significant design decisions | ADR format (Status/Context/Decision/Consequences), first ADR content |
</phase_requirements>

---

## Summary

Phase 2 is a hardening and migration phase, not a feature phase. The primary work is: (1) remove the `langgraph<1.0` version pin and upgrade to 1.0.6 initially, validating all 208 tests pass before moving to latest; (2) wire `ToolNode`/`tools_condition` for the Anthropic provider path only, retiring the XML/JSON envelope parser for that path; (3) add `Annotated[list[T], operator.add]` reducers to the four plain list fields in `RunState`; (4) implement sliding-window message compaction in `ensure_state_defaults()`; (5) apply the existing `@observe()` decorator to `run()` and `generate()`; (6) create the `docs/ADR/` log; and (7) add a GitHub Actions CI pipeline.

All decisions are pre-locked in CONTEXT.md. The existing codebase is in good shape: `observability.py` already has a correct graceful-degradation `@observe()` stub, `ensure_state_defaults()` is the natural insertion point for compaction, `ScriptedProvider` remains the test harness, and `ChatProvider` protocol is preserved. The primary risks are the LangGraph 1.0 API surface changes (specifically `langgraph-prebuilt` 1.0.2 breaking `ToolNode.afunc` signature — confirmed in STATE.md) and ensuring `Annotated` reducers do not silently change behavior for existing sequential tests.

**Primary recommendation:** Upgrade langgraph in isolation first (LGUP-01), run all 208 tests green, then layer the remaining changes one at a time — reducers, ToolNode, compaction, @observe(), CI, ADRs. Never combine the pin removal with behavioral changes in a single commit.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| langgraph | 1.0.6 (initial pin) | Graph orchestration engine | Locked decision; 1.0.x is backwards-compatible with 0.2.x APIs used in graph.py |
| langgraph-prebuilt | 1.0.1 | `ToolNode`, `tools_condition` | Pin to 1.0.1 explicitly — 1.0.2 broke `ToolNode.afunc` signature (GitHub Issue #6363) |
| langchain-anthropic | latest compatible | Anthropic chat model binding for ToolNode path | Required to use `ToolNode` with Anthropic tool-call format |
| langfuse | already installed | `@observe()` tracing with graceful degradation | Already in codebase; `observability.py` stub is complete |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| operator (stdlib) | stdlib | `operator.add` reducer for `Annotated` list fields | Used in RunState TypedDict annotations |
| typing.Annotated | stdlib (3.12) | Annotate list fields with merge reducer | Required by LangGraph for parallel branch merge semantics |
| python-dotenv | already installed | Load `P1_MESSAGE_COMPACTION_THRESHOLD` from env | Already in use; no new dependency |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Sliding-window compaction | LLM summarization | Locked out — adds latency + live LLM dependency |
| Anthropic-path-only ToolNode | All providers at once | Locked out — one migration at a time; Ollama/OpenAI/Groq deferred |
| langgraph-prebuilt 1.0.1 pin | Latest prebuilt | 1.0.2 breaks afunc signature; safe to move after confirmed stable |

**Installation (additions only):**
```bash
pip install "langchain-anthropic>=0.3.0" "langgraph==1.0.6" "langgraph-prebuilt==1.0.1"
```

Update `pyproject.toml`:
```toml
# Remove: "langgraph<1.0"
# Add:
"langgraph>=1.0.6,<2.0",
"langgraph-prebuilt>=1.0.1,<1.0.2",
"langchain-anthropic>=0.3.0",
```

---

## Architecture Patterns

### Recommended Project Structure (changes only)

```
src/agentic_workflows/
├── orchestration/langgraph/
│   ├── state_schema.py      # ADD Annotated reducers + compaction in ensure_state_defaults()
│   ├── graph.py             # ADD ToolNode for Anthropic path; KEEP existing ChatProvider path
│   ├── provider.py          # ADD @observe() to generate()
│   └── run.py               # ADD @observe() to run()
├── observability.py         # UNCHANGED — already correct
docs/
└── ADR/
    ├── ADR-001-langgraph-version-upgrade.md   # NEW
    ├── ADR-002-toolnode-anthropic-path.md     # NEW
    └── ADR-003-annotated-reducers.md          # NEW (one per significant decision)
.github/workflows/
├── claude.yml               # UNCHANGED
└── ci.yml                   # NEW — ruff + mypy + pytest gate
```

### Pattern 1: Annotated Reducer on RunState List Fields

**What:** Replace `list[T]` fields in `RunState` TypedDict with `Annotated[list[T], operator.add]`. This tells LangGraph how to merge these fields when parallel branches (Send()) converge — instead of last-writer-wins, all entries from all branches are concatenated.

**When to use:** Any list field that accumulates records across nodes, especially those written by multiple branches.

**Example:**
```python
# Source: LangGraph docs — Annotated reducer pattern
import operator
from typing import Annotated, TypedDict
from agentic_workflows.orchestration.langgraph.state_schema import ToolRecord, MissionReport, MemoEvent

class RunState(TypedDict):
    # Before (plain list — last-writer-wins on parallel merge):
    # tool_history: list[ToolRecord]

    # After (Annotated reducer — concatenates on parallel merge):
    tool_history: Annotated[list[ToolRecord], operator.add]
    mission_reports: Annotated[list[MissionReport], operator.add]
    memo_events: Annotated[list[MemoEvent], operator.add]
    seen_tool_signatures: Annotated[list[str], operator.add]
```

**Critical:** `ensure_state_defaults()` is NOT removed. It remains the repair function for missing keys. Reducer annotations are a LangGraph graph-level merge contract, not Python-level initialization.

### Pattern 2: ToolNode Construction for Anthropic Path

**What:** Construct `ToolNode` with explicit `handle_tool_errors=True`. Wire it as a graph node. Use `tools_condition` as the routing condition from the agent node to the tool node.

**When to use:** When provider is Anthropic (detected at graph construction time via `P1_PROVIDER` env var).

**Example:**
```python
# Source: langgraph-prebuilt docs
from langgraph.prebuilt import ToolNode, tools_condition

# Construct with handle_tool_errors=True — required because prebuilt 1.0.1
# defaults this to False, unlike earlier versions
tool_node = ToolNode(tools=[...], handle_tool_errors=True)

# In graph builder:
builder.add_node("tools", tool_node)
builder.add_conditional_edges(
    "agent",           # source node
    tools_condition,   # routes to "tools" if tool_calls present, else END
    {"tools": "tools", "__end__": "__end__"}
)
```

**Deduplication note:** `ToolNode` has no built-in deduplication. The existing `seen_tool_signatures` check in `graph.py` must be preserved as a pre-check before invoking the ToolNode path.

### Pattern 3: Message Compaction in ensure_state_defaults()

**What:** Sliding-window truncation of `messages` list when it exceeds the configured threshold. Drop oldest messages (after system message at index 0) to keep list at threshold size.

**When to use:** Called at every node entry via `ensure_state_defaults()` — fires automatically.

**Example:**
```python
import os

def ensure_state_defaults(state: RunState | dict, *, system_prompt: str = "") -> RunState:
    # ... existing defaults repair ...

    # Message compaction — sliding window, drop oldest
    threshold = int(os.getenv("P1_MESSAGE_COMPACTION_THRESHOLD", "40"))
    messages = state_dict.get("messages", [])
    if len(messages) > threshold:
        # Preserve system message at index 0, drop oldest non-system messages
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        keep = non_system[-(threshold - len(system_msgs)):]
        state_dict["messages"] = system_msgs + keep

    return cast(RunState, state_dict)
```

### Pattern 4: @observe() Wiring

**What:** Apply the existing `observe()` decorator from `observability.py` to `run()` and `generate()`. The decorator is already a correct graceful-degradation stub — this is purely a wiring task.

**Example:**
```python
# In run.py
from agentic_workflows.observability import observe

@observe(name="run")
def run(mission: str, ...) -> dict:
    ...

# In provider.py
from agentic_workflows.observability import observe

class AnthropicProvider:
    @observe(name="provider.generate")
    def generate(self, messages: list, ...) -> dict:
        ...
```

**No env vars needed in CI** — when `LANGFUSE_PUBLIC_KEY` is absent, `observe()` returns a passthrough decorator. Zero side effects.

### Pattern 5: ADR Format

**What:** Lightweight markdown ADR in `docs/ADR/` with four mandatory sections.

**Example:**
```markdown
# ADR-001: Remove langgraph<1.0 Version Pin

**Status:** Accepted
**Date:** 2026-03-02

## Context
The `langgraph<1.0` pin was added during Phase 1 to maintain stability while the
1.0 API surface stabilized. Phase 2 requires ToolNode and tools_condition which are
only available in langgraph>=1.0.

## Decision
Remove the `langgraph<1.0` pin. Pin to `langgraph==1.0.6` and
`langgraph-prebuilt==1.0.1` initially (stable combination). Move to latest after
the 208-test suite passes green.

## Consequences
- ToolNode and tools_condition become available
- Annotated reducer syntax is supported for RunState list fields
- langgraph-prebuilt must be pinned to 1.0.1 (1.0.2 breaks ToolNode.afunc)
- All 208 existing tests must pass unchanged (backwards-compatible upgrade)
```

### Pattern 6: GitHub Actions CI

**What:** `.github/workflows/ci.yml` running ruff, mypy, pytest on every push and PR. Uses no API keys — ScriptedProvider handles all LLM interaction in tests.

**Example:**
```yaml
# Source: GitHub Actions docs
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check src/ tests/
      - name: Typecheck
        run: mypy src/
      - name: Test
        run: pytest tests/ -q
```

### Anti-Patterns to Avoid

- **Combining pin removal with behavioral changes:** Do not remove the `langgraph<1.0` pin in the same commit as RunState reducer changes or ToolNode wiring. Upgrade first, verify 208 tests green, then make behavioral changes.
- **Removing ensure_state_defaults():** Annotated reducers do not replace the repair function. They are graph-level merge semantics, not Python initialization.
- **handle_tool_errors omission:** Do not construct ToolNode without `handle_tool_errors=True`. The default in prebuilt 1.0.1 is False, meaning tool errors crash the graph node.
- **Touching ChatProvider protocol:** ToolNode integration is additive. ChatProvider, ScriptedProvider, and existing test patterns must be unchanged.
- **Raising max_steps to fix recursion errors:** If recursion errors appear after the upgrade, diagnose root cause. Recursion limit = max_steps × 3; do not raise max_steps.
- **Live LLM calls in CI:** All tests must use ScriptedProvider. Never add provider API keys to GitHub Actions secrets for this pipeline.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Parallel branch state merge | Custom merge logic in nodes | `Annotated[list[T], operator.add]` in TypedDict | LangGraph enforces this at graph level; custom logic is bypassed on fork-join |
| Tool call routing (Anthropic path) | XML/JSON envelope parser | `ToolNode` + `tools_condition` from langgraph-prebuilt | Parser is the source of fragility being removed; ToolNode handles format differences |
| Observability tracing | Custom timing/logging wrapper | `@observe()` from `observability.py` (already built) | Stub already has graceful degradation and Langfuse integration |
| CI gate | Shell script | GitHub Actions `ci.yml` | Native integration with PR status checks, branch protection |

**Key insight:** Every "don't hand-roll" item in this phase is already either built (observability.py), available in the pinned library (ToolNode), or is a stdlib feature (operator.add, Annotated). This is a wiring phase, not a building phase.

---

## Common Pitfalls

### Pitfall 1: langgraph-prebuilt 1.0.2 ToolNode.afunc Signature Break
**What goes wrong:** Upgrading to langgraph-prebuilt 1.0.2+ causes ToolNode to fail with a signature error on `afunc`.
**Why it happens:** Breaking change introduced in 1.0.2 (GitHub Issue #6363).
**How to avoid:** Pin `langgraph-prebuilt==1.0.1` in `pyproject.toml`. Only move to a higher version after confirming the fix landed in that version's changelog.
**Warning signs:** `TypeError` mentioning `afunc` during tool node construction or invocation.

### Pitfall 2: Annotated Reducer Changes Sequential Test Behavior
**What goes wrong:** After adding `Annotated[list[T], operator.add]`, existing sequential tests that check list contents produce unexpected results because LangGraph now concatenates rather than replaces.
**Why it happens:** In sequential execution (no parallel branches), the reducer still applies to every state update — a node returning `{"tool_history": [new_record]}` now appends, not replaces.
**How to avoid:** Node return values must only include the NEW records to add, not the full accumulated list. Audit all nodes that return list fields and ensure they return only the delta, not the full list.
**Warning signs:** Lists doubling or tripling in length across test assertions.

### Pitfall 3: System Message Lost in Compaction
**What goes wrong:** Sliding-window compaction drops the system message (index 0), causing the agent to lose its role/instruction context.
**Why it happens:** Naive slicing `messages[-40:]` truncates from the front, including the system message.
**How to avoid:** Separate system messages from non-system before slicing. Preserve all system messages; apply window only to non-system messages.
**Warning signs:** Agent behavior changes after compaction fires; tests with system-message assertions fail.

### Pitfall 4: @observe() Applied as Call Instead of Decorator
**What goes wrong:** `observe("run")(run_fn)` wrapping applied incorrectly in a non-decorator context leads to the traced function not being registered.
**Why it happens:** The `observe()` factory returns a decorator; it must be applied with `@observe(name="run")` syntax.
**How to avoid:** Always use `@observe(name="...")` decorator syntax, never manual wrapping in production paths.
**Warning signs:** Langfuse shows no traces even when keys are configured.

### Pitfall 5: CI Fails Due to Missing Dev Dependencies
**What goes wrong:** GitHub Actions `pip install -e ".[dev]"` fails because `pyproject.toml` `[project.optional-dependencies] dev` does not include a new dependency added for Phase 2.
**Why it happens:** `langchain-anthropic` or updated `langgraph` packages added to core deps but not reflected in CI install command or pyproject extras.
**How to avoid:** Add all new Phase 2 packages to `pyproject.toml` core dependencies (not just manually installed). Run `pip install -e ".[dev]"` locally to verify before pushing.
**Warning signs:** CI install step fails; or install succeeds but import fails in tests.

---

## Code Examples

Verified patterns from project codebase and official sources:

### Existing observability.py — Already Correct, Just Apply

```python
# Source: /src/agentic_workflows/observability.py (inspected directly)
# The @observe() decorator already handles graceful degradation:
# - If langfuse not installed: returns passthrough
# - If LANGFUSE_PUBLIC_KEY not set: returns passthrough
# - If configured: wraps with Langfuse tracing

from agentic_workflows.observability import observe

# Apply to run() in run.py:
@observe(name="run")
def run(...):
    ...

# Apply to generate() in provider.py (each provider class):
@observe(name="provider.generate")
def generate(self, messages, ...):
    ...
```

### RunState List Fields Requiring Annotated Reducers

```python
# Source: /src/agentic_workflows/orchestration/langgraph/state_schema.py (inspected directly)
# Current plain list fields that need Annotated reducers:
#   tool_history: list[ToolRecord]           → line 63
#   memo_events: list[MemoEvent]             → line 65
#   seen_tool_signatures: list[str]          → line 69
#   mission_reports: list[MissionReport]     → line 73

# After change:
import operator
from typing import Annotated

class RunState(TypedDict):
    tool_history: Annotated[list[ToolRecord], operator.add]
    memo_events: Annotated[list[MemoEvent], operator.add]
    seen_tool_signatures: Annotated[list[str], operator.add]
    mission_reports: Annotated[list[MissionReport], operator.add]
    # All other fields remain unchanged
```

### Node Return Value Contract After Reducer

```python
# BEFORE reducers — nodes could return full accumulated list:
# state["tool_history"] = [*state["tool_history"], new_record]
# return {"tool_history": state["tool_history"]}   # returns full list

# AFTER reducers — nodes must return ONLY the delta:
# return {"tool_history": [new_record]}   # LangGraph appends this to existing
```

### pyproject.toml Version Change

```toml
# Remove from dependencies:
#   "langgraph<1.0",

# Add to dependencies:
[project]
dependencies = [
    "langgraph>=1.0.6,<2.0",
    "langgraph-prebuilt>=1.0.1,<1.0.2",
    "langchain-anthropic>=0.3.0",
    # ... existing deps unchanged ...
]
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual XML/JSON envelope parsing for tool calls | `ToolNode` + `tools_condition` from langgraph-prebuilt | LangGraph 1.0 release | Eliminates parser fragility; standard tool call handling |
| Plain `list[T]` fields in TypedDict state | `Annotated[list[T], operator.add]` | LangGraph 0.2+ | Required for correct parallel branch merges via Send() |
| `langgraph<1.0` version pin | `langgraph>=1.0.6,<2.0` | Phase 2 (this phase) | Unblocks ToolNode, Annotated reducers, future Send() patterns |

**Deprecated/outdated:**
- XML/JSON envelope parser in `graph.py` `_execute_tool()` / `_handle_tool_calls()`: replaced by ToolNode for Anthropic path in this phase. Parser code for Ollama/OpenAI/Groq paths remains until those migrations happen.
- `langgraph<1.0` pin: removed in this phase.

---

## Open Questions

1. **Node return value audit scope**
   - What we know: After Annotated reducers, nodes must return only deltas (new records), not full accumulated lists.
   - What's unclear: How many nodes in `graph.py` (~1700 lines) currently return full lists vs deltas? This needs a grep audit before the reducer change.
   - Recommendation: Grep for all return statements containing `tool_history`, `mission_reports`, `memo_events`, `seen_tool_signatures` in `graph.py` before implementing reducers. Fix any full-list returns to return only the new element.

2. **langchain-anthropic version compatibility with langgraph 1.0.6**
   - What we know: langchain-anthropic is required for ToolNode with Anthropic format. CONTEXT.md says "latest compatible."
   - What's unclear: Exact version pairing tested against langgraph 1.0.6 without live API access.
   - Recommendation: Use `langchain-anthropic>=0.3.0` (known stable range). If import fails after install, check langchain-core version compatibility (langchain-anthropic and langgraph share langchain-core as a transitive dep).

3. **mypy compatibility with Annotated[list[T], operator.add]**
   - What we know: `operator.add` is typed as `Callable[[_T, _T], _T]`. `Annotated` with a non-type second arg may trigger mypy warnings.
   - What's unclear: Whether current mypy version (in `[dev]` extras) accepts `operator.add` as an Annotated metadata argument without errors.
   - Recommendation: If mypy raises errors on the Annotated fields, use `# type: ignore[misc]` on those lines as a temporary suppression, document in the ADR, and investigate proper typing in a follow-up.

---

## Sources

### Primary (HIGH confidence)
- `/src/agentic_workflows/orchestration/langgraph/state_schema.py` — inspected directly; all four list fields confirmed as plain `list[T]` at lines 63, 65, 69, 73
- `/src/agentic_workflows/observability.py` — inspected directly; `@observe()` stub confirmed correct with graceful degradation
- `.planning/phases/02-langgraph-upgrade-and-single-agent-hardening/02-CONTEXT.md` — all decisions locked by user
- `.planning/STATE.md` — confirms langgraph-prebuilt 1.0.2 afunc bug (GitHub Issue #6363) and 1.0.1 pin rationale
- `.planning/REQUIREMENTS.md` — phase requirement IDs and descriptions

### Secondary (MEDIUM confidence)
- GitHub Issue #6363 (referenced in STATE.md) — langgraph-prebuilt 1.0.2 ToolNode.afunc break; pin to 1.0.1
- GitHub Issue #6486 (referenced in CONTEXT.md) — handle_tool_errors defaults to False in prebuilt 1.0.1

### Tertiary (LOW confidence)
- langchain-anthropic `>=0.3.0` version floor — based on training data knowledge of stable release timeline; verify with `pip install langchain-anthropic` and check actual installed version

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all decisions locked in CONTEXT.md; source files inspected directly
- Architecture: HIGH — patterns derived from existing codebase + locked decisions; no speculation
- Pitfalls: HIGH for known bugs (prebuilt 1.0.2, handle_tool_errors default); MEDIUM for reducer delta-vs-full audit scope (size unknown without full graph.py read)

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (langgraph ecosystem is active; recheck prebuilt pin before implementing if more than 30 days pass)
