# Recursive RLM Architecture Integration Plan

## Goal
Integrate the broker-based ModalREPL architecture to enable true recursive sub-LLM calls with depth limiting.

## Current State (Simplified)
```
Root LLM (RLM_REPL)
  ↓ calls llm_query()
  ↓ spawns ephemeral Modal sandbox
  ↓ runs sub_rlm_worker.py
  ↓ makes direct OpenAI API call
  ↓ returns response
```
- Each sub-LLM call creates/destroys a sandbox
- No recursion: sub-LLMs cannot spawn their own REPLs
- No depth tracking

## Target State (Recursive)
```
Root LLM (RLM_REPL) [depth=0]
  ↓ uses ModalREPL (persistent sandbox with broker)
  ↓ sandbox code calls llm_query()
  ↓ broker forwards to LM handler
  ↓ creates Sub-RLM_REPL [depth=1]
  ↓ which has its own ModalREPL
  ↓ can call llm_query() again [depth=2]
  ↓ ... limited by MAX_DEPTH
```
- One persistent sandbox per RLM instance
- Sub-LLMs can spawn their own REPLs and recurse
- Depth tracking prevents infinite loops
- Broker pattern for async LLM request handling

## Architecture Components

### 1. ModalREPL Class
**Location:** `rlm/rlm/modal_repl.py` (new file, ~500 lines)

**Key Features:**
- Persistent Modal Sandbox with Flask broker on port 8080
- Tunneled HTTP communication via `encrypted_ports`
- Background polling thread for LLM requests
- State persistence via dill in `/tmp/rlm_state.dill`
- Provides `llm_query`, `llm_query_batched`, `FINAL_VAR`, `SHOW_VARS` in sandbox

**Interface (compatible with REPLEnv):**
```python
class ModalREPL:
    def __init__(self,
                 lm_handler: Callable,  # Function to handle LLM requests
                 depth: int = 0,
                 max_depth: int = 3,
                 context_payload: dict | list | str | None = None,
                 context_path: str | None = None,
                 image: modal.Image | None = None,
                 timeout: int = 600):
        self.depth = depth
        self.max_depth = max_depth
        self.sandbox = None  # Persistent
        self.broker_url = None
        self.locals = {}  # Synced from sandbox

    def code_execution(self, code: str) -> REPLResult:
        # Execute in sandbox, return REPLResult

    def cleanup(self):
        # Terminate sandbox, stop poller
```

### 2. LM Handler Function
**Location:** Inside RLM_REPL

The lm_handler is a function that receives an LLM request and routes it appropriately:

```python
def handle_llm_request(self, prompt: str, model: str | None, depth: int) -> str:
    """Handle LLM request from sandbox."""
    if depth >= self.max_depth:
        return f"Error: Maximum recursion depth ({self.max_depth}) reached"

    # Create a new RLM_REPL for the sub-LLM call
    sub_rlm = RLM_REPL(
        model=model or self.recursive_model,
        recursive_model=self.recursive_model,
        max_iterations=self.max_iterations,
        depth=depth + 1,
        max_depth=self.max_depth,
        enable_logging=self.enable_logging,
        # ... same modal config
    )

    # Run completion (this will create its own ModalREPL)
    return sub_rlm.completion(context=prompt, query="Process this.")
```

### 3. Depth Limiting
- Root RLM: `depth=0`
- First sub-LLM: `depth=1`
- Second-level sub-LLM: `depth=2`
- Default `max_depth=3` (configurable)
- When `depth >= max_depth`, return error instead of recursing

### 4. Modified RLM_REPL
**Changes to `rlm/rlm/rlm_repl.py`:**
- Add `depth: int = 0` and `max_depth: int = 3` parameters
- Add `sub_rlm_mode` parameter: "local", "modal_sandbox", or "modal_repl"
- When `sub_rlm_mode="modal_repl"`, create ModalREPL instead of REPLEnv
- Pass `lm_handler` callback to ModalREPL

## Implementation Steps

### Step 1: Create ModalREPL class
**File:** `rlm/rlm/modal_repl.py`

Adapt from `deeprecurse/modal_repl.py` with changes:
1. Replace external imports with inline definitions (no `rlm.core.*` deps)
2. Accept `lm_handler: Callable[[str, str, int], str]` instead of `lm_handler_address`
3. Add `max_depth` parameter
4. Handle `context_path` in addition to `context_payload`
5. Sync `self.locals` from sandbox execution results
6. Use existing Modal `image` or create default

### Step 2: Modify RLM_REPL
**File:** `rlm/rlm/rlm_repl.py`

Add parameters:
```python
def __init__(self,
             ...existing params...,
             depth: int = 0,
             max_depth: int = 3,
             sub_rlm_mode: str = "local"):  # "local" | "modal_sandbox" | "modal_repl"
```

In `setup_context()`:
```python
if sub_rlm_mode == "modal_repl":
    from rlm.modal_repl import ModalREPL

    # Create LM handler that recursively calls RLM_REPL
    def lm_handler(prompt: str, model: str | None, depth: int) -> str:
        if depth >= self.max_depth:
            return f"Error: Max depth {self.max_depth} reached"

        sub_rlm = RLM_REPL(
            model=model or self.recursive_model,
            recursive_model=self.recursive_model,
            max_iterations=self.max_iterations,
            depth=depth,
            max_depth=self.max_depth,
            enable_logging=self.enable_logging,
            sub_rlm_mode="modal_repl",
            # ... pass through modal config
        )
        return sub_rlm.completion(context=prompt, query="Process and respond.")

    self.repl_env = ModalREPL(
        lm_handler=lm_handler,
        depth=self.depth,
        max_depth=self.max_depth,
        context_path=context_path,
        context_payload=context_data,
        image=self.sandbox_image,
        # ... other params
    )
else:
    # Existing REPLEnv logic
    self.repl_env = REPLEnv(...)
```

### Step 3: Update modal_runtime.py
**File:** `rlm/modal_runtime.py`

Change:
```python
rlm = RLM_REPL(
    model=model,
    recursive_model=recursive_model,
    max_iterations=max_iterations,
    depth=0,  # Root is always depth 0
    max_depth=3,  # Configurable
    enable_logging=True,
    sub_rlm_mode="modal_repl",  # Use new recursive mode
    sandbox_image=sandbox_image,
    sandbox_volumes={MOUNT_PATH: shared_volume},
    # ... rest
)
```

### Step 4: Update prompts
**File:** `rlm/rlm/utils/prompts.py`

Add note about recursion depth in system prompt:
```
Note: Sub-LLMs can themselves call llm_query to spawn their own reasoning sessions,
but recursion is limited to 3 levels to prevent infinite loops.
```

### Step 5: Testing
1. Test with `max_depth=1` (no recursion, just root)
2. Test with `max_depth=2` (root + 1 level sub-LLMs)
3. Test with `max_depth=3` (root + 2 levels)
4. Verify depth limit enforcement
5. Compare performance: ephemeral sandboxes vs persistent

## Files to Create/Modify

### New Files
1. `rlm/rlm/modal_repl.py` (~500 lines)

### Modified Files
1. `rlm/rlm/rlm_repl.py` - Add depth, max_depth, sub_rlm_mode="modal_repl"
2. `rlm/modal_runtime.py` - Use sub_rlm_mode="modal_repl"
3. `rlm/rlm/utils/prompts.py` - Add recursion depth note

### Files to Keep As-Is (for backwards compat)
1. `rlm/rlm/repl.py` - REPLEnv (local mode)
2. `rlm/rlm/sub_rlm_worker.py` - For modal_sandbox mode

## Configuration Examples

**Flat (current):**
```python
RLM_REPL(sub_rlm_mode="modal_sandbox", max_depth=1)
# Sub-LLMs = direct API calls
```

**Recursive (new):**
```python
RLM_REPL(sub_rlm_mode="modal_repl", max_depth=3)
# Sub-LLMs = new RLM_REPL instances with their own REPLs
```

## Benefits
1. **True recursion** - Sub-LLMs can spawn their own reasoning sessions
2. **Persistent sandboxes** - Faster (no setup/teardown per call)
3. **Depth control** - Prevent infinite loops
4. **State persistence** - Variables persist across code blocks in sandbox
5. **Concurrent sub-LLMs** - Broker can handle multiple requests
6. **Better logging** - Track full recursion tree

## Trade-offs
- More complex architecture
- Higher resource usage (persistent sandboxes)
- Slightly higher latency for first call (sandbox setup)
- Need to manage sandbox lifecycle

## Depth Limit Recommendations
- `max_depth=1`: No recursion (flat, like current)
- `max_depth=2`: Root + 1 level (good for most cases)
- `max_depth=3`: Root + 2 levels (for complex queries)
- `max_depth=4+`: Rarely needed, higher cost
