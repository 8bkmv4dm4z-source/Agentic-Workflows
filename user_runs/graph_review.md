# LangGraph Orchestrator Code Review

## High-Level Architecture

The LangGraphOrchestrator class (Phase 1) serves as the Layer-2 orchestration engine. It follows a state-graph pattern with clear separation between planning, execution, policy enforcement, and finalization.

**Key Components:**
- **Planning Loop (`_plan_next_action`)**: Handles model interaction, JSON parsing, and action validation
- **Execution Pipeline**: Routes to specialist subgraphs or direct tool execution
- **Memoization Policy**: Automatic and required memoization for deterministic writes
- **Checkpointing**: Persistent state saves at each node transition

## Strengths

### 1. Comprehensive Error Handling
The planner implements robust retry logic for:
- Provider timeouts (`max_provider_timeout_retries`)
- Invalid JSON (`max_invalid_plan_retries`)
- Duplicate tool calls (`max_duplicate_tool_retries`)
- Content validation failures (`max_content_validation_retries`)

### 2. State Management
Uses Pydantic-typed `RunState` with annotated reducers for parallel-safe list operations. The `_sequential_node` wrapper cleverly handles the semantic difference between parallel (additive) and sequential (replacement) semantics.

### 3. Token Budget Tracking
Implements rough token estimation (`len // 4`) with configurable thresholds, switching to deterministic fallback when exhausted.

### 4. Specialist Routing
Clean delegation to evaluator/executor roles via `DIRECTIVE_BY_SPECIALIST` configuration. Subgraph invocations provide real node transitions while maintaining backward compatibility with direct execution.

### 5. Mission Tracking
Missions parsed from structured plans get contracts and progress reporting. The `_diagnose_incomplete_missions` provides actionable debugging output.

## Areas of Concern

### 1. Anthropic ToolNode Path
The `P1_PROVIDER=anthropic` branch introduces significant branching complexity:
- Different graph topology (plan → tools → plan vs plan → execute → policy)
- Pre-check deduplication via `_dedup_then_tool_node` wrapper
- Skips JSON envelope parsing entirely

This creates two substantially different code paths that could drift out of sync.

### 2. Memoization Policy Enforcement
The `memo_required` flag uses retry counting that could interact poorly with other retry loops. Consider whether memo policy violations should be terminal failures vs recoverable.

### 3. Cache Reuse Safety
The `_maybe_complete_next_write_from_cache` has complex path-based matching and validation. The check `non_helper_required - {"write_file"}` for complexity safety is subtle and should have edge-case tests.

### 4. Message Compaction
`_compact_messages` preserves tool call summaries but loses full tool arguments/results after 50 messages. This could affect long-running replays.

## Code Quality Observations

### Positive Patterns
- **Type hints**: Extensive use with `RunState` and action dicts
- **Logging**: Structured logger with context variables
- **Delegation**: Helper modules for parsing, validation, and text extraction

### Improvement Opportunities
1. `_plan_next_action` (~500+ lines) violates single responsibility principle
2. Mixed concerns between state mutation and I/O in several methods
3. Some nested conditionals in finish rejection logic are complex

## Security Considerations
- `run_bash` timeout is configurable (max 120s) but path injection should be validated
- SQLite checkpoint/memo stores should use parameterized queries (verified in separate modules)
- `P1_PROVIDER` env var controls provider selection without strict validation

## Testing Recommendations
1. Property-based testing for signature deduplication (`_seen_tool_signatures`)
2. State machine verification for mission lifecycle transitions
3. Cache invalidation scenarios (poisoned entries already handled)
4. Provider timeout injection at various graph nodes

## Summary

This is a well-architected orchestration system with production-ready error handling and observability. The primary risk areas are:

1. Dual provider paths (Anthropic vs standard) and their divergence over time
2. State mutation complexity in the planning loop
3. Cache safety guarantees for cross-run completion

The codebase demonstrates mature patterns for deterministic agentic systems with strong checkpointing and audit guarantees.

---
**Review Date**: Current Run
**Lines Reviewed**: 2,565
**File**: `src/agentic_workflows/orchestration/langgraph/graph.py`