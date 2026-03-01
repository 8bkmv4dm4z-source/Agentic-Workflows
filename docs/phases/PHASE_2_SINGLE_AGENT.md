# Phase 2 -- Single-Agent Enhancement

**Duration:** Week 3-4
**Prerequisites:** Phase 1 complete
**Status:** Planned

## Goal
Upgrade the single-agent loop to use LangGraph 1.0 stable APIs, Anthropic provider, structured outputs via instructor, and achieve full pytest coverage.

## Sub-phases

### 2A: Core Stack
- [ ] Install `langgraph>=1.0`, `langchain-core`, `langchain-anthropic`, `instructor`
- [ ] Update `pyproject.toml` dependencies

### 2B: LangGraph 1.0 Upgrade
- [ ] Migrate to `ToolNode`, `tools_condition` from langgraph.prebuilt
- [ ] Use proper checkpointer API (replace custom SQLiteCheckpointStore)
- [ ] Update graph construction to use stable StateGraph API

### 2C: Anthropic Provider
- [ ] Add `AnthropicChatProvider` via `langchain-anthropic`
- [ ] Add `ANTHROPIC_API_KEY` to `.env.example` and provider table
- [ ] Update `build_provider()` to support `anthropic` option

### 2D: Structured Outputs
- [ ] Define Pydantic models for plan extraction
- [ ] Use `instructor` for structured extraction with retries
- [ ] Replace manual JSON parsing in plan node

### 2E: Tool Wrapping
- [ ] Create LangGraph `@tool` wrappers alongside existing Tool class
- [ ] Ensure backward compatibility with existing tool registry

### 2F: LangGraph Studio
- [ ] Add `langgraph.json` for local graph visualization
- [ ] Document Studio setup in README

### 2G: Pytest Migration
- [ ] Convert remaining `unittest.TestCase` classes to pytest style
- [ ] Use pytest fixtures from conftest.py

### 2H: Quality Tests
- [ ] Schema validation tests for Pydantic models
- [ ] Structured output round-trip tests
- [ ] Provider fallback chain tests
- [ ] 95%+ coverage on new code

## Industry Tools
- `langgraph>=1.0` (LangGraph stable API)
- `langchain-anthropic` (Claude integration)
- `instructor` (structured extraction with retries)
- `pytest-asyncio` (async test support)

## Acceptance Criteria
- [ ] LangGraph Studio loads and visualizes the graph
- [ ] Structured outputs work with Anthropic provider
- [ ] All existing tests pass + new tests for upgraded components
- [ ] 95%+ coverage on new code

## Risks
| Risk | Severity | Mitigation |
|------|----------|------------|
| LangGraph API changes 0.2.67 -> 1.0 | Medium | Follow official migration guide; pin versions |
| instructor version compatibility | Low | Pin instructor version in pyproject.toml |
