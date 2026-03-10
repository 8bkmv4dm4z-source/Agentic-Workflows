---
phase: quick-5
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/agentic_workflows/tools/base.py
  - src/agentic_workflows/orchestration/langgraph/graph.py
  - src/agentic_workflows/orchestration/langgraph/provider.py
  - tests/conftest.py
autonomous: true
requirements: [QUICK-5]

must_haves:
  truths:
    - Compact prompt lists tools as write_file(path, content) not write_file
    - All providers accept optional response_schema param without breaking existing tests
    - OpenAI uses dynamic json_schema from tool registry when response_schema provided
    - LlamaCpp uses response_schema as response_format when grammar is disabled
    - Groq, Ollama, ScriptedProvider silently ignore response_schema
    - Orchestrator builds and caches _action_json_schema at __init__ time
    - All 823+ existing tests pass, ruff clean
  artifacts:
    - path: src/agentic_workflows/tools/base.py
      provides: required_args() method on Tool base class
      contains: def required_args
    - path: src/agentic_workflows/orchestration/langgraph/graph.py
      provides: _build_action_json_schema() plus compact prompt arg signatures
      contains: _build_action_json_schema
    - path: src/agentic_workflows/orchestration/langgraph/provider.py
      provides: Updated ChatProvider Protocol plus generate() signatures
      contains: response_schema
  key_links:
    - from: graph.py __init__
      to: _build_action_json_schema()
      via: self._action_json_schema cached at startup after build_tool_registry()
      pattern: _action_json_schema
    - from: _generate_with_hard_timeout()
      to: provider.generate()
      via: response_schema=self._action_json_schema keyword arg
      pattern: response_schema=self._action_json_schema
    - from: compact prompt builder (line ~310)
      to: tool.required_args()
      via: _tool_sig() inner function
      pattern: _tool_sig
---

## Objective

Add arg-signature hints to the compact prompt tool listing and introduce a dynamic
anyOf JSON schema (built from the live tool registry) that providers can use as
response_format for harder JSON enforcement.

**Purpose:** The compact prompt shows bare tool names with no arg guidance. Providers
that support json_schema response_format (OpenAI, LlamaCpp without grammar) benefit
from a schema that constrains the model to valid tool names and required args, reducing
parse errors and schema_mismatch retries.

**Output:**
- Tool base class gains required_args() that parses description strings
- Compact prompt emits classify_intent(text) instead of classify_intent
- ChatProvider Protocol updated with optional response_schema param
- All concrete providers handle response_schema (use or ignore)
- Orchestrator builds _action_json_schema once at init, passes to generate()

---

## Execution Context

@/home/nir/.claude/get-shit-done/workflows/execute-plan.md

---

## Context

Key source files:
- src/agentic_workflows/tools/base.py -- Tool base class (10 lines, add required_args)
- src/agentic_workflows/orchestration/langgraph/provider.py -- ChatProvider Protocol + all providers
- src/agentic_workflows/orchestration/langgraph/graph.py -- compact prompt builder (~line 310), __init__, _generate_with_hard_timeout (~line 1500)
- tests/conftest.py -- ScriptedProvider.generate() (line 44, positional-only, no annotations)

**Existing interfaces extracted from codebase:**

Current Tool base (base.py):
```python
class Tool:
    name: str
    description: str
    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError('Tool must implement the execute method.')
```

Current ChatProvider Protocol (provider.py line 66):
```python
class ChatProvider(Protocol):
    def generate(self, messages: Sequence[AgentMessage]) -> str: ...
    def context_size(self) -> int: ...
```

Generate call sites in _generate_with_hard_timeout (graph.py lines ~1506/1512):
```python
# Direct path (no timeout):
return self._router.route(complexity).generate(messages)
# Threaded path:
outbox.put(('ok', self._router.route(complexity).generate(messages)))
```

Compact prompt builder (graph.py line ~310, inside if self._prompt_tier == 'compact'):
```python
tool_names_line = ', '.join(self.tools.keys())
return env_block + compact_directive + f'Available tools: {tool_names_line}\n'
```

ScriptedProvider (conftest.py line 44):
```python
def generate(self, messages):  # no type annotations
```

LlamaCpp grammar-disabled path (provider.py ~577):
```python
if not self._grammar_enabled:
    kwargs['response_format'] = {'type': 'json_object'}
```

OpenAI existing schema constant (provider.py line 165):
```python
_OPENAI_ACTION_RESPONSE_FORMAT = {'type': 'json_schema', 'json_schema': {'name': 'agent_action', ...}}
# used as response_format=_OPENAI_ACTION_RESPONSE_FORMAT in generate()
```

---

## Tasks

### Task 1: Add required_args() to Tool base and update compact prompt signatures

**Files:** src/agentic_workflows/tools/base.py, src/agentic_workflows/orchestration/langgraph/graph.py

**Action:**

In base.py, add `import re` at top. Add required_args() method to Tool class:

```python
import re
from typing import Any


class Tool:
    name: str
    description: str

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError('Tool must implement the execute method.')

    def required_args(self) -> list[str]:
        """Extract required arg names from the description string.

        Parses segments like 'Required args: path (str), content (str). Optional: ...'
        Returns arg names in order, or [] when no Required args section exists.
        """
        desc = getattr(self, 'description', '')
        m = re.search(r'Required args?:\s*(.+?)(?:\.|Optional|$)', desc, re.IGNORECASE)
        if not m:
            return []
        segment = m.group(1)
        return [
            re.split(r'\s*[\(,]', a.strip())[0]
            for a in segment.split(',')
            if a.strip()
        ]
```

In graph.py, inside `if self._prompt_tier == 'compact':` block (around line 310),
replace the single line `tool_names_line = ', '.join(self.tools.keys())` with:

```python
def _tool_sig(name: str, tool: object) -> str:
    req = tool.required_args() if hasattr(tool, 'required_args') else []
    return f"{name}({', '.join(req)})" if req else name

tool_names_line = ', '.join(_tool_sig(n, t) for n, t in self.tools.items())
```

Use `object` annotation (not `Any`) -- `object` is always in scope, no import needed.
Do NOT touch the full-tier prompt path below (line ~318+).

**Verify:**
```bash
cd /home/nir/dev/agent_phase0
python -c "
from agentic_workflows.tools.base import Tool
t = Tool()
assert t.required_args() == []
t.description = 'Required args: path (str), content (str). Optional: mode (str).'
assert t.required_args() == ['path', 'content'], f'got {t.required_args()}'
t.description = 'Required args: text (str).'
assert t.required_args() == ['text'], f'got {t.required_args()}'
print('PASS required_args()')
"
```

**Done:** Tool.required_args() parses description strings and returns arg names. Compact
prompt shows `write_file(path, content)` instead of `write_file` for tools with Required
args in their description. Tools with no Required args section keep bare name format.

---

### Task 2: Update ChatProvider Protocol and all concrete providers with optional response_schema

**Files:** src/agentic_workflows/orchestration/langgraph/provider.py, tests/conftest.py

**Action:**

In provider.py, update ChatProvider Protocol signature:
```python
class ChatProvider(Protocol):
    def generate(
        self,
        messages: Sequence[AgentMessage],
        response_schema: dict | None = None,
    ) -> str: ...

    def context_size(self) -> int: ...
```

**OpenAIChatProvider.generate()** -- add param, use it when provided (dynamic schema
takes precedence over static _OPENAI_ACTION_RESPONSE_FORMAT constant):
```python
def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
    schema_to_use = response_schema if response_schema is not None else _OPENAI_ACTION_RESPONSE_FORMAT

    def _request_schema_mode() -> object:
        return self.client.chat.completions.create(
            model=self.model,
            messages=list(messages),
            response_format=schema_to_use,
            timeout=self.timeout_seconds,
        )
    # _request_json_mode() and rest of method remain unchanged
```

**GroqChatProvider.generate()** -- add param, ignore it:
```python
def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
    # response_schema ignored -- Groq has limited json_schema support
    # existing body unchanged
```

**OllamaChatProvider.generate()** -- add param after messages, ignore it:
```python
@observe(name='provider.generate')
def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:
    # response_schema ignored -- Ollama does not support json_schema response_format
    # existing body unchanged
```

**LlamaCppChatProvider.generate()** -- add param, use it when grammar is disabled.
In the _request_json_mode() inner function at the grammar-disabled branch (~line 577):
```python
if not self._grammar_enabled:
    kwargs['response_format'] = response_schema if response_schema is not None else {'type': 'json_object'}
```
Outer generate() signature: `def generate(self, messages: Sequence[AgentMessage], response_schema: dict | None = None) -> str:`

**tests/conftest.py ScriptedProvider.generate()** -- add response_schema param, ignore it:
```python
def generate(self, messages, response_schema=None):  # noqa: ANN001
    # response_schema ignored -- scripted responses are pre-determined
    if self._index < len(self._responses):
        value = self._responses[self._index]
        self._index += 1
        return value
    return self._responses[-1]
```

**Verify:**
```bash
cd /home/nir/dev/agent_phase0
python -c "
from tests.conftest import ScriptedProvider
import inspect
sig = inspect.signature(ScriptedProvider.generate)
assert 'response_schema' in sig.parameters, 'ScriptedProvider missing response_schema param'
print('PASS ScriptedProvider signature')"
make lint 2>&1 | tail -10
```

**Done:** All five providers (OpenAI, Groq, Ollama, LlamaCpp, ScriptedProvider) accept
`response_schema: dict | None = None`. OpenAI uses it preferentially; LlamaCpp uses it
when grammar is off; others ignore it. ChatProvider Protocol signature matches all impls.

---

### Task 3: Add _build_action_json_schema() to orchestrator and pass schema at generate() call sites

**Files:** src/agentic_workflows/orchestration/langgraph/graph.py

**Action:**

Add `_build_action_json_schema()` method to LangGraphOrchestrator (place near
_build_system_prompt() or after _build_codebase_context()):

```python
def _build_action_json_schema(self) -> dict:
    """Generate json_schema response_format from live tool registry.

    Produces an anyOf schema covering every registered tool (with required
    args as string properties) plus finish and clarify actions.
    Cached in self._action_json_schema at __init__ time.
    """
    tool_variants: list[dict] = []
    for name, tool in self.tools.items():
        req = tool.required_args() if hasattr(tool, 'required_args') else []
        args_props: dict = {arg: {'type': 'string'} for arg in req}
        variant: dict = {
            'type': 'object',
            'properties': {
                'action': {'const': 'tool'},
                'tool_name': {'const': name},
                'args': {
                    'type': 'object',
                    'properties': args_props,
                    **({'required': req} if req else {}),
                },
            },
            'required': ['action', 'tool_name', 'args'],
        }
        tool_variants.append(variant)
    tool_variants += [
        {
            'type': 'object',
            'properties': {
                'action': {'const': 'finish'},
                'answer': {'type': 'string'},
            },
            'required': ['action', 'answer'],
        },
        {
            'type': 'object',
            'properties': {
                'action': {'const': 'clarify'},
                'question': {'type': 'string'},
            },
            'required': ['action', 'question'],
        },
    ]
    return {
        'type': 'json_schema',
        'json_schema': {
            'name': 'agent_action',
            'schema': {'anyOf': tool_variants},
            'strict': False,
        },
    }
```

In __init__(), after `self.tools = build_tool_registry(...)` and before
`self.system_prompt = self._build_system_prompt()`, add:
```python
self._action_json_schema: dict = self._build_action_json_schema()
```

Update both generate() call sites in _generate_with_hard_timeout() (lines ~1506/1512).

Direct path (no timeout), change from:
```python
return self._router.route(complexity).generate(messages)
```
To:
```python
return self._router.route(complexity).generate(messages, response_schema=self._action_json_schema)
```

Threaded path, change from:
```python
outbox.put(('ok', self._router.route(complexity).generate(messages)))
```
To:
```python
outbox.put(('ok', self._router.route(complexity).generate(messages, response_schema=self._action_json_schema)))
```

**Verify:**
```bash
cd /home/nir/dev/agent_phase0
python -c "
from agentic_workflows.orchestration.langgraph.graph import LangGraphOrchestrator
from tests.conftest import ScriptedProvider
provider = ScriptedProvider([{'action': 'finish', 'answer': 'ok'}])
orch = LangGraphOrchestrator(provider=provider)
assert hasattr(orch, '_action_json_schema'), 'missing _action_json_schema'
schema = orch._action_json_schema
assert schema['type'] == 'json_schema'
inner = schema['json_schema']['schema']
assert 'anyOf' in inner
variants = inner['anyOf']
actions = [v['properties']['action'].get('const') for v in variants if 'action' in v.get('properties', {})]
assert 'finish' in actions and 'clarify' in actions
tool_vs = [v for v in variants if v.get('properties', {}).get('action', {}).get('const') == 'tool']
assert len(tool_vs) > 0, 'no tool variants'
print(f'PASS: {len(tool_vs)} tool variants + finish + clarify')"
pytest tests/ -q -x --tb=short -k 'not postgres' 2>&1 | tail -20
```

**Done:** _action_json_schema built at startup from live tool registry. Both
_generate_with_hard_timeout() call sites pass response_schema=self._action_json_schema.
All 823+ tests pass, make lint clean.

---

## Verification

```bash
cd /home/nir/dev/agent_phase0

# 1. Unit smoke tests
python -c "from agentic_workflows.tools.base import Tool; t=Tool(); assert t.required_args()==[]"

# 2. Full test suite (no Postgres)
pytest tests/ -q -x --tb=short -k 'not postgres'

# 3. Lint
make lint
```

## Success Criteria

- All 823+ existing tests pass with zero failures
- `make lint` exits 0
- `Tool.required_args()` parses standard description format correctly
- Compact prompt shows arg signatures for tools that have Required args in description
- `_action_json_schema` attribute exists on LangGraphOrchestrator at init time
- Both generate() call sites in _generate_with_hard_timeout() pass response_schema
- OpenAI uses dynamic schema when response_schema is not None
- LlamaCpp uses response_schema as response_format when grammar is disabled
- Groq, Ollama, ScriptedProvider accept the param and ignore it without error

## Output

After completion, create .planning/quick/5-tool-schema-enforcement-compact-prompt-s/5-SUMMARY.md
