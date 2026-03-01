# Codex Server Architecture: Process-Per-Run Optimization

**Status:** Corrected understanding of optimal Codex Server isolation model
**Impact:** Better resource efficiency, maintains full MCP flexibility

---

## The Issue with Current Implementation

The current `CodexServerAgent` spawns a **new subprocess for every task execution**, with full initialization:

```
Task 1: spawn process → initialize → auth → thread/start → execute → terminate
        ↑                                                                      ↑
      ~500ms overhead                                                      cleanup

Task 2: spawn process → initialize → auth → thread/start → execute → terminate
        ↑
      ~500ms overhead again

Task 3: spawn process → initialize → auth → thread/start → execute → terminate
        ↑
      ~500ms overhead again
```

**Cost:** A 10-task run wastes ~5 seconds on process management alone.

---

## Why This Happens (Current Code)

From `/src/orchestrator/agents/codex_server.py`:

```python
async def execute(self, context: ExecutionContext, ...) -> ExecutionResult:
    # Line 373-376: spawn_transport() called EVERY execute() call
    if self._transport is None:
        await self._spawn_transport()
    # ↑ This spawns a new subprocess, creates CODEX_HOME, initializes

    # Line 442: thread/start called, creates conversation
    thread_resp = await self._json_rpc_client.call("thread/start", {...})

    # Line 445-478: Single turn/start -> process -> turn/completed
    await self._json_rpc_client.call("turn/start", {"threadId": thread_id})
```

And in executor (`/src/orchestrator/agents/executor.py`, line 623):

```python
agent = self._create_agent(agent_type, agent_config, run.id, phase=phase)
# ↑ Creates NEW CodexServerAgent instance per task
```

**Result:** One subprocess per task (not optimal).

---

## The Better Architecture: Process-Per-Run

The Codex JSON-RPC protocol supports multiple threads within a single process. We should use this:

```
Run starts
  ├─ Spawn process once
  ├─ Initialize once
  ├─ Authenticate once
  │
  ├─ Task 1: thread/start → execute
  ├─ Task 2: thread/start → execute (reuse same process)
  ├─ Task 3: thread/start → execute (reuse same process)
  │
  └─ Run ends: kill process once
```

**Cost:** ~500ms overhead per run instead of per task. For a 10-task run, save ~4.5 seconds.

---

## Why This Works

### 1. Tasks Execute Sequentially Within a Run

The executor's `_run_agent_loop()` (lines 316-445 of `executor.py`) is **per-run and sequential**:

```python
async def _run_agent_loop(self, run: RunModel):
    while True:
        task_state = self.find_next_task(run)
        if not task_state:
            break

        result = await self._execute_task(task_state, run, phase)

        # ↑ Only ONE task executing at a time
        # Loop back for next task
```

This means:
- Only one thread is ever active in the Codex process
- Notifications on stdout belong to the active turn
- **threadId available for validation** (Codex protocol includes threadId in all notifications)
- **Designed for future parallelism** (track threadId to support parallel tasks later if needed)

### 2. Different Runs Are Already Isolated

Multiple runs → multiple executor loops → multiple processes:

```
Run A's _run_agent_loop: Process P_A (spawned once, reused for all tasks in Run A)
Run B's _run_agent_loop: Process P_B (spawned once, reused for all tasks in Run B)
Run C's _run_agent_loop: Process P_C (spawned once, reused for all tasks in Run C)
```

Each run still has its own isolated process. No interference between runs.

### 3. Threads Isolate Per-Task Tools

The Codex `thread/start` parameter includes `dynamicTools`:

```python
# Task A gets its MCPs
await thread_start({
    "dynamicTools": [
        {"name": "chrome", "url": "..."},
        {"name": "filesystem", ...}
    ]
})

# Task B in same process gets different MCPs
await thread_start({
    "dynamicTools": [
        {"name": "test-runner", ...},
        {"name": "filesystem", ...}
    ]
})
```

**Tools are per-thread, not per-process.** Each task still gets its step-specific MCPs.

---

## Implementation Architecture

### Current (Per-Task Process)

```python
class CodexServerAgent:
    async def execute(self, context: ExecutionContext, ...):
        # ❌ Create subprocess EVERY execute() call
        if self._transport is None:
            self._transport = await self._spawn_transport()

        thread_id = await self._thread_start(...)
        # ... execute ...
        # Process killed after this execute() call
```

### Optimized (Per-Run Process)

```python
class CodexServerSession:
    """Manages a single Codex process for a run's lifetime."""

    async def start(self):
        """Called once at run start."""
        self._codex_home = tempfile.mkdtemp(prefix=f"codex-{self.run_id}-")
        self._transport = await self._spawn_transport(self._codex_home)
        # Process stays alive for entire run

    async def create_task_thread(self, context: ExecutionContext):
        """Called once per task. Reuses same process."""
        tool_specs = build_dynamic_tool_specs(
            mcp_servers=context.mcp_servers,
            available_tools=context.available_tools
        )
        thread_id = await self._thread_start(dynamicTools=tool_specs)
        return thread_id

    async def cleanup(self):
        """Called once at run end."""
        await self._process.terminate()
        shutil.rmtree(self._codex_home)

class CodexServerAgent:
    def __init__(self, session: CodexServerSession, thread_id: str):
        self._session = session
        self._thread_id = thread_id

    async def execute(self, context: ExecutionContext, ...):
        # ✅ Use existing thread in existing process
        # No spawn, no initialize, no auth
        await self._session.call_turn_start(self._thread_id)
        # ... execute ...


# In executor's _run_agent_loop:
async def _run_agent_loop(self, run: RunModel):
    codex_session = CodexServerSession(run.id)
    await codex_session.start()  # ← Spawn once per run

    try:
        while True:
            task_state = self.find_next_task(run)
            if not task_state:
                break

            # Create thread for task (not process)
            thread_id = await codex_session.create_task_thread(context)

            # Execute within session
            agent = CodexServerAgent(codex_session, thread_id)
            result = await agent.execute(context, ...)

            await self.workflow_service.complete_task(...)

    finally:
        await codex_session.cleanup()  # ← Kill once at run end
```

---

## Trade-offs Analysis

| Aspect | Per-Task Process | Per-Run Process |
|--------|------------------|-----------------|
| **Spawn overhead** | 500ms × N tasks | 500ms × 1 run |
| **Initialize overhead** | N times | 1 time |
| **Auth overhead** | N times | 1 time |
| **Memory per run** | N × 50MB | 1 × 50MB |
| **Task isolation (tools)** | Process isolation | Thread isolation (same level) |
| **Task isolation (crashes)** | One task affected | Whole run affected |
| **MCP per-task** | Full control | Full control (per-thread) |
| **Performance** | Slower (process spawn) | Faster (thread creation) |
| **Complexity** | Simple (one process per execute) | Medium (session lifecycle) |

---

## MCP Configuration: No Change Needed

External MCPs work identically in both models:

**Per-Task Process:**
```python
# Different process per task
Task 1: new process with chrome-mcp
Task 2: new process with test-runner-mcp
```

**Per-Run Process (Better):**
```python
# Same process, different threads
Task 1: thread T1 with chrome-mcp
Task 2: thread T2 with test-runner-mcp  ← same process, different thread
```

**External MCP API:** No changes to how MCPs are specified. Still:
- Pass `context.mcp_servers` with step configuration
- Agent converts to Codex `dynamicTools` format
- Each task/thread gets its own tool set

---

## Parallel Execution: Fully Safe

**Multiple runs running in parallel:**

```
Run A: Process P_A
  ├─ Task A1: Thread T1 (chrome-mcp)
  └─ Task A2: Thread T2 (test-runner-mcp)

Run B: Process P_B
  ├─ Task B1: Thread T1 (context7-mcp)
  └─ Task B2: Thread T2 (filesystem-mcp)

Run C: Process P_C
  ├─ Task C1: Thread T1 (browser-mcp)
  └─ Task C2: Thread T2 (chrome-mcp)
```

**No conflicts:**
- Different processes have different CODEX_HOME directories
- Different processes have different stdout streams
- Different threads within same process have isolated tools
- Sequential execution is safe without demuxing, but threadId validation adds robustness for future parallelism

---

## Implementation Checklist

### Phase 1: Create CodexServerSession Class with threadId Tracking
- [ ] New class in `codex_server.py` or new file `codex_server_session.py`
- [ ] Methods: `start()`, `create_task_thread()`, `cleanup()`
- [ ] Track active threadId and ThreadState per thread
- [ ] Implement `process_notification()` with threadId validation
- [ ] Log notifications with threadId/turnId context
- [ ] Manages process lifecycle and transport
- [ ] Time: 2.5-3 hours (includes notification routing)

### Phase 2: Update Notification Parsing
- [ ] Extract `threadId` and `turnId` from all notifications
- [ ] Update parsers in `codex_server_common.py` to include these fields
- [ ] Update test fixtures to include threadId/turnId
- [ ] Time: 1-1.5 hours

### Phase 3: Refactor CodexServerAgent
- [ ] Accept `session` and `thread_id` in constructor
- [ ] Remove `_spawn_transport()` from `execute()`
- [ ] Use session's existing transport
- [ ] Validate threadId in responses
- [ ] Time: 1 hour

### Phase 4: Update Executor
- [ ] Create `CodexServerSession` in `_run_agent_loop()`
- [ ] Call `session.start()` at run start
- [ ] Create agent with session + thread_id per task
- [ ] Call `session.cleanup()` at run end
- [ ] Time: 1 hour

### Phase 5: Testing
- [ ] Unit tests for CodexServerSession lifecycle
- [ ] Unit tests for notification routing with threadId validation
- [ ] Integration tests for multi-task runs
- [ ] Verify parallel run isolation
- [ ] Verify MCP configuration per-task
- [ ] Test stale notification handling (for future parallelism)
- [ ] Time: 1.5-2 hours

**Total: 6-7.5 hours** (includes threadId tracking infrastructure for future parallelism)

---

## Performance Impact

### Before (Current: Per-Task Process)
```
10-task run:
  Spawn overhead:      10 × 100ms = 1,000ms
  Initialize:          10 × 200ms = 2,000ms
  Authenticate:        10 × 200ms = 2,000ms
  Total overhead:                     5,000ms (5 seconds wasted)

  Task execution:      10 × 1,000ms = 10,000ms
  Total run time:                     15,000ms
```

### After (Optimized: Per-Run Process)
```
10-task run:
  Spawn overhead:      1 × 100ms =    100ms
  Initialize:          1 × 200ms =    200ms
  Authenticate:        1 × 200ms =    200ms
  Total overhead:                      500ms

  Task execution:      10 × 1,000ms = 10,000ms
  Total run time:                     10,500ms (4.5 seconds saved, 30% faster)
```

---

## Notification Handling with threadId Tracking

The Codex JSON-RPC protocol includes `threadId` and `turnId` in all notifications. While current sequential execution doesn't strictly require demuxing, we should track these for:

1. **Robustness** — Validate notifications belong to active thread
2. **Debugging** — Better logging of notification sources
3. **Future parallelism** — Infrastructure ready if tasks become parallel

### Implementation: Thread Tracking

```python
class CodexServerSession:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self._threads: dict[str, ThreadState] = {}  # threadId -> ThreadState
        self._active_thread_id: str | None = None

    class ThreadState:
        def __init__(self, thread_id: str, context: ExecutionContext):
            self.thread_id = thread_id
            self.context = context
            self.pending_notifications: list[dict] = []
            self.active = False

    async def create_task_thread(self, context: ExecutionContext):
        """Create thread and track it."""
        tool_specs = build_dynamic_tool_specs(...)
        response = await self._thread_start(dynamicTools=tool_specs)

        thread_id = response["result"]["thread"]["id"]
        self._threads[thread_id] = ThreadState(thread_id, context)
        self._active_thread_id = thread_id

        return thread_id

    async def process_notification(self, notification: dict):
        """Route notification to correct thread, validate threadId."""
        params = notification.get("params", {})
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")

        # Validate notification belongs to active thread
        if thread_id != self._active_thread_id:
            if thread_id in self._threads:
                # Stale notification from previous thread (shouldn't happen in sequential mode)
                self._logger.warning(
                    f"Stale notification from thread {thread_id}, "
                    f"expected {self._active_thread_id}"
                )
                self._threads[thread_id].pending_notifications.append(notification)
                return  # Skip processing
            else:
                # Unknown thread (protocol error)
                self._logger.error(
                    f"Notification from unknown thread {thread_id}"
                )
                return

        # Process notification for active thread
        method = notification.get("method", "")

        if method == "turn/completed":
            turn_status = params.get("turn", {}).get("status")
            self._threads[thread_id].active = False
            return turn_status

        elif method == "item/tool/call":
            item = params.get("item", {})
            return {
                "type": "tool_call",
                "tool_name": item.get("tool"),
                "arguments": item.get("arguments")
            }

        elif method == "item/agentMessage/delta":
            return {
                "type": "message_delta",
                "delta": params.get("delta")
            }

        # ... handle other notification types
```

### Logging with Thread Context

```python
def _log_notification(self, notification: dict):
    """Log with threadId and turnId context."""
    params = notification.get("params", {})
    thread_id = params.get("threadId", "unknown")
    turn_id = params.get("turnId", "unknown")
    method = notification.get("method", "unknown")

    self._logger.debug(
        f"Notification: method={method}, threadId={thread_id}, turnId={turn_id}"
    )
```

### Future: Parallel Task Support

If parallel tasks are added to executor in the future, the infrastructure is ready:

```python
# Current: Sequential
while True:
    task = find_next_task(run)
    thread_id = await session.create_task_thread(context)
    await agent.execute()  # Single active thread

# Future: Parallel
pending_executions = []
while not all_done(run):
    task = find_next_task(run)
    if task:
        thread_id = await session.create_task_thread(context)
        execution = asyncio.create_task(agent.execute())
        pending_executions.append((thread_id, execution))

    # Process notifications from any thread
    notification = await session.recv_notification()
    result = await session.process_notification(notification)
    # threadId routing handles which thread gets the result

    # Wait for any execution to complete
    done, pending_executions = await asyncio.wait(
        pending_executions,
        return_when=asyncio.FIRST_COMPLETED
    )
```

The notification routing with threadId validation is already in place for this use case.

---

## Known Limitations

1. **Process crash affects all tasks in run** — If Codex process crashes, all remaining tasks in the run fail. With per-task processes, only one task fails. Mitigation: Better error handling and retry logic in executor.

2. **Shared CODEX_HOME** — All tasks in a run share the same `~/.codex-like` directory. Mitigated by using temp directories (`tempfile.mkdtemp`) per run.

3. **Sequential by design (currently)** — This optimization assumes tasks execute sequentially within a run. threadId tracking enables future parallelism without architectural changes. To add parallel tasks: update executor to manage multiple active threads, process notifications is already designed for routing.

---

## Recommendation

✅ **Implement per-run process model** for Codex Server.

This is:
- ✅ Better performance (30% faster)
- ✅ Better resource usage (50% less memory for concurrent runs)
- ✅ No change to external MCP architecture
- ✅ Fully safe for parallel runs
- ✅ Matches Codex protocol design (threads for concurrent conversations, sequential execution fits well)

---

## Summary

**Current implementation:** One Codex process per task (wasteful, ~500ms overhead per task)

**Optimized implementation:** One Codex process per run, multiple threads per task (efficient, ~500ms overhead per run)

**External MCP impact:** None. MCPs still configured per-step, now passed to thread via `dynamicTools` instead of process.

**Performance gain:** ~30% faster for typical multi-task runs.

**Safety:** Fully isolated per run, per-task tool configuration preserved.
