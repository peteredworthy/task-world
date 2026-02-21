# Codex App Server — Transport API Contract

**Status:** Locked
**Date:** 2026-02-20
**Primary source:** [Codex App Server documentation](https://developers.openai.com/codex/app-server/)
**Secondary sources:** `openai/codex` GitHub repository (`codex-rs/app-server/README.md`);
`docs/codex-server/context/contract-matrix.md`; stub comments in
`src/orchestrator/agents/codex_server.py` and `src/orchestrator/agents/codex_server_remote.py`.

---

## Executive Summary

The Codex app server **does not expose a traditional HTTP REST API**.
It uses **JSON-RPC 2.0** messaging over one of two transports:

| Transport | Invocation | Status |
|-----------|-----------|--------|
| `stdio` | `codex app-server --listen stdio://` | Default; production-grade |
| `WebSocket` | `codex app-server --listen ws://IP:PORT` | Experimental; not recommended for production |

There are **no HTTP endpoints** (no `POST /sessions`, no SSE event stream).
All communication — requests from the client and notifications from the server — is carried as
newline-delimited JSON objects (JSONL) on stdout/stdin (stdio transport) or as individual WebSocket
text frames (WebSocket transport).

> **Implication for stub comments:** The `POST /sessions` and `GET /sessions/{id}/events` paths
> mentioned in the existing stub comments (`codex_server.py` lines 165–176,
> `codex_server_remote.py` lines 373–395) were placeholders written before API research was
> complete.  The correct client pattern is documented in full below.

---

## 1. Session Creation

### Concept

A **Thread** is the durable session container.  Creating a thread is the equivalent of "creating a
session".  Threads persist across reconnections; a thread ID can be resumed later.

### JSON-RPC Method

```
method: "thread/start"
```

### Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "thread/start",
  "params": {
    "model": "gpt-5.1-codex",
    "cwd": "/path/to/project",
    "approvalPolicy": "never",
    "sandbox": "workspaceWrite",
    "personality": "pragmatic",
    "dynamicTools": [
      {
        "name": "tool_name",
        "description": "Human-readable description",
        "inputSchema": {
          "type": "object",
          "properties": {}
        }
      }
    ],
    "persistExtendedHistory": true
  }
}
```

**Required params:**

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | Model identifier (e.g. `"gpt-5.1-codex"`) |

**Optional params (all have server defaults if omitted):**

| Field | Type | Description |
|-------|------|-------------|
| `cwd` | string | Working directory path for file operations |
| `approvalPolicy` | string | `"never"`, `"always"`, or `"ask"` — command execution approval mode |
| `sandbox` | string | Sandbox policy (e.g. `"workspaceWrite"`) |
| `personality` | string | Interaction style: `"friendly"`, `"pragmatic"`, or `"none"` |
| `dynamicTools` | array | Tool definitions injected into the session (v1: orchestrator callbacks only) |
| `persistExtendedHistory` | boolean | Persist full turn history for reconnection |
| `collaborationMode` | string | Preset collaboration mode identifier |
| `settings` | object | Additional key/value configuration |

### Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "thread": {
      "id": "thr_abc123",
      "preview": "",
      "modelProvider": "openai",
      "createdAt": 1730910000
    }
  }
}
```

**Response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `thread.id` | string | Opaque thread identifier; pass as `threadId` in subsequent requests |
| `thread.preview` | string | Short preview of the thread (empty on creation) |
| `thread.modelProvider` | string | Provider used (e.g. `"openai"`) |
| `thread.createdAt` | integer | Unix timestamp of creation |

### Session Resumption

An existing thread can be reopened without losing history:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "thread/resume",
  "params": {
    "threadId": "thr_abc123"
  }
}
```

---

## 2. Event Streaming / Polling Mechanism

### Protocol

The Codex app server uses **server-initiated JSON-RPC notifications** — not SSE, not polling.
After a client sends a request (e.g. `turn/start`), the server asynchronously emits zero or more
notification messages on stdout (stdio transport) or as WebSocket frames.  These notifications have
no `id` field (they are not responses to any specific request).

### Initiating Agent Work

To pass a prompt to the agent and start receiving events, send a `turn/start` request:

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "method": "turn/start",
  "params": {
    "threadId": "thr_abc123",
    "userMessage": "Your full prompt text here",
    "model": "gpt-5.1-codex",
    "cwd": "/path/to/project",
    "approvalPolicy": "never",
    "effort": "medium",
    "summary": "concise"
  }
}
```

**Params:**

| Field | Type | Description |
|-------|------|-------------|
| `threadId` | string | **Required.** Thread to send the turn to |
| `userMessage` | string | Plain-text prompt/instruction for this turn |
| `model` | string | Override model for this turn |
| `cwd` | string | Working directory override |
| `approvalPolicy` | string | Override approval policy for this turn |
| `effort` | string | `"low"`, `"medium"`, `"high"` |
| `summary` | string | `"concise"` or `"detailed"` — controls agent verbosity |

**Immediate response** (turn creation acknowledgement):

```json
{
  "jsonrpc": "2.0",
  "id": 10,
  "result": {
    "turn": {
      "id": "turn_xyz789",
      "status": "inProgress",
      "items": [],
      "error": null
    }
  }
}
```

### Event Notification Envelope

All server-pushed notifications share this structure:

```json
{
  "jsonrpc": "2.0",
  "method": "<notification-method>",
  "params": { ... }
}
```

Note: notifications have **no `id` field** — they cannot be replied to.

### Notification Methods (Event Types)

**Turn lifecycle:**

| Method | Description |
|--------|-------------|
| `turn/started` | Turn has been created and agent work is beginning |
| `turn/completed` | Turn has finished; contains terminal status |

**Item lifecycle (atomic output units):**

| Method | Description |
|--------|-------------|
| `item/started` | An item (message, tool call, command, etc.) has begun |
| `item/completed` | An item has finished; final fields are populated |

**Streaming deltas (incremental content):**

| Method | Description |
|--------|-------------|
| `item/agentMessage/delta` | Incremental text chunk from the agent response |
| `item/commandExecution/delta` | Incremental command output |
| `item/mcpToolCall/delta` | Incremental tool result |
| `item/plan/delta` | Incremental plan text |

**Thread events:**

| Method | Description |
|--------|-------------|
| `thread/started` | Thread opened or resumed |
| `thread/archived` | Thread moved to archive |
| `thread/unarchived` | Thread restored from archive |
| `thread/status/changed` | Thread status or active flags changed |

**System events:**

| Method | Description |
|--------|-------------|
| `account/updated` | Auth state changed; includes active `authMode` |
| `codex/event/session_configured` | Session configuration applied |

---

## 3. Tool-Call Event Shape

### Overview

When the agent invokes an MCP (Model Context Protocol) tool — including the orchestrator callback
tools (`update_checklist`, `grade`, `submit`, `request_clarification`) — two notifications are
emitted: `item/started` when the call begins, and `item/completed` when the result is available.

### item/started Notification (mcpToolCall)

```json
{
  "jsonrpc": "2.0",
  "method": "item/started",
  "params": {
    "item": {
      "type": "mcpToolCall",
      "id": "item_abc123",
      "serverId": "orchestrator",
      "toolName": "update_checklist",
      "status": "inProgress",
      "input": {
        "req_id": "R-01",
        "status": "done",
        "note": "Implementation complete"
      },
      "result": null,
      "error": null
    }
  }
}
```

### item/completed Notification (mcpToolCall)

```json
{
  "jsonrpc": "2.0",
  "method": "item/completed",
  "params": {
    "item": {
      "type": "mcpToolCall",
      "id": "item_abc123",
      "serverId": "orchestrator",
      "toolName": "update_checklist",
      "status": "completed",
      "input": {
        "req_id": "R-01",
        "status": "done",
        "note": "Implementation complete"
      },
      "result": "Checklist item R-01 updated to done",
      "error": null
    }
  }
}
```

### mcpToolCall Item Fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | Always `"mcpToolCall"` for MCP tool invocations |
| `id` | string | Unique item ID within the turn |
| `serverId` | string | Identifier of the MCP server that owns this tool |
| `toolName` | string | **The tool name to dispatch on** (e.g. `"update_checklist"`) |
| `status` | string | `"inProgress"` or `"completed"` or `"failed"` |
| `input` | object | **Tool arguments** as a JSON object — map from param name to value |
| `result` | string\|null | Tool return value (string) once completed; `null` while in progress |
| `error` | string\|null | Error message if the tool call failed; `null` on success |

### Extracting Tool Name and Arguments

```python
# Pseudocode for handling an item/started or item/completed notification
def handle_notification(method: str, params: dict) -> None:
    if method not in ("item/started", "item/completed"):
        return
    item = params.get("item", {})
    if item.get("type") != "mcpToolCall":
        return

    tool_name = item["toolName"]    # e.g. "update_checklist"
    tool_args = item["input"]        # e.g. {"req_id": "R-01", "status": "done"}

    # Enforce allow-list, then route:
    enforce_tool_allowlist(tool_name)
    await route_tool_call(tool_name, tool_args, ...)
```

### collabToolCall (Collaboration Mode)

A second item type, `collabToolCall`, appears when collaboration-mode tools are invoked.  Its
structure mirrors `mcpToolCall` but uses `server` (not `serverId`) and `tool` (not `toolName`)
field names.  Collaboration mode tools are **not** in the v1 allow-list and must be rejected by
the `enforce_tool_allowlist` guard.

---

## 4. Session Terminal States

### Turn Terminal States

A turn ends when `turn/completed` is emitted.  The `turn.status` field carries one of:

| Status | Meaning |
|--------|---------|
| `"completed"` | Turn finished normally; all agent work is done |
| `"interrupted"` | Turn was cancelled via `turn/interrupt` |
| `"systemError"` | Internal server error; the turn could not complete |

**turn/completed notification:**

```json
{
  "jsonrpc": "2.0",
  "method": "turn/completed",
  "params": {
    "turn": {
      "id": "turn_xyz789",
      "status": "completed",
      "items": [],
      "error": null,
      "tokenUsage": {
        "inputTokens": 1024,
        "outputTokens": 256
      }
    }
  }
}
```

### Session-Level Terminal States

A **session** (thread) itself does not have a terminal state in the same sense — threads are
persistent and can be resumed.  However, the orchestrator integration treats the following
conditions as a session terminal state:

| Condition | Orchestrator interpretation |
|-----------|----------------------------|
| `turn/completed` with `status: "completed"` | Session succeeded; stop polling |
| `turn/completed` with `status: "systemError"` | Session failed; raise `AgentExecutionError` |
| `turn/completed` with `status: "interrupted"` | Session cancelled; raise `AgentCancelledError` |

### Cancelling an In-Flight Turn

Send `turn/interrupt` to stop agent work mid-turn:

```json
{
  "jsonrpc": "2.0",
  "id": 20,
  "method": "turn/interrupt",
  "params": {
    "threadId": "thr_abc123"
  }
}
```

The server will emit a `turn/completed` notification with `status: "interrupted"` shortly after.

---

## 5. Authentication

### Local Variant (`codex_server`)

**No bearer auth is required for loopback connections.**  The local `codex app-server` process is
spawned by the orchestrator on `localhost`.  Because the connection is on the loopback interface,
no network-level authentication is performed.

Authentication is configured once, before any threads are created, by sending
`account/login/start`:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "account/login/start",
  "params": {
    "type": "apiKey",
    "apiKey": "sk-..."  // pragma: allowlist secret
  }
}
```

The API key is stored internally by the Codex server and used for upstream OpenAI API calls.  It
does not appear in subsequent request envelopes.

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "type": "apiKey"
  }
}
```

### Remote Variant (`codex_server_remote`)

**Bearer token in the `Authorization` HTTP header** (per contract-matrix §2).

When connecting to a remote Codex server over HTTPS (WebSocket transport with `wss://`), the
client must include:

```
Authorization: Bearer <token>
```

Token resolution precedence (evaluated at construction time):

1. `api_key` constructor argument — explicit value takes highest priority.
2. `CODEX_SERVER_API_KEY` environment variable — primary env-var source.
3. `OPENAI_API_KEY` environment variable — global fallback.

If none of the above yields a non-empty string, `AgentConfigError` is raised immediately and no
connection is attempted.

**Security constraints (contract-matrix §2):**

- The resolved token MUST NOT appear in any log entry, action-log item, or API response.
- `401 Unauthorized` responses MUST be mapped to `AgentExecutionError` with a redacted message
  (no token value in the message string).
- `403 Forbidden` responses MUST be mapped to `AgentExecutionError` with a redacted message.

### Authentication Mode Comparison

| Aspect | Local (`codex_server`) | Remote (`codex_server_remote`) |
|--------|----------------------|-------------------------------|
| Transport | stdio (loopback) | WebSocket over HTTPS (`wss://`) |
| Auth required | No (loopback trust) | Yes — `Authorization: Bearer <token>` |
| Token source | N/A | `api_key` arg → `CODEX_SERVER_API_KEY` env → `OPENAI_API_KEY` env |
| Session setup | `account/login/start` with API key | Bearer token on WebSocket upgrade handshake |
| Token in logs | Not applicable | **Never** — must be redacted |

---

## 6. Complete Client Interaction Sequence

The following is the expected full lifecycle for one builder/verifier session:

```
Client                                  Codex App Server
  |                                           |
  |-- account/login/start (local only) ------>|
  |<- result: {type: "apiKey"} ---------------|
  |                                           |
  |-- thread/start --------------------------->|
  |<- result: {thread: {id: "thr_..."}} ------|
  |                                           |
  |-- turn/start (with full prompt) ---------->|
  |<- result: {turn: {id: "turn_...", status: "inProgress"}} --|
  |                                           |
  |<- item/started {type: "agentMessage"} ----|  (streaming begins)
  |<- item/agentMessage/delta ... ------------|
  |<- item/completed {type: "agentMessage"} --|
  |                                           |
  |<- item/started {type: "mcpToolCall",      |  (agent calls update_checklist)
  |     toolName: "update_checklist",         |
  |     input: {req_id: "R-01", ...}} --------|
  |<- item/completed {type: "mcpToolCall"} ---|
  |                                           |
  |<- item/started {type: "mcpToolCall",      |  (agent calls submit)
  |     toolName: "submit", input: {}} --------|
  |<- item/completed {type: "mcpToolCall"} ---|
  |                                           |
  |<- turn/completed {status: "completed"} ---|  (session done)
```

---

## 7. Transport Configuration Reference

### Starting the Local Server

```bash
codex app-server --listen stdio://
```

### Starting with WebSocket Transport

```bash
codex app-server --listen ws://127.0.0.1:9000
```

### Generating Type Definitions

The Codex CLI can emit TypeScript or JSON Schema type definitions for the full JSON-RPC message
set:

```bash
codex app-server generate-ts --out /path/to/types/
codex app-server generate-json-schema --out /path/to/schemas/
```

Use these generated definitions as the authoritative schema reference when implementing the
transport layer.

### Backpressure Handling

If the server's request queue is full it returns JSON-RPC error code `-32001` with message
`"Server overloaded; retry later."` Use exponential back-off before retrying.

---

## 8. V1 Tool Allow-List

Per contract-matrix §4, only the following tools may be registered with the Codex server in v1
sessions.  Any invocation outside this list MUST be rejected by `enforce_tool_allowlist` with a
logged warning and must NOT reach the orchestrator callbacks.

| Tool Name | Phase | Description |
|-----------|-------|-------------|
| `update_checklist` | Builder | Mark a requirement as done, blocked, or not_applicable |
| `grade` | Verifier | Set a grade on a requirement |
| `submit` | Both | Submit work / complete verification |
| `request_clarification` | Both | Request clarification on ambiguous requirements |

---

## 9. Known Ambiguities and Open Questions

The following items require clarification or runtime verification before the transport
implementation can be considered complete.  They correspond to open risks in
`docs/codex-server/context/open-risks.md`.

| Item | Risk | Reference |
|------|------|-----------|
| Exact `serverId` value used for dynamically-registered tools | R-01 (payload drift) | R-01 |
| Whether `toolName` or `tool` is the canonical field name for `mcpToolCall` vs `collabToolCall` | R-01 | R-01 |
| Precise WebSocket upgrade header format for bearer auth on remote variant | R-02 | R-02 |
| Whether `turn/completed` is always the last notification, or if a thread-level terminal event follows | R-01 | R-01 |
| Token usage fields in `turn/completed.tokenUsage` — exact names and whether `tokens_cache` is reported | R-01 | R-01 |

These items should be resolved by running the live server and observing the wire protocol, or by
referencing the generated JSON Schema output from `codex app-server generate-json-schema`.

---

## 10. References

- [Codex App Server documentation](https://developers.openai.com/codex/app-server/) — primary spec
- [`openai/codex` GitHub repository](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) — implementation reference
- `docs/codex-server/context/contract-matrix.md` — binding integration decisions
- `docs/codex-server/context/open-risks.md` — open risks and mitigations
- `src/orchestrator/agents/codex_server.py` — local agent stub
- `src/orchestrator/agents/codex_server_remote.py` — remote agent stub
- `src/orchestrator/agents/codex_server_common.py` — shared helpers (allow-list, prompt, normalization)
