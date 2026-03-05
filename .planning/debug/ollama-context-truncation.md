---
status: investigating
trigger: "Investigate issue: ollama-context-truncation"
created: 2026-03-05T21:40:00Z
updated: 2026-03-05T21:40:00Z
---

## Current Focus

hypothesis: The failing Ollama request path is using a provider implementation that does not send `num_ctx`, so Ollama falls back to its default 4096-token context.
test: Trace all Ollama provider callsites and inspect whether the active path attaches `OLLAMA_NUM_CTX` to `/v1/chat/completions` requests.
expecting: If the active path is `core.llm_provider.LLMProvider`, requests will omit `options.num_ctx`; if the active path is the LangGraph provider, requests should include it.
next_action: Search the repo for `OLLAMA_NUM_CTX`, `LLMProvider`, and `build_provider` usages to identify the active code path.

## Symptoms

expected: Requests to Ollama should use a context window larger than 4096, ideally matching configured `OLLAMA_NUM_CTX=32768`, so prompts around 29k tokens are not truncated.
actual: Ollama runner logs show effective limit 4096 and prompt truncation, followed by 500 responses around 2m.
errors: `time=2026-03-05T23:23:20.816+02:00 level=WARN source=runner.go:187 msg="truncating input prompt" limit=4096 prompt=29312 keep=4 new=4096`; repeated `[GIN] ... | 500 | 2m0s | POST "/v1/chat/completions"`; occasional `aborting completion request due to client closing the connection`.
reproduction: Run this repo against local Ollama using the OpenAI-compatible base URL `http://localhost:11434/v1` with provider `ollama` and a prompt/context around 29k tokens.
started: Happening in current repo state as of 2026-03-05.

## Eliminated

## Evidence

- timestamp: 2026-03-05T21:39:00Z
  checked: `/home/nir/dev/agent_phase0/src/agentic_workflows/orchestration/langgraph/provider.py`
  found: `OllamaChatProvider` reads `OLLAMA_NUM_CTX` and, when positive, sends it as `extra_body={"options":{"num_ctx":...}}` on `chat.completions.create(...)`.
  implication: The LangGraph provider path is designed to request a larger Ollama context window.

- timestamp: 2026-03-05T21:39:00Z
  checked: `/home/nir/dev/agent_phase0/src/agentic_workflows/core/llm_provider.py`
  found: `LLMProvider` creates the Ollama OpenAI-compatible client and sends `chat.completions.create(...)` requests without any `extra_body` or `num_ctx` handling.
  implication: Any runtime using `LLMProvider` will leave Ollama at its server/model default context, which matches the observed 4096-token truncation.

- timestamp: 2026-03-05T21:39:00Z
  checked: `/home/nir/dev/agent_phase0/.env.example`
  found: The example env documents `OLLAMA_BASE_URL` and `OLLAMA_MODEL` but does not document `OLLAMA_NUM_CTX`.
  implication: The larger-context setting is not consistently surfaced across provider implementations/config docs.

## Resolution

root_cause:
fix:
verification:
files_changed: []
