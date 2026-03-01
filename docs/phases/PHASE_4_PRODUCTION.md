# Phase 4 -- Production Hardening

**Duration:** Week 9-12
**Prerequisites:** Phase 3 complete
**Status:** Planned

## Goal
Containerize, add API layer, CI/CD pipeline, security controls, eval suites, and comprehensive documentation for production deployment.

## Sub-phases

### 4A: Containerization
- [ ] Create `Dockerfile` for agent service
- [ ] Create `docker-compose.yml` (agent API, Redis, Langfuse)
- [ ] Health check endpoints

### 4B: API Layer
- [ ] FastAPI HTTP endpoints for agent invocation
- [ ] Request/response models with Pydantic
- [ ] WebSocket support for streaming responses

### 4C: CI/CD
- [ ] GitHub Actions pipeline: test, lint, typecheck, eval
- [ ] Branch protection rules
- [ ] Automated release workflow

### 4D: Security
- [ ] Input validation on all external boundaries
- [ ] Tool scoping and permission model
- [ ] Token budgets per request
- [ ] Secrets management (no hardcoded keys)

### 4E: Eval Suites
- [ ] Automated agent quality evals in CI
- [ ] Benchmark suite for tool execution performance
- [ ] Regression tests for prompt changes

### 4F: Agentic CI
- [ ] GitHub Agentic Workflows (`@claude` on PRs)
- [ ] Automated code review suggestions
- [ ] PR description generation

### 4G: Fallback Chains
- [ ] Try cheap model first, escalate on quality threshold
- [ ] LiteLLM as unified gateway for 100+ providers
- [ ] Circuit breaker for failing providers

### 4H: Documentation
- [ ] README with architecture diagram
- [ ] CHANGELOG
- [ ] Demo GIFs / screenshots
- [ ] API reference (auto-generated from docstrings)

## Industry Tools
- `fastapi[standard]` (HTTP API layer)
- `prefect>=3.6` (workflow scheduling, optional)
- `litellm` (unified LLM gateway)
- Docker + docker-compose
- GitHub Actions + claude-code-action

## Acceptance Criteria
- [ ] `docker-compose up` works end-to-end
- [ ] CI passes with eval gates
- [ ] README has architecture diagram and setup instructions
- [ ] Security controls documented and tested
- [ ] API responds to health checks and agent invocation

## Risks
| Risk | Severity | Mitigation |
|------|----------|------------|
| Over-engineering before product-market fit | Medium | Feature flags, MVP-first approach |
| Docker image size bloat | Low | Multi-stage builds |
| LiteLLM compatibility issues | Low | Pin version, test against target providers |
