# Working with Codex App Server (Codex Server) in our Orchestrator

This canvas summarizes a clean, safe integration approach that treats Codex App Server as a first-class backend alongside existing agents (CodexCLI/OpenCode/ClaudeCLI/OpenHands).

---

## 1) Availability & Health Checks

### Goals
- Fail fast if Codex Server is not present / mismatched.
- Capture version + capabilities so orchestration remains deterministic.

### Recommended checks
1. **Binary present**
   - Verify `codex` is installed and executable in the target runtime.
2. **Start app-server**
   - Launch `codex app-server` using stdio transport (JSON-RPC over JSONL) unless you explicitly need WebSocket.
3. **Initialize handshake**
   - Call `initialize` and confirm:
     - Protocol compatibility
     - Supported capabilities
     - Whether **experimental** API capabilities are enabled (required for `dynamicTools` and `tool/requestUserInput`).
4. **Sanity exec**
   - Run a minimal no-op or `command/exec` (e.g., `pwd`) to confirm command execution works in the sandbox policy you plan to use.

### Health-state record
Persist a single “backend capability” record per process:
- codex version
- app-server protocol version
- experimentalApi enabled?
- sandbox policy defaults

---

## 2) Add Two Agent Types

Add two new agent types to the orchestrator so Codex integrates like OpenHands + OpenHands Docker:

### A) **Codex Server** (controller agent)
**Purpose**: long-lived thread/session manager and interaction surface.
- Owns:
  - thread lifecycle (start/resume/fork/archive)
  - turn lifecycle (start/cancel)
  - event stream ingestion (items, deltas, completions)
  - tool hosting for orchestrator-owned tools (via experimental tools interface)

### B) **Codex Server Sandbox** (execution agent)
**Purpose**: deterministic execution wrapper for direct command/file operations.
- Primary calls:
  - `command/exec` for deterministic “run this” operations (tests, grep, format, etc.)
- Secondary:
  - Used by Codex Server agent for environment checks and preflight verification.

**Why two types?**
- Keeps the mental model consistent with existing “agent + sandbox” separation.
- Allows tighter permissions: Sandbox agent can be locked down to command execution and telemetry; Codex Server agent is for interactive/agent turns and tool calls.

---

## 3) Use the Experimental Tools Interface (Dynamic Tools)

### Objective
Provide Codex with orchestrator tools without opening new inbound network paths from sandbox ➜ orchestrator.

### Mechanism
- Use **experimental `dynamicTools`** on `thread/start` (and potentially `thread/resume`).
- Tools execute on the orchestrator side:
  - Codex requests a tool call
  - orchestrator executes
  - orchestrator returns results

### Tool parity with OpenHands
For **both Codex Server and Codex Server Sandbox**, provide the same “orchestration tools” as OpenHands/OpenHands Docker so capability is consistent across backends:

**Tool groups to include**
1. **Requirements / To-Do / Work items**
   - list requirements
   - add requirement
   - mark satisfied / unsatisfied
   - attach evidence (links, command outputs, diffs)

2. **Grading / Verification**
   - run grading rubric
   - return pass/fail + reasons
   - return missing requirements (“gaps”) in a structured form

3. **Task Graph / Orchestration**
   - get current task
   - enqueue follow-up task
   - publish task status
   - request approval for state transitions

4. **State & Memory**
   - read orchestrator state snapshot
   - write minimal state deltas
   - attach artifacts (patches, logs)

### Safety and governance rules
- **Per-thread tool allowlist**: only expose tools required for that task.
- **Schema validation**: hard-validate tool input to prevent prompt injection by argument.
- **Idempotency**: de-dupe tool calls by `(threadId, turnId, callId)`.
- **AuthZ scope**: issue a per-thread capability token and require it in tool arguments.
- **Timeouts**: return structured errors quickly; avoid wedging schedulers.

---

## 4) Map Codex Event Stream into Our Implementation-Agnostic History

### Goal
Codex emits rich, event-based “items”. We want a single normalized history model across:
- Codex Server
- Codex CLI
- OpenHands
- Claude/OpenCode

### Recommended mapping
Treat Codex App Server events as the source-of-truth timeline and translate to our common event schema.

**Codex concepts ➜ Our concepts**
- **Thread** ➜ `RunContext` (or `ConversationContext`)
- **Turn** ➜ `RunStep` (one orchestrator step with a bounded objective)
- **Item** ➜ `HistoryEvent`

**Item types to normalize**
1. Agent text
   - streaming delta ➜ append to same `message_id`
   - completed message ➜ finalize

2. Tool calls
   - `tool_call_requested` ➜ `ToolInvocationStarted`
   - tool result ➜ `ToolInvocationCompleted`

3. Command execution
   - start ➜ `CommandStarted`
   - output streaming ➜ `CommandOutputDelta`
   - end ➜ `CommandCompleted` (exit code, duration, stdout/stderr refs)

4. File changes
   - patch/diff events ➜ `FilePatchProposed`
   - committed changes (if applicable) ➜ `FilePatchApplied`

5. Approvals / policy gates
   - approval request ➜ `ApprovalRequested`
   - allow/deny ➜ `ApprovalResolved`

6. Completion
   - turn completed ➜ `RunStepCompleted` (status, summary, artifacts)

### Storage guidance
- Store normalized history as the canonical record.
- Keep raw Codex items as an optional “debug blob” for fidelity.

---

## 5) Practical Workflow Template

### Thread lifecycle
1. Start Codex Server
2. Initialize (experimental enabled)
3. `thread/start` with:
   - sandboxPolicy
   - cwd/worktree identifier
   - dynamicTools allowlist for this task
4. For each orchestrator step:
   - `turn/start` with a clear objective
   - stream items
   - normalize to our history
   - run verifier/grader tools
   - enqueue gaps as new tasks (if needed)
5. Archive thread when done

### Sandbox lifecycle
- Use Codex Server Sandbox (`command/exec`) for deterministic operations.
- Prefer deterministic runs for:
  - tests
  - formatting
  - grep/search
  - build
  - static analysis

---

## 6) Notes / Known Limitations

- Codex UI “TODO list” is not a documented API surface. Treat the orchestrator requirements/tasks list as the system of record.
- `dynamicTools` and `tool/requestUserInput` are experimental; guard with capability checks and feature flags.

---

## 7) Next Implementation Tasks

- [ ] Add `CodexServerBackend` and `CodexServerSandboxBackend` adapters
- [ ] Implement app-server health check + capability record
- [ ] Implement dynamicTools tool host:
  - call routing
  - schema validation
  - idempotency
  - per-thread allowlist
- [ ] Implement event normalizer: Codex item stream ➜ common history
- [ ] Add parity tool set (requirements + grading + task graph) consistent with OpenHands
- [ ] Add integration tests: start server, run turn, tool call, command/exec, normalize history

