---
status: resolved
trigger: "plan-invalid-empty-output-loop — model returns output={} at every planner step"
created: 2026-03-09T00:00:00Z
updated: 2026-03-09T01:00:00Z
---

## Current Focus

hypothesis: CONFIRMED AND FIXED. GBNF grammar causes phi-4 to return `{}` (minimum valid grammar token) instead of a real action. The provider.py grammar fallback (lines 598-603) only fires on exception or empty string — `"{}"` is neither. Fix applied: after grammar call, if content.strip() == "{}" and grammar is enabled, automatically retry in plain (unconstrained) mode. phi-4 without grammar constraint follows the compact prompt JSON schema and produces a valid action.
test: 1344 tests pass. Ruff clean.
expecting: phi-4 in real run produces valid action on retry in plain mode. No more consecutive timeout loops.
next_action: User verify with real phi-4 run.

## Symptoms

expected: Planner calls provider, model returns a valid JSON action ({"action": "tool", "tool_name": "...", ...} or {"action": "finish", ...}), orchestrator executes it.
actual: Every PLAN PROVIDER CALL returns output={} — an empty dict string "{}". Parser produces action={'action': '', 'tool_name': '', '__mission_id': 0, 'arg_keys': []} which fails validation with "action must be 'tool' or 'finish'". Steps 1-5 all fail identically, then server shuts down.
errors:
  - WARNING PLAN INVALID step=N invalid_count=N error=action must be 'tool' or 'finish' (repeats steps 1-5)
  - MODEL OUTPUT step=N output={} (every step, empty dict string)
reproduction: POST /run via FastAPI. P1_PROVIDER=llama-cpp (or similar). Regression appeared after phase 07.6 implementation.
timeline: Appeared after 07.6 execution (today 2026-03-09). 07.6-01 added two-tier prompt system and 07.6-04 refactored parse_action_json() to return (dict, bool) tuples.

## Eliminated

- hypothesis: The tuple refactor (07.6-04) broke _parse_action_json shim — treating tuple as dict
  evidence: _parse_action_json at graph.py:2321 correctly unpacks (data, bool) from parse_action_json; _parse_all_actions_json at 2331 correctly forwards to action_parser.parse_all_actions_json. The shims are fine. The bug is upstream: model returns "{}" which parses to {} (empty dict, valid JSON), so the parse path itself doesn't error.
  timestamp: 2026-03-09T00:01:00Z

- hypothesis: model_output logging shows post-parse "{}" not raw provider string
  evidence: Line 920 logs model_output[:500] BEFORE any parsing. output={} means the raw string from the provider is the 2-char string "{}". The model is physically returning an empty JSON object.
  timestamp: 2026-03-09T00:01:00Z

- hypothesis: Compact prompt is missing JSON schema instructions (the model has no format guidance)
  evidence: supervisor.md ## COMPACT section (lines 1-6) includes full JSON schema and two examples. The compact_directive extracted by _build_system_prompt compact branch includes this content. Prompt is adequate.
  timestamp: 2026-03-09T00:07:00Z

## Evidence

- timestamp: 2026-03-09T00:20:00Z
  checked: provider.py LlamaCppChatProvider.generate() fallback logic (lines 591-604)
  found: Grammar fallback at line 598 checks `if not content` (empty string). "{}" is truthy — this guard does NOT fire. No fallback to plain mode. Grammar-enforced call returns "{}" → caller receives it → graph.py {} guard converts to "" → empty-output escalation → hint injected. On step 2 model tries harder under grammar, hits provider timeout (30s × 3 retries = ~90s). This explains the 3-minute wait.
  implication: The fix must be at the provider layer, not the graph layer. Provider must detect "{}" from grammar call and retry in plain mode.

- timestamp: 2026-03-09T00:21:00Z
  checked: _grammar_enabled instance attribute in LlamaCppChatProvider
  found: Set at __init__ from LLAMA_CPP_GRAMMAR env var. Can be checked per-call in generate(). _request_plain_mode() is already defined within generate() and does unconstrained sampling. No grammar key passed in extra_body when grammar disabled.
  implication: Plain mode retry is safe and already exists. Adding a check for content.strip() == "{}" gated on self._grammar_enabled is clean and targeted.

- timestamp: 2026-03-09T00:22:00Z
  checked: supervisor.md ## COMPACT section
  found: Section is 6 lines: JSON schema + rules + two concrete examples. phi-4 without grammar constraint should follow this directly.
  implication: Compact prompt is sufficient. The issue is grammar constraint fighting the model's instruction-following, not missing prompt content.

- timestamp: 2026-03-09T00:01:00Z
  checked: graph.py line 920 — MODEL OUTPUT log
  found: Logs model_output[:500] before any parsing. output={} means the raw provider return is the 2-char string "{}".
  implication: The model is returning an empty JSON object, not a parse error. Root cause is the empty-output guard missing this case.

- timestamp: 2026-03-09T00:02:00Z
  checked: graph.py line 923 (empty-output guard)
  found: `if not model_output:` — string "{}" is truthy (non-empty string), guard NOT triggered.
  implication: "{}" bypasses the empty-output escalation entirely. No hint is injected. The model has no guidance to try again differently.

- timestamp: 2026-03-09T00:03:00Z
  checked: action_parser.py parse_all_actions_json("{}") flow
  found: json.loads("{}") = {} (empty dict). isinstance({}, dict) True. Returns ([{}], False). Then validate_action_from_dict({}) → action="" → raises ValueError("action must be 'tool' or 'finish'").
  implication: Matches the exact error in symptoms. {} causes PLAN INVALID, not empty-output escalation.

- timestamp: 2026-03-09T00:04:00Z
  checked: provider.py LlamaCppChatProvider.context_size() line 542-543
  found: Returns int(os.getenv("LLAMA_CPP_N_CTX", "8192")). Default 8192. 8192 ≤ 10000 → compact prompt tier selected.
  implication: llama-cpp uses compact prompt by default without any env override needed.

- timestamp: 2026-03-09T00:05:00Z
  checked: GBNF grammar in provider.py (_JSON_GBNF_GRAMMAR)
  found: object ::= "{" ws (string ":" ws value ("," ws string ":" ws value)*)? "}" ws — the ? makes content optional, {} is valid per grammar.
  implication: Grammar enforces valid JSON syntax but NOT semantic completeness. {} is intentionally allowed by the grammar. This cannot be fixed at the grammar level without breaking tool args.

- timestamp: 2026-03-09T00:06:00Z
  checked: graph.py PLAN INVALID exception handler (lines 1182-1282)
  found: Retry hints are appended (escalating: schema example at count 3+, then user question echo at count 5+). But the hints are generic JSON format reminders. The model ignores them and keeps returning {}.
  implication: PLAN INVALID retries are ineffective when the model is confused. The empty-output escalation path (lines 922-982) has better recovery logic including a deterministic fallback clarify action.

- timestamp: 2026-03-09T00:08:00Z
  checked: graph.py empty-output escalation path (lines 922-982)
  found: Tracks consecutive_empty counter. On threshold hit, injects a deterministic clarify action. Otherwise injects targeted hints. This path would break the loop.
  implication: Routing {} into this path (by treating it as semantically empty) would fix the infinite loop.

## Resolution

root_cause: |
  Two-layer bug in LlamaCppChatProvider + graph.py for phi-4 (and other grammar-incompatible models):

  Layer 1 (original, now fixed in graph.py): The empty-output guard at graph.py line 923
  checked `if not model_output:` (string emptiness). GBNF grammar returns `"{}"` — truthy.
  This bypassed empty-output escalation and caused PLAN INVALID loop. FIXED: graph.py now
  normalises `"{}"` to `""` at line 926 before the empty-output check.

  Layer 2 (new, now fixed in provider.py): Even with the graph.py fix routing `{}` to
  empty-output escalation and injecting a recovery hint, phi-4 under GBNF grammar still
  returns `{}` on every retry. Step 2 then times out (provider retries 3× at 30s each = ~90s)
  because grammar-constrained sampling for a real action causes token budget exhaustion.
  Root cause: GBNF grammar allows `{}` as the minimum valid JSON object token sequence.
  phi-4's instruction-following under grammar constraint collapses to this minimum when it
  cannot find a valid action — instead of the schema-correct `{"action":"finish","answer":"..."}`.
  The provider.py grammar fallback only fires on exception or empty string (`if not content`).
  `"{}"` is truthy, so no fallback. Plain mode is never tried.

  The fix at provider.py: after grammar call, detect `content.strip() == "{}"` and retry
  in plain (unconstrained) mode. phi-4 without grammar follows the compact prompt examples
  directly and produces valid JSON actions.

fix: |
  Two fixes applied:

  1. graph.py _plan_next_action (lines 922-931): Detect `model_output == "{}"` and normalise
     to `""`, routing into empty-output escalation instead of PLAN INVALID loop.

  2. provider.py LlamaCppChatProvider.generate() (lines 604-620): After grammar-enforced call,
     if `self._grammar_enabled and content.strip() == "{}"`, log a warning and retry via
     `_request_plain_mode()` (no grammar, no response_format). Use plain_content if non-empty.
     This is the primary fix — it prevents the empty output from ever reaching graph.py.

verification: |
  1344 tests pass. Ruff clean on provider.py.
  Fix 1 (graph.py): HUMAN VERIFIED — PLAN EMPTY JSON OBJECT warning fires correctly.
  Fix 2 (provider.py): HUMAN VERIFIED — "LLAMA-CPP grammar returned '{}' — falling back to plain mode"
    logged at step 3 of real phi-4 run. Plain mode subsequently timed out (phi-4 is fundamentally
    too slow without grammar constraint — 3+ minutes per call, PROVIDER RETRY attempt=1/3).
  User-facing resolution: phi-4-Q4_K_M.gguf is incompatible with this orchestration pattern.
    User switching to Qwen3-8B or Qwen3-14B with no_think flag.
  Both defensive code fixes remain in place and protect against future grammar-stubborn models.
files_changed:
  - src/agentic_workflows/orchestration/langgraph/graph.py (lines 922-931 — fix 1, already applied)
  - src/agentic_workflows/orchestration/langgraph/provider.py (lines 604-620 — fix 2, just applied)
