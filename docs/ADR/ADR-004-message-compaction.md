# ADR-004: Sliding-Window Message Compaction (No LLM Summarization)

**Status:** Accepted
**Date:** 2026-03-02

## Context
Phase 3 will delegate to specialist subgraphs. Before delegation, the parent graph's
`messages` list may contain 20–50+ messages from prior planning/execution turns. Without
compaction, specialist subgraphs receive bloated context that may exceed provider context
windows and increase latency.

## Decision
Implement sliding-window compaction in `ensure_state_defaults()`: when `messages` exceeds
`P1_MESSAGE_COMPACTION_THRESHOLD` (default 40), drop the oldest non-system messages to
bring the list back to the threshold. System messages are always preserved. Compaction fires
automatically at every node entry because `ensure_state_defaults()` is called at node entry.

LLM summarization was explicitly rejected: it adds latency and introduces a live-LLM
dependency in what should be deterministic state management.

## Consequences
- Context window overflow is prevented before specialist delegation in Phase 3
- System prompt is never lost (system messages are separated before the sliding window is applied)
- Threshold is configurable via `P1_MESSAGE_COMPACTION_THRESHOLD` env var (useful for testing)
- Historical context beyond the window is lost — this is acceptable for the current single-agent
  workload; revisit if long-running sessions require more context depth
- No new dependencies required (stdlib `os.getenv` only)
