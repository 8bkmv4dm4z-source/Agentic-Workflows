# Code Review: user_run.py

## Overview
`user_run.py` implements a persistent conversational session manager for the LangGraph orchestration system. It maintains rolling conversation history, compresses context between runs, and provides interactive CLI loop functionality.

---

## Structural Assessment

### ✅ Strengths

| Aspect | Observation |
|--------|-------------|
| **Architecture** | Clean separation between session state (`UserSession`) and orchestrator logic. Dataclass-based state management is appropriate. |
| **Type Safety** | Extensive use of type hints throughout; validates result structures with `_validate_result()`. |
| **Context Management** | Sophisticated `_minimize_context()` and `_build_prior_context()` handle token budget constraints. |
| **Defensive Programming** | Validates dict/list types before access (e.g., line 158-165, line 204-206). |
| **Recursion Safety** | `clarify_depth` guard prevents infinite clarification loops (line 285-290). |

### ⚠️ Areas of Concern

#### 1. **Method Complexity - `run_once()` (Lines 227-318)**
**Issue**: This method violates Single Responsibility Principle. It handles:
- Input formatting and history tracking
- Exception handling
- Result validation and processing  
- Mission report collection
- Stuck-loop detection
- Clarification recursion
- UI rendering

**Recommendation**: Decompose into smaller, testable units:
```python
# Suggested structure:
def _execute_orchestrator(self, formatted_input, prior_context) -> dict:
    # Handle orchestrator.run() with error wrapping

def _process_result(self, result: dict) -> dict:
    # Validation, history update, summary collection

def _detect_stuck_state(self, result: dict) -> bool:
    # Extract retry count logic

def _handle_clarification(self, answer: str, ...) -> dict:
    # Clarification flow with depth check
```

#### 2. **Magic String Dependencies**
**Line 278**: `"__CLARIFY__:"` prefix detection is fragile.

```python
# Current (brittle):
if answer.startswith("__CLARIFY__:"):

# Suggested:
from enum import Enum
class ResponseType(Enum):
    CLARIFY = "__CLARIFY__"
    
# Or use structured result instead of string prefix
```

#### 3. **Error Handling Granularity**
**Line 237-243**: Broad `Exception` catching loses diagnostic value.

```python
# Current:
except Exception as exc:  # noqa: BLE001
    error_msg = f"Orchestrator error: {exc}"
```

**Issues**:
- No logging of stack trace for debugging
- Different error types (LLM timeout vs config error) treated identically
- User sees raw exception message which may expose internals

#### 4. **State Mutation Side Effects**
The `_collect_summary()` and `_minimize_context()` methods mutate instance state as side effects during `run_once()`. This makes reasoning about state changes difficult.

**Line 254**: `self._collect_summary(result)` modifies `_completed_summaries`
**Line 274**: `self._minimize_context(full_clear=context_clear)` mutates `_conversation_history`

#### 5. **History Trimming Logic Bug Risk**
**Line 116-119**:
```python
if len(self._conversation_history) > _MAX_TOOL_HISTORY_RETAINED:
    self._conversation_history = self._conversation_history[-_MAX_TOOL_HISTORY_RETAINED:]
```

**Concern**: This keeps N entries from the *end* but the conversation is alternating user/assistant pairs. Trimming may leave orphaned entries (e.g., only assistant responses without prompts).

**Recommendation**: Ensure trimming preserves `[user, assistant]` pairs:
```python
# Keep complete pairs
trimmed = []
for i in range(0, len(self._conversation_history), 2):
    if i+1 < len(self._conversation_history):
        trimmed.extend([history[i], history[i+1]])
trimmed = trimmed[-_MAX_TOOL_HISTORY_RETAINED:]
```

---

## Maintainability Findings

### Code Smells

| Smell | Location | Severity |
|-------|----------|----------|
| **Long Method** | `run_once()` (90+ lines) | High |
| **Feature Envy** | UI rendering calls in business logic | Medium |
| **Primitive Obsession** | `result: dict[str, Any]` instead of Result class | Medium |
| **Comments as Crutches** | Complex logic requires extensive comments | Low |

### Naming Issues
- `_print_live_phase()` is `@staticmethod` but name suggests instance method behavior
- `_original_input` parameter (line 228) uses underscore prefix but is used in recursion

---

## Security Considerations

1. **Input Sanitization**: No sanitization of `user_input` before appending to history (potential for log injection if history is persisted).

2. **Error Information Leakage**: Raw exception messages flow to user output (line 240). Consider:
   ```python
   # Don't expose internal details
   log.exception("Orchestrator execution failed")  # full trace to log
   error_msg = "Unable to process request. Check logs for details."
   ```

---

## Testing Recommendations

The current structure makes unit testing difficult. Key test scenarios:

| Scenario | Current Testability | Recommendation |
|----------|---------------------|----------------|
| Context minimization | Medium (stateful, requires mocking) | Extract to pure function: `minimize(history: list) -> list` |
| Prior context building | Low (depends on instance state) | Make static with explicit inputs |
| Clarification flow | Low (recurses to self) | Extract to separate `ClarificationHandler` class |
| Tool failure extraction | Medium | Pure function taking `tool_history` |

---

## Documentation Quality

The module docstring (lines 3-10) is excellent. However:

- Complex multi-step logic in `_build_prior_context()` (lines 125-169) would benefit from inline examples
- The `state` dictionary structure is implicit (keys like `token_budget_used`, `context_clear_requested` are magic strings)

---

## Suggested Refactoring Priority

```
Priority 1: Decompose run_once() into focused methods
Priority 2: Create Result dataclass replacing dict[str, Any]
Priority 3: Extract UI rendering from business logic (render_* calls)
Priority 4: Add structured logging (replace print statements)
Priority 5: Extract tool failure parsing to pure function
```

---

## Conclusion

**Overall Grade: B+**

The code demonstrates solid architectural patterns for a conversational agent system. Token management and context compression are well-implemented. The primary concern is the complexity of `run_once()` which exceeds cognitive load limits and hinders maintainability.

**Primary Recommendation**: Refactor `run_once()` using Extract Method pattern to create a clear pipeline of discrete transformation steps. This will improve testability and make the clarification recursion flow more explicit.

---

*Review generated for commit: current (main branch)*
