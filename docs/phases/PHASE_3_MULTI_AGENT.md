# Phase 3 -- Multi-Agent Orchestration

**Duration:** Week 5-8
**Prerequisites:** Phase 2 complete
**Status:** Planned

## Goal
Evolve from single-agent to multi-agent orchestration with specialist roles, persistent memory, human-in-the-loop, and MCP server capabilities.

## Phase 1 Bridge

- A deterministic reviewer gate is implemented in Phase 1 runtime as a stability-first bridge.
- Phase 3 should evolve this into a dedicated reviewer specialist/subgraph with richer routing and handoff handling.
- Until then, reviewer policy selection remains runtime-configured and deterministic (`fail_only`, `weighted`, `both`).

## Sub-phases

### 3A: Agent Design
- [ ] Define specialist roles (research, execution, evaluation)
- [ ] Create directive templates with YAML frontmatter + markdown body
- [ ] Implement role-based system prompts

### 3B: Plan-and-Execute
- [ ] Build Planner agent as LangGraph subgraph
- [ ] Build Executor agent as LangGraph subgraph
- [ ] Implement re-planning loop on execution failure

### 3C: Supervisor Graph
- [ ] Central routing via LangGraph `Command` + conditional edges
- [ ] Dynamic agent spawning based on task requirements
- [ ] Agent-to-agent communication protocol

### 3D: Memory
- [ ] Integrate Mem0 for cross-session episodic/semantic memory
- [ ] Memory retrieval during planning phase
- [ ] Memory persistence across agent sessions

### 3E: Human-in-the-Loop
- [ ] LangGraph `interrupt()` for high-stakes tool calls
- [ ] Approval workflow for destructive operations
- [ ] Configurable approval thresholds

### 3F: MCP Server
- [ ] Expose tools as MCP endpoints via `mcp[cli]` SDK
- [ ] Tool discovery and schema generation
- [ ] Authentication and rate limiting

### 3G: Cost Optimization
- [ ] Model routing: Haiku for simple tasks, Sonnet for complex
- [ ] Anthropic prompt caching (90% cost reduction on repeated content)
- [ ] Token budget tracking and enforcement

## Industry Tools
- `mem0ai` (persistent agent memory)
- `mcp[cli]>=1.26` (Model Context Protocol)
- LangGraph `Command`, `Send`, `interrupt()` APIs
- Anthropic prompt caching

## Acceptance Criteria
- [ ] Multi-agent demo runs end-to-end
- [ ] Mem0 persists across sessions
- [ ] MCP server responds to tool calls
- [ ] Model routing achieves measurable cost reduction

## Risks
| Risk | Severity | Mitigation |
|------|----------|------------|
| Multi-agent state coordination complexity | High | Typed contracts between agents |
| Mem0 reliability in production | Medium | Fallback to local SQLite store |
| MCP protocol version changes | Low | Pin mcp SDK version |
