# Codex Server JSON-RPC Handshake Technical Reference

**Quick Reference:** JSON-RPC 2.0 protocol sequence for Codex Server agent subprocess communication

**Files:**
- `/src/orchestrator/agents/codex_server.py` (lines 396-476)
- `/src/orchestrator/agents/codex_server_common.py` (JSON-RPC helpers)

---

## Message Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Orchestrator (Client) ← JSON-RPC 2.0 → Codex app-server (Server)   │
│                        (newline-delimited JSON on stdin/stdout)      │
└─────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Step 0: Initialize (Enable Experimental API)                        │
├──────────────────────────────────────────────────────────────────────┤
│ Client → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 1,                                                   │
│            "method": "initialize",                                    │
│            "params": {                                                │
│              "clientInfo": {                                          │
│                "name": "orchestrator",                                │
│                "version": "1.0.0"                                     │
│              },                                                       │
│              "capabilities": {                                        │
│                "experimentalApi": true          ← ENABLES dynamicTools
│              }                                                        │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Server → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 1,                                                   │
│            "result": { ... }                                          │
│          }                                                            │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Step 1: Authenticate (Optional, API Key Only)                        │
├──────────────────────────────────────────────────────────────────────┤
│ Client → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 2,                                                   │
│            "method": "account/login/start",                           │
│            "params": {                                                │
│              "type": "apiKey",                                        │
│              "apiKey": "<example-api-key>"                            │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Server → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 2,                                                   │
│            "result": { ... } or error                                 │
│          }                                                            │
│                                                                       │
│ NOTE: Only sent if self._api_key is provided (codex_server.py:407)   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Step 2: Create Thread (WITH TOOL REGISTRATION)                       │
├──────────────────────────────────────────────────────────────────────┤
│ Client → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 3,                                                   │
│            "method": "thread/start",                                  │
│            "params": {                                                │
│              "cwd": "/path/to/workspace",                             │
│              "approvalPolicy": "never",                               │
│              "dynamicTools": [                    ← TOOL REGISTRATION │
│                {                                                      │
│                  "name": "update_checklist",                          │
│                  "description": "Mark requirement...",                │
│                  "inputSchema": { ... }                               │
│                },                                                     │
│                {                                                      │
│                  "name": "submit",                                    │
│                  "description": "Submit work...",                     │
│                  "inputSchema": { ... }                               │
│                },                                                     │
│                ... more tools ...                                     │
│              ],                                                       │
│              "sandbox": "workspace-write",        ← Optional          │
│              "model": "gpt-5.2-codex"             ← Optional          │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Server → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 3,                                                   │
│            "result": {                                                │
│              "thread": {                                              │
│                "id": "thread-abc123def456..."     ← THREAD ID LOCKED  │
│              }                                                        │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ ⚠️  AFTER THIS POINT: Tools are IMMUTABLE for this thread             │
│    No way to add/remove/modify tools until thread closes             │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Step 3: Start Turn (Submit Prompt)                                   │
├──────────────────────────────────────────────────────────────────────┤
│ Client → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 4,                                                   │
│            "method": "turn/start",                                    │
│            "params": {                                                │
│              "threadId": "thread-abc123def456...",                    │
│              "input": [                                               │
│                {                                                      │
│                  "type": "text",                                      │
│                  "text": "Full prompt text with task..."              │
│                }                                                      │
│              ],                                                       │
│              "cwd": "/path/to/workspace",                             │
│              "approvalPolicy": "never",                               │
│              "effort": "medium",                                      │
│              "model": "gpt-5.2-codex"             ← Optional override  │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Server → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "id": 4,                                                   │
│            "result": { ... }                                          │
│          }                                                            │
│                                                                       │
│ NOTE: NO "dynamicTools" parameter here!                              │
│       Tools from thread/start are locked and immutable               │
│       Cannot change tools mid-turn                                   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Step 4a: Tool Call Invocation (Server Request)                       │
├──────────────────────────────────────────────────────────────────────┤
│ Server → {                    ← Unsolicited server-to-client request  │
│            "jsonrpc": "2.0",                                          │
│            "id": 100,         ← MUST MATCH in response                │
│            "method": "item/tool/call",                                │
│            "params": {                                                │
│              "tool": "update_checklist",                              │
│              "arguments": {                                           │
│                "req_id": "R-01",                                      │
│                "status": "done",                                      │
│                "note": "Optional note"                                │
│              }                                                        │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Client → {                    ← MUST echo back id                     │
│            "jsonrpc": "2.0",                                          │
│            "id": 100,                                                 │
│            "result": {                                                │
│              "success": true,                                         │
│              "contentItems": [                                        │
│                {                                                      │
│                  "type": "inputText",                                 │
│                  "text": "Tool executed successfully."                │
│                }                                                      │
│              ]                                                        │
│            }                                                          │
│          }                                                            │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│ Step 4b: Notifications (Server → Client, no response needed)         │
├──────────────────────────────────────────────────────────────────────┤
│ Server → {                    ← No "id" = notification (no response)  │
│            "jsonrpc": "2.0",                                          │
│            "method": "item/agentMessage/delta",                       │
│            "params": {                                                │
│              "delta": "Let me start by..."                            │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Server → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "method": "item/started",                                  │
│            "params": {                                                │
│              "item": {                                                │
│                "type": "mcpToolCall",                                 │
│                "tool": "update_checklist",                            │
│                "arguments": { ... }                                   │
│              }                                                        │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Server → {                                                            │
│            "jsonrpc": "2.0",                                          │
│            "method": "item/completed",                                │
│            "params": { ... }                                          │
│          }                                                            │
│                                                                       │
│ ... (more deltas and items) ...                                       │
│                                                                       │
│ Server → {                    ← Terminal notification                 │
│            "jsonrpc": "2.0",                                          │
│            "method": "turn/completed",                                │
│            "params": {                                                │
│              "turn": {                                                │
│                "status": "completed",             ← or "interrupted"  │
│                "output": [...]                    ← or "systemError"  │
│              }                                                        │
│            }                                                          │
│          }                                                            │
│                                                                       │
│ Client: closes stdin, terminates subprocess                          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Key Code Locations

### Transport Implementation

**File:** `/src/orchestrator/agents/codex_server.py`

#### Stdio Transport (lines 75-128)
```python
class RealStdioTransport:
    """JSON-RPC 2.0 transport over subprocess stdin/stdout."""

    async def send(self, message: dict[str, Any]) -> None:
        """Write JSON-RPC message to subprocess stdin."""
        line = json.dumps(message) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def recv(self) -> dict[str, Any]:
        """Read next JSON-RPC message from subprocess stdout."""
        while True:
            line_bytes = await self._proc.stdout.readline()
            if not line_bytes:
                raise EOFError("codex app-server process stdout closed")
            line = line_bytes.decode().strip()
            if not line:
                continue  # skip blank lines
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                logger.debug("skipping non-JSON line: %r", line[:120])
```

**Critical detail:** Messages are newline-delimited JSON (NDJSON format), not framed by length.

### Handshake Sequence (lines 396-476)

```python
async def _send_and_wait(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Send request, wait for matching response, buffer notifications."""
    req_id = next_id
    next_id += 1
    await transport.send(build_jsonrpc_request(req_id, method, params))
    while True:
        msg = await transport.recv()
        if msg.get("id") == req_id:
            return msg  # ← Got the response we want
        # Buffer any notifications that arrive while we wait
        if "method" in msg and "id" not in msg:
            notification_buffer.append(msg)

# Step 0: Initialize
await _send_and_wait(
    "initialize",
    {
        "clientInfo": {"name": "orchestrator", "version": "1.0.0"},
        "capabilities": {"experimentalApi": True},
    },
)

# Step 1: Authenticate (if API key available)
if self._api_key:
    login_resp = await _send_and_wait(
        "account/login/start",
        {"type": "apiKey", "apiKey": self._api_key},
    )

# Step 2: Create Thread with Tools
thread_resp = await _send_and_wait("thread/start", {
    "cwd": context.working_dir,
    "approvalPolicy": "never",
    "dynamicTools": build_dynamic_tool_specs(),
    "sandbox": sandbox_mode,  # optional
    "model": self._model,     # optional
})
thread_id = thread_resp["result"]["thread"]["id"]

# Step 3: Start Turn
turn_resp = await _send_and_wait("turn/start", {
    "threadId": thread_id,
    "input": [{"type": "text", "text": full_prompt}],
    "cwd": context.working_dir,
    "approvalPolicy": "never",
    "effort": "medium",
    "model": self._model,  # optional
})

# Step 4: Process notifications
while not done:
    msg = await transport.recv()
    if msg.get("method") == "item/tool/call" and "id" in msg:
        # Server is requesting tool invocation
        await _dispatch_tool_call(msg)
    elif msg.get("method") == "turn/completed":
        # Terminal notification
        done = True
```

### Tool Call Dispatch (lines 481-520)

```python
async def _dispatch_tool_call(tool_msg: dict[str, Any]) -> None:
    """Extract tool details from server request and invoke callback."""
    tool_result = extract_dynamic_tool_call(tool_msg)
    if tool_result is None:
        return
    req_id, tool_name, tool_args = tool_result

    try:
        await route_tool_call(
            tool_name,
            tool_args,
            on_checklist_update,
            on_submit,
            on_grade=on_grade,
            on_complete_recovery=on_complete_recovery,
            agent_label="CodexServerAgent",
        )
        # Send success response (must echo req_id)
        await transport.send(
            build_dynamic_tool_call_response(req_id, success=True)
        )
    except ValueError:
        # Disallowed tool — respond with failure
        await transport.send(
            build_dynamic_tool_call_response(req_id, success=False)
        )
```

### Notification Handling (lines 744-803)

```python
async def _handle_notification(
    self,
    msg: dict[str, Any],
    output_lines: list[str],
    on_output: LogLineCallback | None,
    on_checklist_update: ChecklistUpdateCallback,
    on_submit: SubmitCallback,
    on_grade: GradeCallback | None,
    on_complete_recovery: CompleteRecoveryCallback | None = None,
) -> bool:
    """Process one JSON-RPC notification.

    Returns True if terminal (turn/completed), False otherwise.
    """
    # Check for terminal state
    terminal, status = is_terminal_notification(msg)
    if terminal:
        if status == "interrupted":
            raise AgentCancelledError(AgentType.CODEX_SERVER.value)
        if status in ("systemError", "failed"):
            raise AgentExecutionError(
                AgentType.CODEX_SERVER.value,
                f"Codex session ended with status: {status}",
            )
        return True  # Success

    # Route tool calls from item/started events
    tool_call = extract_tool_call_from_notification(msg)
    if tool_call is not None:
        tool_name, tool_args = tool_call
        await route_tool_call(
            tool_name,
            tool_args,
            on_checklist_update,
            on_submit,
            on_grade=on_grade,
            on_complete_recovery=on_complete_recovery,
            agent_label="CodexServerAgent",
        )

    # Accumulate agent message text
    delta = extract_agent_message_delta(msg)
    if delta:
        output_lines.append(delta)
        if on_output is not None:
            await on_output([delta])

    return False
```

---

## Helper Functions (codex_server_common.py)

### build_jsonrpc_request() — Lines 74-89

```python
def build_jsonrpc_request(
    req_id: int,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Build JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }
```

### extract_dynamic_tool_call() — Lines 125-149

Extracts `(req_id, tool_name, args)` from `item/tool/call` server request:

```python
def extract_dynamic_tool_call(
    message: dict[str, Any],
) -> tuple[int, str, dict[str, Any]] | None:
    """Extract (req_id, tool_name, args) from item/tool/call server request."""
    if message.get("method") != "item/tool/call":
        return None
    req_id = message.get("id")
    if req_id is None:
        return None
    params = message.get("params", {})
    tool_name = str(params.get("tool", ""))
    tool_args: dict[str, Any] = params.get("arguments") or {}
    return (int(req_id), tool_name, tool_args)
```

### build_dynamic_tool_call_response() — Lines 152-170

Builds response to `item/tool/call` server request:

```python
def build_dynamic_tool_call_response(
    req_id: int,
    success: bool = True,
) -> dict[str, Any]:
    """Build JSON-RPC response for item/tool/call."""
    text = "Tool executed successfully." if success else "Tool execution failed."
    return {
        "jsonrpc": "2.0",
        "id": req_id,                    # ← Must match server request id
        "result": {
            "success": success,
            "contentItems": [{"type": "inputText", "text": text}],
        },
    }
```

### is_terminal_notification() — Lines 284-300

Checks if a notification is `turn/completed`:

```python
def is_terminal_notification(
    notification: dict[str, Any],
) -> tuple[bool, str]:
    """Return (True, status) for turn/completed notification."""
    if notification.get("method") != "turn/completed":
        return (False, "")
    params = notification.get("params", {})
    turn: dict[str, Any] = params.get("turn", {})
    status = str(turn.get("status", ""))
    return (True, status)  # status in ["completed", "interrupted", "systemError"]
```

---

## Important Implementation Details

### 1. Message ID Sequencing

IDs must be unique and incremented per request:
```python
next_id = 1
req_id = next_id
next_id += 1
```

This ensures responses can be matched to requests uniquely.

### 2. Notification vs. Request Distinction

**Requests** have `id`:
```json
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {...}}
```

**Notifications** (one-way) do NOT have `id`:
```json
{"jsonrpc": "2.0", "method": "item/agentMessage/delta", "params": {...}}
```

**Server Requests** (bidirectional calls FROM server TO client):
```json
{"jsonrpc": "2.0", "id": 100, "method": "item/tool/call", "params": {...}}
```

Response MUST echo the `id`.

### 3. Tool Registration Immutability

**CRITICAL:** After `thread/start` succeeds, the tool set is locked for that thread's lifetime.

- ✅ Can call `turn/start` multiple times in same thread with same tools
- ✅ Can create different threads with different tools
- ❌ Cannot modify/add/remove tools mid-thread
- ❌ Cannot pass `dynamicTools` to `turn/start` (no such parameter)

### 4. Subprocess Lifecycle

Each `execute()` call:
1. Spawns new subprocess: `codex app-server`
2. Sends initialize → thread/start → turn/start
3. Reads notifications until `turn/completed`
4. Closes stdin, terminates subprocess
5. Cleans up isolated CODEX_HOME temp directory

---

## Error Handling

### Protocol Errors

```python
# thread/start failed
thread_resp = await _send_and_wait("thread/start", thread_params)
if "error" in thread_resp:
    raise AgentExecutionError(
        AgentType.CODEX_SERVER.value,
        "thread/start failed",
    )
```

### Terminal Notification Errors

```python
terminal, status = is_terminal_notification(msg)
if terminal:
    if status == "interrupted":
        raise AgentCancelledError(AgentType.CODEX_SERVER.value)
    if status in ("systemError", "failed"):
        raise AgentExecutionError(
            AgentType.CODEX_SERVER.value,
            f"Codex session ended with status: {status}",
        )
```

### Transport Errors

```python
except EOFError as exc:
    raise AgentNotAvailableError(
        AgentType.CODEX_SERVER.value,
        "codex app-server process terminated unexpectedly",
    ) from exc
```

---

## Tool Registration Schema

Full tool spec for `dynamicTools` parameter:

```python
{
    "name": str,                    # Tool name
    "description": str,             # Human-readable description
    "inputSchema": {                # JSON Schema describing inputs
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "...",
            },
            "param2": {
                "type": "string",
                "enum": ["option1", "option2"],
            },
        },
        "required": ["param1"],      # Which parameters are required
    },
}
```

Five tools currently defined in `build_dynamic_tool_specs()` (lines 173-258):
1. `update_checklist` — `{req_id: string, status: enum, note?: string}`
2. `grade` — `{req_id: string, grade: enum, grade_reason?: string}`
3. `submit` — `{}`
4. `request_clarification` — `{question: string}`
5. `complete_recovery` — `{outcome: enum, notes?: string}`

---

## Timeout and Cancellation

### Cancellation Mechanism

```python
async def cancel(self) -> None:
    """Request cancellation of active session."""
    self._cancelled = True
    if self._active_thread_id is not None and self._transport is not None:
        try:
            await self._transport.send(
                build_jsonrpc_request(99, "turn/interrupt", {"threadId": thread_id})
            )
        except Exception:
            pass  # Best-effort
    logger.info("CodexServerAgent: cancelled")
```

The cancellation flag is checked throughout the notification processing loop:
```python
while not done and not self._cancelled:
    msg = await transport.recv()
    if await _process_msg(msg):
        done = True

if self._cancelled:
    raise AgentCancelledError(AgentType.CODEX_SERVER.value)
```

---

## Summary: Key Protocol Constraints

| Feature | Supported | Notes |
|---------|-----------|-------|
| Tool registration | ✅ | Via `thread/start.dynamicTools` |
| Dynamic tools | ⚠️ | Per-thread only, not per-turn |
| Tool modification mid-thread | ❌ | Tools locked after `thread/start` |
| Per-turn parameter override | ⚠️ | Model can be overridden in `turn/start`, tools cannot |
| Multiple threads | ✅ | Can create separate threads for different tool sets |
| Tool invocation | ✅ | Via `item/tool/call` server request |
| Tool response | ✅ | Echo req_id in response |
| Conversation context | ✅ | Persists across turns in same thread |
| Cancellation | ✅ | Via `turn/interrupt` + flag checking |
