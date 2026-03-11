---
status: awaiting_human_verify
trigger: "After commit 24f70ff, Qwen3-8B planner returns empty plans -- 0 tools executed, loops plan-plan-plan-plan-clarify-finalize."
created: 2026-03-11T00:00:00Z
updated: 2026-03-11T14:00:00Z
---

## Current Focus

hypothesis: CONFIRMED -- GBNF grammar is incompatible with Qwen3-8B. Grammar blocks <think> tokens even with /no_think, causing empty output. The 02:18 working run had grammar DISABLED (json_schema mode); the 13:10 failing run had grammar ENABLED (GBNF mode).
test: Compare request logs between working and failing runs
expecting: Working run uses json_schema response_format; failing run uses GBNF grammar
next_action: Verify fix with user -- auto-detect Qwen3 and disable grammar

## Symptoms

expected: Planner produces structured plans with tool calls as before commit 24f70ff
actual: 0 tools used, answer: `__CLARIFY__`, plan-plan-plan-plan-clarify-finalize loop
errors: No explicit errors -- silent empty content from llama-server
reproduction: Run with Qwen3-8B model and LLAMA_CPP_GRAMMAR not explicitly set to false
timeline: Started after LLAMA_CPP_GRAMMAR=false was commented out in .env (not directly caused by commit 24f70ff)

## Eliminated

- hypothesis: json_schema anyOf too large (36 variants) causing llama-server to reject schema
  evidence: Grammar is enabled by default, which SKIPS response_format entirely (line 608). The json_schema is not sent when grammar is active.
  timestamp: 2026-03-11T13:30:00Z

- hypothesis: Richer cross-run format inflating context beyond model window
  evidence: The 13:07 run with only 67 chars of cross-run context also failed. The 02:18 run with identical system_prompt_len=7186 worked. Context size is 16384 (not 8192).
  timestamp: 2026-03-11T13:35:00Z

- hypothesis: Auto-inject context hint confusing the model
  evidence: All runs from 13:02 onwards failed regardless of whether auto-inject fired. The 13:07 run (1 mission) failed too.
  timestamp: 2026-03-11T13:40:00Z

- hypothesis: Code changes in commit 24f70ff directly caused the regression
  evidence: The 02:18 run was AFTER all commits (24f70ff, 998b263, c318a61) and worked fine. The code was identical in both working and failing sessions.
  timestamp: 2026-03-11T13:45:00Z

## Evidence

- timestamp: 2026-03-11T13:20:00Z
  checked: Model output in log.txt for all recent runs
  found: Every run from 13:02 onwards has "MODEL OUTPUT step=N output=" (empty string). Earlier runs at 02:18 had valid JSON output.
  implication: Not a gradual degradation -- all runs fail from a specific point, suggesting an env/config change between sessions.

- timestamp: 2026-03-11T13:30:00Z
  checked: Request options in log.txt for 02:18 working run vs 13:10 failing run
  found: "02:18 run: extra_json={'enable_thinking': False} (NO grammar). 13:10 run: extra_json={'enable_thinking': False, 'grammar': 'root ::= object...'} (grammar enabled)."
  implication: Grammar setting changed between sessions. The .env has LLAMA_CPP_GRAMMAR=false commented out, so the default (enabled) applies in the failing session.

- timestamp: 2026-03-11T13:32:00Z
  checked: 02:18 run request for response_format
  found: "02:18 run included response_format={'type': 'json_schema', 'json_schema': {'name': 'agent_action', 'schema': {'anyOf': [...]}}} -- grammar disabled means json_schema is used instead."
  implication: Qwen3-8B works correctly with json_schema response_format but fails with GBNF grammar.

- timestamp: 2026-03-11T13:35:00Z
  checked: HTTP response content-length for empty outputs
  found: Response content-length=780 bytes but content is empty string. The 780 bytes contain the completion JSON envelope with empty content field.
  implication: llama-server returns a valid response structure but the model cannot produce any tokens that satisfy both the GBNF grammar (must start with '{') and Qwen3's internal processing (wants to emit <think> first).

- timestamp: 2026-03-11T13:40:00Z
  checked: _request_plain_mode fallback
  found: BUG -- _request_plain_mode still sends grammar in extra_body. When grammar produces empty content and the code falls back to plain mode, the plain mode still has grammar constraints, so it also produces empty content.
  implication: The fallback path is broken -- plain mode is not actually plain.

- timestamp: 2026-03-11T13:45:00Z
  checked: .env file for LLAMA_CPP_GRAMMAR setting
  found: Both LLAMA_CPP_GRAMMAR=false lines are commented out, with a comment saying "MUST be false for Qwen3 -- GBNF blocks <think> tokens and deadlocks generation"
  implication: The user already knew about this incompatibility but the setting got commented out.

## Resolution

root_cause: Two issues combined:
1. GBNF grammar is incompatible with Qwen3 models. The grammar forces output to start with '{' but Qwen3 internally tries to emit <think> tokens even with /no_think, causing a conflict that results in empty output. The .env had LLAMA_CPP_GRAMMAR=false commented out, reverting to the default (enabled).
2. The _request_plain_mode fallback in LlamaCppChatProvider still includes the grammar in extra_body, so when grammar-constrained mode fails and falls back to "plain" mode, the grammar constraint is still active, defeating the purpose of the fallback.

fix: Two changes to provider.py:
1. Auto-detect Qwen3 models by name and disable GBNF grammar when LLAMA_CPP_GRAMMAR env var is not explicitly set. Explicit true/false still overrides. When auto-disabled, json_schema response_format is used instead (which worked in the 02:18 session).
2. Fix _request_plain_mode to strip the grammar key from extra_body, ensuring truly unconstrained generation on fallback. Also added a warning log when empty content triggers the plain mode retry.

verification: 34/34 provider tests pass (including 4 new tests for Qwen3 auto-detection). Ruff lint clean. Pre-existing test_action_queue failure is unrelated.

files_changed:
  - src/agentic_workflows/orchestration/langgraph/provider.py
  - tests/unit/test_llama_cpp_alias.py
