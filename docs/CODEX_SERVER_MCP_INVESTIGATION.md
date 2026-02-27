# Codex Server Agent: Dynamic MCP Support Investigation

**Date:** February 27, 2026
**Investigator:** Claude Code (Haiku 4.5)
**Status:** Complete Analysis with Implementation Roadmap

---

## Executive Summary

Codex Server **can accept MCPs dynamically** to some extent, but with important constraints:

### What Works Today
✅ MCPs can be passed to the `codex app-server` subprocess via JSON-RPC `thread/start` request
✅ Dynamic tools are registered once per thread (per task execution)
✅ Subprocess environment can be customized (auth, sandbox, working directory)
✅ Tools can differ between task executions (different threads)

### What Doesn't Work (Currently)
❌ MCPs cannot change mid-conversation (within a single task)
❌ No per-turn tool updates (only per-thread)
❌ Tools must be known at thread creation time
❌ Step-level tool control would require multiple threads

### Bottom Line
**MCPs CAN be dynamic per task/thread, but NOT per step within a task.** Each task gets its own subprocess with its own tool set. To get per-step tool variation, you'd either need multiple threads per routine or upstream Codex protocol changes.

---

## 1. Current Codex Server MCP Support

### 1.1 Subprocess Architecture

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/codex_server.py`

The Codex Server agent:
1. Spawns a `codex app-server` subprocess via `asyncio.create_subprocess_exec()` (line 713)
2. Communicates via JSON-RPC 2.0 over stdin/stdout
3. Creates one thread per task execution
4. Registers tools once at thread creation time
5. Cleans up subprocess when task completes

**Subprocess spawning (lines 713-720):**
```python
proc = await asyncio.create_subprocess_exec(
    *argv,  # ["codex", "app-server"]
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.DEVNULL,
    env=clean_env,              # Customized environment
    cwd=context.working_dir,    # Custom working dir
)
```

### 1.2 JSON-RPC Handshake Sequence

The protocol has **four required steps** (lines 396-476):

#### Step 0: Initialize (Experimental API Enablement)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "clientInfo": {"name": "orchestrator", "version": "1.0.0"},
    "capabilities": {"experimentalApi": true}
  }
}
```

**Why `experimentalApi: true`?** This enables `dynamicTools` parameter in the next step (line 397 comment).

#### Step 1: Authenticate (Optional, API Key Only)
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "account/login/start",
  "params": {
    "type": "apiKey",
    "apiKey": "sk-..."
  }
}
```

Only sent if `self._api_key` is provided (line 407).

#### Step 2: Create Thread with Tools
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "thread/start",
  "params": {
    "cwd": "/path/to/workspace",
    "approvalPolicy": "never",
    "dynamicTools": [
      {
        "name": "update_checklist",
        "description": "Mark a requirement as done, blocked, or not_applicable.",
        "inputSchema": { ... }
      },
      {
        "name": "submit",
        "description": "Submit work for verification or complete verification.",
        "inputSchema": { ... }
      },
      // ... more tools
    ],
    "sandbox": "workspace-write",  // Optional: controls macOS seatbelt
    "model": "gpt-5.2-codex"      // Optional: model override
  }
}
```

**Tools are registered HERE** and persist for the thread's lifetime. Once thread is created, tool set is immutable (line 16 of codex_server_common.py).

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "thread": {
      "id": "thread-abc123"
    }
  }
}
```

#### Step 3: Start Turn with Prompt
```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "method": "turn/start",
  "params": {
    "threadId": "thread-abc123",
    "input": [{"type": "text", "text": "full prompt text..."}],
    "cwd": "/path/to/workspace",
    "approvalPolicy": "never",
    "effort": "medium",
    "model": "gpt-5.2-codex"  // Optional: can vary per turn
  }
}
```

**Note:** `turn/start` has NO `dynamicTools` parameter. Tools cannot be updated here. Once the turn starts, tool set is locked in.

#### Step 4: Stream Notifications
The subprocess sends `item/*` notifications:
- `item/agentMessage/delta` — Agent's thinking
- `item/started` — Tool call initiated
- `item/completed` — Tool call finished
- `turn/completed` — Session ended

### 1.3 Tool Definition Format

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/codex_server_common.py` (lines 173-258)

Tools are defined as JSON Schema objects:
```python
{
    "name": "update_checklist",
    "description": "Mark a requirement as done, blocked, or not_applicable.",
    "inputSchema": {
        "type": "object",
        "required": ["req_id", "status"],
        "properties": {
            "req_id": {"type": "string", "description": "Requirement ID (e.g. 'R-01')"},
            "status": {
                "type": "string",
                "enum": ["done", "blocked", "not_applicable"],
            },
            "note": {"type": "string", "description": "Optional explanation"},
        },
    },
}
```

**Current Tools Defined (5 total):**
1. `update_checklist` — Mark requirement as done/blocked/not_applicable
2. `grade` — Set grade (verifier only, but currently registered always)
3. `submit` — Submit work for verification
4. `request_clarification` — Ask clarifying question
5. `complete_recovery` — Finalize recovery decision

### 1.4 Tool Allowlist Enforcement

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/codex_server_common.py` (lines 308-346)

After tool calls are received, they're validated against a static frozenset:
```python
CODEX_SERVER_TOOL_ALLOWLIST: frozenset[str] = frozenset({
    "update_checklist",
    "grade",
    "submit",
    "request_clarification",
    "complete_recovery",
})
```

**Important:** This is POST-HOC validation. Tools are already registered in the thread, so allowlist enforcement is a safety layer, not a registration filter.

---

## 2. How MCPs Can Be Dynamic per Task

### 2.1 Per-Thread Variation (Currently Possible)

**Each task execution creates a new thread:**
```
Task 1: Create thread A with tools=[update_checklist, submit]
        Run turn 1 with prompt 1
        Close thread A

Task 2: Create thread B with tools=[update_checklist, submit, grade]
        Run turn 1 with prompt 2
        Close thread B
```

**This enables:**
- ✅ Different tools for builder vs. verifier phases (detected from callback presence)
- ✅ Different tools for different tasks (if you pass different tool specs)
- ✅ External MCPs per task (if you build tool specs from task config)

**Code path:** `CodexServerAgent.execute()` → `_spawn_transport()` → `thread/start` request with `dynamicTools` parameter

### 2.2 Per-Step Variation (Not Currently Possible)

Within a single task, once `thread/start` is sent, tools are locked:
```
Step 1 of Task: Thread A created with tools=[file_editor, terminal]
                Turn 1 starts and continues...

Step 2 of Task: Still in Thread A, tools=[file_editor, terminal]
                NO WAY to update to tools=[browser, terminal]
                Would need to close thread and start new one
```

This would require either:
1. **Per-step threads** (high overhead, loses context)
2. **Codex protocol extension** (add `dynamicTools` to `turn/start`, upstream change)
3. **Workaround:** Prompt the agent about available tools in each turn

---

## 3. Environment and Configuration Passing

### 3.1 Subprocess Environment Setup

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/codex_server.py` (lines 684-710)

#### CODEX_HOME Isolation
```python
# Create isolated temp directory
tmp_codex_home = Path(tempfile.mkdtemp(prefix="orchestrator-codex-"))

# Copy auth credentials (if they exist)
if (user_codex_home / "auth.json").exists():
    shutil.copy2(user_codex_home / "auth.json", tmp_codex_home / "auth.json")

# Optionally copy config.toml based on restrictions mode
if self._restrictions == "use-local" and (user_codex_home / "config.toml").exists():
    shutil.copy2(user_codex_home / "config.toml", tmp_codex_home / "config.toml")

# Set isolated CODEX_HOME environment
clean_env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
clean_env["CODEX_HOME"] = str(tmp_codex_home)
```

**Why isolate?** Prevents the subprocess from overwriting user's `~/.codex/auth.json` when `account/login/start` is called (line 685-686 comment).

#### Restrictions Mode (Thread-Level Sandbox Control)

The `self._restrictions` parameter controls sandbox behavior:

1. **`"no-network"` (default)**
   - Forces `sandbox="workspace-write"` in `thread/start`
   - Disables network access
   - Does NOT load user's `config.toml`
   - Only copies `auth.json` (credentials)

2. **`"none"`**
   - Uses Codex defaults
   - Still isolates `CODEX_HOME` but copies only `auth.json`
   - No sandbox override

3. **`"use-local"`**
   - Copies both `auth.json` AND `config.toml`
   - No sandbox override (user's config controls)
   - Full local control

**Code (lines 424-431):**
```python
sandbox_mode: str | None
if self._restrictions == "none":
    sandbox_mode = "danger-full-access"
elif self._restrictions == "no-network":
    sandbox_mode = "workspace-write"
else:
    # "use-local": let the config.toml decide
    sandbox_mode = None
```

Then passed to `thread/start` params (line 437-438).

### 3.2 Subprocess Configuration via Constructor

**File:** `/Users/peter/code/task-world/src/orchestrator/agents/codex_server.py` (lines 166-195)

```python
class CodexServerAgent:
    def __init__(
        self,
        model: str | None = None,              # Model override
        callback_channel: str = "rest",        # REST or MCP callback
        api_key: str | None = None,            # API key for auth
        restrictions: str = "no-network",      # Sandbox/config behavior
        *,
        _transport: JsonRpcTransport | None = None,  # Test injection
        _environ: dict[str, str] | None = None,      # Test env override
    ) -> None:
```

**What can be configured at instance creation:**
- ✅ Model to use (e.g., `gpt-5.2-codex`)
- ✅ Callback channel (REST vs. MCP)
- ✅ OpenAI API key (for auth)
- ✅ Sandbox/restrictions mode
- ✅ Test-only: transport injection, environment override

**What can be configured per-execution (in `execute()`):**
- ✅ Model (if provided in constructor, can be overridden... actually no, it's baked in)
- ❌ Tools (cannot vary between executions with same agent instance)
- ❌ Sandbox (fixed at agent creation time)

### 3.3 API Key Handling

**Lines 184-190:**
```python
env = _environ if _environ is not None else {}
self._api_key: str | None = api_key or env.get("OPENAI_API_KEY")
```

**Important gotcha (line 187 comment):**
> Do NOT fall back to OPENAI_API_KEY from os.environ — doing so causes execute() to call account/login/start with apiKey, which unconditionally overwrites ~/.codex/auth.json and clobbers any ChatGPT subscription auth.

So the API key is controlled entirely at agent construction time, not at execution time.

---

## 4. JSON-RPC Protocol Capabilities vs. Constraints

### 4.1 What the JSON-RPC Protocol Supports

✅ **Tool registration at thread creation** (`thread/start` → `dynamicTools`)
✅ **Tool invocation and response** (`item/tool/call` → response)
✅ **Model override per turn** (`turn/start` → `model`)
✅ **Working directory per turn** (`turn/start` → `cwd`)
✅ **Multiple threads** (separate conversations)

### 4.2 What the JSON-RPC Protocol Doesn't Support

❌ **Per-turn tool updates** — No `dynamicTools` parameter in `turn/start`
❌ **Tool addition mid-thread** — Only `thread/start` accepts tool specs
❌ **Per-turn sandbox changes** — Sandbox set at `thread/start`, not `turn/start`
❌ **Tool removal or modification** — Tools are immutable after `thread/start`

### 4.3 Workaround: Prompt-Based Tool Discovery

If you want the agent to "know" about tools without explicitly registering them, you can include tool information in the prompt:

```python
prompt = """
Available tools for this step:
- terminal: Run shell commands
- file_editor: Create/edit files
- browser: Fetch web pages

You can call these tools using the update_checklist callback.
"""
```

This is what Codex likely does internally — the agent sees available tools in the system message and only uses those. But from the JSON-RPC perspective, the registered tools are still the canonical source of truth.

---

## 5. Format for Passing MCP Configs to Subprocess

### 5.1 Direct JSON Schema Approach (Current)

MCPs are passed as JSON Schema objects in the `dynamicTools` array:

```python
def build_dynamic_tool_specs() -> list[dict[str, Any]]:
    """Build tool specs for dynamicTools parameter."""
    return [
        {
            "name": "orchestrator_call_external_mcp",
            "description": "Call an external MCP tool",
            "inputSchema": {
                "type": "object",
                "required": ["tool_name", "arguments"],
                "properties": {
                    "tool_name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
            },
        },
    ]
```

### 5.2 Proposed Enhanced Approach for Dynamic MCPs

To support per-task MCP configuration, you'd need to:

1. **Add to ExecutionContext** (Phase 1):
```python
class ExecutionContext(BaseModel):
    # ... existing fields ...
    available_mcp_tools: list[dict[str, Any]] | None = None  # External MCPs
    available_tools: list[str] | None = None                 # Allowed callback tools
```

2. **Extend build_dynamic_tool_specs()**:
```python
def build_dynamic_tool_specs(
    context: ExecutionContext,
    is_verifier: bool = False,
) -> list[dict[str, Any]]:
    """Build tool specs, including external MCPs."""
    base_tools = [update_checklist, submit, ...]

    # Add verifier tool if needed
    if is_verifier:
        base_tools.append(grade)

    # Add external MCPs from context
    if context.available_mcp_tools:
        base_tools.extend(context.available_mcp_tools)

    return base_tools
```

3. **Pass ExecutionContext to tool builder** in `codex_server.py` line 435:
```python
# Before:
"dynamicTools": build_dynamic_tool_specs(),

# After:
"dynamicTools": build_dynamic_tool_specs(context, is_verifier=is_verifier),
```

### 5.3 MCP Format Compatibility

Codex accepts any tool that conforms to JSON Schema's `Tool` type:
```typescript
interface Tool {
  name: string;
  description: string;
  inputSchema: JSONSchema;  // JSON Schema describing arguments
}
```

This is **compatible with**:
- Claude API tool format
- OpenHands tool format
- MCP tool schema (can be converted to JSON Schema)

---

## 6. Per-Execution vs. Per-Step Tool Control

### 6.1 Current Behavior: Per-Execution Only

```python
async def execute(
    self,
    context: ExecutionContext,
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    ...
) -> ExecutionResult:
    """Execute a task with fixed tool set."""

    # Tool set determined here and never changes
    tool_specs = build_dynamic_tool_specs()

    # Send to thread/start
    await _send_and_wait("thread/start", {
        "dynamicTools": tool_specs,
        ...
    })

    # All subsequent turns use same tools
    await _send_and_wait("turn/start", {
        "threadId": thread_id,
        "input": [prompt],
        # NO "dynamicTools" parameter — tools are locked
    })
```

**Limitation:** All steps within a task share the same tools.

### 6.2 Enabling Per-Step Control: Two Approaches

#### Option A: Context Extension + Filtering (Recommended)

**Effort:** Medium | **Breaking:** No | **Feasibility:** ✅ High

1. Add step info to ExecutionContext (Phase 1, very low effort)
2. Extend routine schema with `available_tools` per step (Phase 0, very low effort)
3. Have executor read from step and populate context
4. Have agent filter tools based on context

**Files to modify:**
- `src/orchestrator/config/models.py` — Add `available_tools` to `StepConfig`
- `src/orchestrator/agents/types.py` — Add `available_tools` to `ExecutionContext`
- `src/orchestrator/agents/executor.py` — Populate from step config
- `src/orchestrator/agents/codex_server_common.py` — Filter `build_dynamic_tool_specs()`

**Code example:**
```python
# In codex_server.py execute():
tool_specs = build_dynamic_tool_specs(context, is_verifier)
# Filter by available_tools
if context.available_tools:
    allowed_names = set(context.available_tools)
    tool_specs = [t for t in tool_specs if t["name"] in allowed_names]
```

#### Option B: Thread-Per-Step (Heavier)

**Effort:** High | **Breaking:** Yes | **Feasibility:** ⚠️ Medium

Create a separate thread for each step:
```
Routine Step 1: Create Thread A, execute turn 1-N, close Thread A
Routine Step 2: Create Thread B, execute turn 1-M, close Thread B
```

**Pros:** Full per-step control, can change sandbox/model/tools per step
**Cons:** Loses conversation context, more overhead, requires task model changes

#### Option C: Codex Protocol Extension (Future)

**Effort:** Very High | **Breaking:** N/A (upstream) | **Feasibility:** ⚠️ Low

Propose to Codex team: add `dynamicTools` to `turn/start`:
```json
{
  "method": "turn/start",
  "params": {
    "dynamicTools": [...],  // ← NEW, update per turn
    ...
  }
}
```

**Pros:** True per-turn control, maintains conversation context
**Cons:** Requires upstream change, uncertain timeline, high complexity

---

## 7. Technical Feasibility Assessment

### 7.1 Can MCPs Be External?

**Yes, with caveats:**

1. **Format:** Codex accepts any JSON Schema tool definition
2. **Source:** Can come from:
   - In-process tool registry (current)
   - File-based MCP config (read at startup)
   - Database query (per-task lookup)
   - HTTP MCP server discovery (pre-execution)

3. **Constraints:** Must be available BEFORE `thread/start` is sent

### 7.2 Can MCPs Vary by Thread/Execution?

**Yes, trivially:**

Each `execute()` call creates a new thread, so you can pass different `dynamicTools` to different threads. Current limitation is that tools are hardcoded in `build_dynamic_tool_specs()`, which doesn't accept parameters.

**To enable:** Extend `build_dynamic_tool_specs()` to accept context/config and filter tools accordingly.

### 7.3 Can MCPs Vary by Step?

**Only with Option A (context extension) or Option B (thread-per-step):**

- **Within thread:** ❌ No (protocol constraint)
- **Across threads:** ✅ Yes (create separate thread per step)
- **Within conversation:** ❌ No (would need protocol extension)

### 7.4 Can JSON-RPC Handle MCP Specs?

**Yes, completely:**

JSON-RPC doesn't dictate tool schema — it just transports JSON. MCPs are represented as JSON Schema tools, which fit perfectly in the `dynamicTools` array.

**Example:**
```json
{
  "method": "thread/start",
  "params": {
    "dynamicTools": [
      {"name": "mcp_fetch_web", "description": "...", "inputSchema": {...}},
      {"name": "mcp_execute_python", "description": "...", "inputSchema": {...}},
      {"name": "orchestrator_submit", "description": "...", "inputSchema": {...}}
    ]
  }
}
```

All mixed together — Codex doesn't distinguish between orchestrator tools and external MCPs.

---

## 8. Recommended Implementation Path

### Phase 0: Prerequisites (Very Low Effort)

Add `available_tools` field to routine schema:

**File:** `/src/orchestrator/config/models.py`
```python
class StepConfig(BaseModel):
    id: str
    description: str
    instruction: str | None = None
    available_tools: list[str] | None = None  # ← NEW
```

### Phase 1: Context Extension (Low Effort)

Extend ExecutionContext and update executor:

**File:** `/src/orchestrator/agents/types.py`
```python
class ExecutionContext(BaseModel):
    # ... existing fields ...
    step_id: str | None = None
    available_tools: list[str] | None = None  # ← NEW
```

**File:** `/src/orchestrator/agents/executor.py` (line 654+)
```python
step_index = run.current_step_index
if 0 <= step_index < len(run.routine.steps):
    step_config = run.routine.steps[step_index]
    step_id = step_config.id
    available_tools = step_config.available_tools
else:
    step_id = None
    available_tools = None

context = ExecutionContext(
    run_id=run.id,
    task_id=task_state.id,
    # ... other fields ...
    step_id=step_id,              # ← NEW
    available_tools=available_tools,  # ← NEW
)
```

### Phase 2a: Quick Win — Codex Phase Filtering

**File:** `/src/orchestrator/agents/codex_server_common.py` (line 173)

Change signature:
```python
def build_dynamic_tool_specs(is_verifier: bool = False) -> list[dict[str, Any]]:
    """Build tool specifications.

    Args:
        is_verifier: If True, include grade tool; otherwise exclude it.
    """
    base_tools = [update_checklist, submit, request_clarification, complete_recovery]

    if is_verifier:
        base_tools.append(grade)

    return base_tools
```

**File:** `/src/orchestrator/agents/codex_server.py` (line 435)

Update call site:
```python
is_verifier = on_grade is not None
tool_specs = build_dynamic_tool_specs(is_verifier=is_verifier)

# Optional: filter by available_tools from context
if context.available_tools:
    allowed = set(context.available_tools)
    tool_specs = [t for t in tool_specs if t["name"] in allowed]

thread_params["dynamicTools"] = tool_specs
```

### Phase 2b: Agent Filtering

Apply same pattern to Claude SDK and other agents.

---

## 9. Summary: Questions Answered

### Q1: Does Codex Server support MCPs at all currently?

**A:** Yes, partially. It accepts `dynamicTools` in `thread/start` which can represent any JSON Schema tool, including externally-sourced MCPs. Current implementation only defines orchestrator callback tools.

### Q2: Can MCPs be passed to the codex app-server subprocess?

**A:** Yes. They're passed via the JSON-RPC `thread/start` request's `dynamicTools` parameter. The subprocess receives them as part of the thread initialization handshake.

### Q3: What format would MCPs need to be in?

**A:** JSON Schema tool objects:
```json
{
  "name": "tool_name",
  "description": "What it does",
  "inputSchema": {
    "type": "object",
    "properties": {...},
    "required": [...]
  }
}
```

This is compatible with Claude API tools, OpenHands tools, and MCP tool specs (after conversion).

### Q4: Can the JSON-RPC protocol handle MCP specifications?

**A:** Yes, completely. JSON-RPC just transports JSON. Tools are represented as plain JSON Schema objects in the `dynamicTools` array. Codex doesn't distinguish between orchestrator tools and external MCPs.

### Q5: Can MCPs be different per thread/per execution?

**A:** Yes, per-execution (different threads). Not per-step within a conversation (would need protocol extension or thread-per-step approach). Currently, tool set is locked once `thread/start` is sent.

---

## 10. Files Referenced

### Core Implementation Files
- `/Users/peter/code/task-world/src/orchestrator/agents/codex_server.py` (803 lines)
- `/Users/peter/code/task-world/src/orchestrator/agents/codex_server_common.py` (777 lines)
- `/Users/peter/code/task-world/src/orchestrator/agents/types.py` (ExecutionContext)
- `/Users/peter/code/task-world/src/orchestrator/config/models.py` (StepConfig)
- `/Users/peter/code/task-world/src/orchestrator/agents/executor.py` (ExecutionContext creation)

### Documentation Files
- `/Users/peter/code/task-world/docs/mcp-control/codex-server-agent.md` (280 lines)
- `/Users/peter/code/task-world/docs/mcp-control/IMPLEMENTATION-ROADMAP.md` (568 lines)
- `/Users/peter/code/task-world/docs/mcp-control/00-START-HERE.md` (navigation guide)

### Test Files
- `/Users/peter/code/task-world/tests/unit/test_codex_server_agent.py`
- `/Users/peter/code/task-world/tests/unit/test_codex_server_common.py`

---

## Conclusion

**Codex Server CAN support dynamic MCPs at the thread/task level**, and the infrastructure is mostly in place. The main limitations are:

1. **Thread-level granularity** — Tools are fixed per thread, not per turn
2. **Architecture changes needed** — To enable step-level control, you need to extend `ExecutionContext` and `StepConfig`
3. **Effort estimates** — Phase 0 (5 min), Phase 1 (30 min), Phase 2a (15 min), Phase 2b (varies by agent)

The recommended approach is **Option A: Context Extension + Filtering**, which is non-breaking and leverages existing Codex capabilities without requiring protocol extensions.

**Next steps:** See `/Users/peter/code/task-world/docs/mcp-control/IMPLEMENTATION-ROADMAP.md` for detailed code examples and phasing.
