# Phase 7.6 Walkthrough: LLM Output Structure Stabilization

**Phase goal:** Mechanically enforce LLM output structure before multi-mission agent teams deploy
with weaker executor models. Fix the phi4 context overflow blocker, add provider-aware compact
prompts, re-enable GBNF grammar for llama-cpp, instrument the fallback parser, convert handoff
TypedDicts to Pydantic, persist chunked-read cursors, and add structural health metrics.

**Status:** Complete (16/16 verified, 2026-03-09) + post-phase quick-5 extension (2026-03-10)

---

## Two-Tier Prompt System

### Problem

phi4 (llama-cpp) has an 8192-token context. The full system prompt with all tool descriptions
exceeded the budget, causing "context length exceeded" errors before a single tool call.

### Solution

`provider.context_size() -> int` added to the `ChatProvider` protocol and all four providers:

| Provider | Return value |
|----------|-------------|
| LlamaCpp | `LLAMA_CPP_N_CTX` env var or `/props` query (default 8192) |
| Groq | 32768 |
| OpenAI | 128000 |
| Ollama | `OLLAMA_NUM_CTX` or 32768 |
| ScriptedProvider | 32768 |

`_select_prompt_tier(context_size: int) -> Literal["compact", "full"]` in `graph.py`:
- `compact` when `context_size <= 10000`
- `full` otherwise

Stored as `self._prompt_tier` in `LangGraphOrchestrator.__init__` after calling
`provider.context_size()`.

### Compact vs Full prompt

`_build_system_prompt()` dispatches on `self._prompt_tier`:

**Full tier:** Injects the complete `supervisor.md` directive + full tool descriptions.

**Compact tier:** Injects the `## COMPACT` section from `supervisor.md` (≤ 15 lines) + a single
tool-names line. Both tiers include the env block (`python3 is available`, working directory).

The compact tier is intentionally lossy — it trades some instruction fidelity for surviving the
context budget. The structural health counters (see below) measure the fallout.

---

## Fallback Parser Instrumentation

### Problem

When the LLM emits malformed JSON, `parse_action_json()` falls back to
`extract_first_json_object()`. This was silent — no log, no metric.

### Solution

`parse_action_json()` now returns `(dict, bool)` — the dict and a `fallback_used` flag. The
boolean propagates up through `validate_action()`, `parse_all_actions_json()`, and into the
orchestrator loop where it increments `state["structural_health"]["json_parse_fallback"]`.

A `WARNING` is logged at the parse site with `step` and a truncated `model_output` prefix so the
failing model output is visible in run logs.

---

## Pydantic Handoff Models

`TaskHandoff` and `HandoffResult` converted from `TypedDict` to Pydantic `BaseModel` with
`ConfigDict(extra="forbid")`. Malformed handoff data now raises `ValidationError` at parse time
instead of silently passing wrong keys into the graph. Call sites use `.model_dump()` before
appending to `handoff_queue` / `handoff_results`.

---

## Cursor Persistence for Chunked Reads

### Problem

After context eviction (`compact()`), the orchestrator lost track of where a `read_file_chunk`
sequence had stopped, causing the same chunk to be re-read or a duplicate-kill loop.

### Solution

`MissionContextStore` gained three methods:
- `upsert_cursor(run_id, task_id, tool, offset)` — store progress in `sub_task_cursors` table
- `get_cursor(run_id, task_id, tool)` — retrieve saved offset
- `get_active_cursors(run_id)` — list all in-progress cursors for a run

`context_manager.compact()` calls `get_active_cursors()` and re-injects `[Orchestrator]` cursor
hint messages before the next planner call so the planner knows to resume from the saved offset.

The `seen_tool_signatures` duplicate-kill check is bypassed when `action["__cursor_resume"] is True`
AND `tool_name == "read_file_chunk"` — narrowly scoped to prevent abuse.

Migration: `storage/migrations/005_sub_task_cursors.sql`.

---

## Structural Health Metrics

`RunState` gained `structural_health: dict` (initialized by `ensure_state_defaults()`):

```python
{
    "json_parse_fallback": 0,   # incremented each time fallback parser triggers
    "schema_mismatch": 0,       # incremented each time validate_action rejects a field
}
```

`_finalize()` attaches it to `audit_report["structural_health"]` — visible in every run's output
panel and in the cross-run audit summary.

---

## Post-Phase Extension: Tool Schema Enforcement (quick-5, 2026-03-10)

### Motivation

Qwen3-8B and similarly weak local models hallucinate tool arg names when the compact prompt lists
bare tool names. Observed: `classify_intent` called with `payload.text` instead of `text`, looping
indefinitely. Two fixes:

### Part A — Arg Signatures in Compact Prompt

`Tool.required_args() -> list[str]` added to `tools/base.py`. Parses the description string's
"Required args: X (type), ..." section via regex.

Compact prompt tool listing changed from:
```
classify_intent, search_files, read_file, write_file, ...
```
to:
```
classify_intent(text), search_files(pattern), read_file(path), write_file(path, content), ...
```

This is a soft enforcement — the model sees what args are expected but isn't forced to use them.

### Part B — JSON Schema response_format (hard enforcement)

`ChatProvider.generate()` extended with `response_schema: dict | None = None`.

`LangGraphOrchestrator._build_action_json_schema()` builds an `anyOf` JSON schema from the live
tool registry at init time (cached as `self._action_json_schema`):

```python
{
    "type": "json_schema",
    "json_schema": {
        "name": "agent_action",
        "schema": {
            "anyOf": [
                # one variant per tool:
                {
                    "type": "object",
                    "properties": {
                        "action": {"const": "tool"},
                        "tool_name": {"const": "classify_intent"},
                        "args": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"]
                        }
                    },
                    "required": ["action", "tool_name", "args"]
                },
                # ... more tools ...
                # finish and clarify variants
            ]
        },
        "strict": False
    }
}
```

Provider wiring:

| Provider | Behavior |
|----------|---------|
| LlamaCpp | Uses as `response_format` when `LLAMA_CPP_GRAMMAR=false`; ignores when grammar on |
| OpenAI | Uses if provided, else falls back to `_OPENAI_ACTION_RESPONSE_FORMAT` |
| Ollama | Accepts param, ignores (no json_schema support) |
| Groq | Accepts param, ignores (limited json_schema support) |
| ScriptedProvider | Accepts param, ignores (tests unaffected) |

Both `_generate_with_hard_timeout()` call sites pass `response_schema=self._action_json_schema`.

---

## GBNF Grammar

`LLAMA_CPP_GRAMMAR` env var (default `true`) enables GBNF grammar enforcement for llama-cpp.
When `false`, the JSON schema response_format (Part B above) takes over. The `.env.example`
comment was clarified to make the default explicit.

---

## Known Pitfalls

- `strict: False` in the JSON schema — required because `anyOf` with many variants doesn't
  satisfy OpenAI's strict mode constraints. LlamaCpp respects it regardless.
- `required_args()` parses description strings via regex — if a tool description doesn't follow
  the "Required args: X (type)" convention, `required_args()` returns `[]` and the tool name
  appears without args in the compact prompt (harmless fallback).
- Cursor bypass is narrowly scoped to `tool_name == "read_file_chunk"` — adding `__cursor_resume`
  to any other tool call will NOT bypass the duplicate check.

---

## Files

| File | What changed |
|------|-------------|
| `src/agentic_workflows/tools/base.py` | `Tool.required_args()` |
| `src/agentic_workflows/orchestration/langgraph/graph.py` | Two-tier prompt, `_build_action_json_schema()`, `_tool_sig()`, cursor bypass, structural health tracking |
| `src/agentic_workflows/orchestration/langgraph/provider.py` | `context_size()`, `response_schema` param, all providers updated |
| `src/agentic_workflows/orchestration/langgraph/action_parser.py` | `(dict, bool)` return, fallback WARNING |
| `src/agentic_workflows/orchestration/langgraph/handoff.py` | Pydantic BaseModel migration |
| `src/agentic_workflows/orchestration/langgraph/mission_context_store.py` | `upsert_cursor`, `get_cursor`, `get_active_cursors` |
| `src/agentic_workflows/orchestration/langgraph/context_manager.py` | Cursor hint re-injection in `compact()` |
| `src/agentic_workflows/orchestration/langgraph/state_schema.py` | `structural_health` field |
| `src/agentic_workflows/directives/supervisor.md` | `## COMPACT` section |
| `storage/migrations/005_sub_task_cursors.sql` | `sub_task_cursors` table DDL |
| `tests/conftest.py` | `ScriptedProvider` — `context_size()` + `response_schema` param |

---

## References

- `.planning/phases/07.6-llm-output-structure-stabilization/07.6-VERIFICATION.md` — 16/16 truths
- `.planning/phases/07.6-llm-output-structure-stabilization/07.6-POST-NOTES.md` — quick-5 detail
- `.planning/quick/5-tool-schema-enforcement-compact-prompt-s/5-SUMMARY.md` — quick-5 summary
