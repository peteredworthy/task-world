# Codex Server: threadId Tracking and Future Parallelism

**Purpose:** Design document for notification routing and threadId tracking to support current sequential execution and future parallel tasks.

---

## Why threadId Tracking Matters

The Codex JSON-RPC protocol includes `threadId` and `turnId` in all notifications. While the current architecture executes tasks sequentially (no demuxing needed), tracking threadId enables:

1. **Robustness** — Validate notifications belong to active thread
2. **Safety** — Detect stale/late notifications
3. **Debugging** — Better logging and error tracking
4. **Future Parallelism** — Infrastructure ready if tasks become parallel

---

## Codex Protocol Guarantees

From [official OpenAI documentation](https://developers.openai.com/codex/app-server/):

> "Notifications include `threadId` and/or `turnId` in their params to scope events to specific conversations and requests."

### Notification Format

All notifications include these fields in `params`:

```json
{
  "jsonrpc": "2.0",
  "method": "item/tool/call",
  "params": {
    "threadId": "thr_abc123def456",
    "turnId": "turn_xyz789",
    "item": {
      "type": "tool",
      "tool": "update_checklist",
      "arguments": {...}
    }
  }
}
```

### Notification Types Affected

All notification types include threadId:
- `item/agentMessage/delta` — threadId + turnId
- `item/started` — threadId + turnId
- `item/tool/call` — threadId + turnId
- `turn/completed` — threadId + turnId
- `thread/status/changed` — threadId

---

## Current Implementation Gap

The codebase doesn't extract `threadId` from notifications:

```python
# Current parsing (codex_server_common.py, line 92-122)
def extract_tool_call_from_notification(notification):
    params = notification.get("params", {})
    item = params.get("item", {})
    return {
        "type": item.get("type"),
        "tool": item.get("tool"),
        "arguments": item.get("arguments")
        # ❌ Ignores: params.threadId, params.turnId
    }
```

This works for current process-per-task architecture (only one thread per process), but should be improved when implementing process-per-run.

---

## Improved Design: Thread Tracking

### Data Structure

```python
class ThreadState:
    """Tracks state of a single thread/task execution."""

    def __init__(self, thread_id: str, task_id: str, context: ExecutionContext):
        self.thread_id = thread_id
        self.task_id = task_id
        self.context = context
        self.active = True
        self.pending_notifications: list[dict] = []
        self.completed_at: datetime | None = None


class CodexServerSession:
    """Manages Codex process for a run with thread tracking."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self._threads: dict[str, ThreadState] = {}  # threadId -> ThreadState
        self._active_thread_id: str | None = None
        self._completed_threads: list[str] = []

    async def create_task_thread(self, context: ExecutionContext) -> str:
        """Create thread and track it."""
        # ... create thread ...
        thread_id = response["result"]["thread"]["id"]

        # Track the thread
        self._threads[thread_id] = ThreadState(
            thread_id=thread_id,
            task_id=context.task_id,
            context=context
        )
        self._active_thread_id = thread_id

        return thread_id

    async def process_notification(self, notification: dict) -> ProcessedNotification:
        """Route notification to correct thread and validate threadId."""
        params = notification.get("params", {})
        thread_id = params.get("threadId")
        turn_id = params.get("turnId")
        method = notification.get("method", "")

        # Validate threadId
        if not self._validate_thread_id(thread_id):
            self._logger.error(f"Invalid threadId in {method}: {thread_id}")
            return None

        # Route to appropriate thread
        return self._route_notification(thread_id, method, params, turn_id)

    def _validate_thread_id(self, thread_id: str | None) -> bool:
        """Validate threadId is known and routing is correct."""
        if thread_id is None:
            self._logger.warning("Notification missing threadId")
            return False

        if thread_id not in self._threads:
            self._logger.error(f"Notification from unknown thread: {thread_id}")
            return False

        # In sequential mode, should match active thread
        if thread_id != self._active_thread_id:
            if thread_id in self._completed_threads:
                self._logger.warning(
                    f"Stale notification from completed thread {thread_id}"
                )
                return False  # Discard stale notification
            else:
                self._logger.warning(
                    f"Notification from inactive thread {thread_id}, "
                    f"active is {self._active_thread_id}"
                )
                return False

        return True

    def _route_notification(
        self,
        thread_id: str,
        method: str,
        params: dict,
        turn_id: str | None
    ) -> ProcessedNotification:
        """Route and process notification for the thread."""
        thread_state = self._threads[thread_id]

        # Log with thread context
        self._log_notification(thread_id, turn_id, method)

        if method == "turn/completed":
            return ProcessedNotification(
                type="turn_completed",
                thread_id=thread_id,
                turn_id=turn_id,
                status=params.get("turn", {}).get("status")
            )

        elif method == "item/tool/call":
            item = params.get("item", {})
            return ProcessedNotification(
                type="tool_call",
                thread_id=thread_id,
                turn_id=turn_id,
                tool_name=item.get("tool"),
                arguments=item.get("arguments")
            )

        elif method == "item/agentMessage/delta":
            return ProcessedNotification(
                type="message_delta",
                thread_id=thread_id,
                turn_id=turn_id,
                delta=params.get("delta")
            )

        else:
            self._logger.debug(f"Ignoring notification type: {method}")
            return None

    def _log_notification(
        self,
        thread_id: str,
        turn_id: str | None,
        method: str
    ):
        """Log notification with thread/turn context."""
        task_id = self._threads[thread_id].task_id
        self._logger.debug(
            f"Notification: {method} (task={task_id}, thread={thread_id}, turn={turn_id})"
        )

    async def finalize_thread(self, thread_id: str):
        """Mark thread as completed after all notifications received."""
        if thread_id in self._threads:
            self._threads[thread_id].completed_at = datetime.now()
            self._completed_threads.append(thread_id)
            self._threads[thread_id].active = False
```

---

## Notification Processing Flow

```
┌─ Receive notification on stdout
│
├─ Extract threadId and turnId
│
├─ Validate threadId
│  ├─ ❌ Unknown threadId → log error, discard
│  ├─ ❌ Stale (completed thread) → log warning, discard
│  └─ ✅ Valid and active → process
│
├─ Route to correct thread handler
│
├─ Parse method-specific data
│  ├─ turn/completed → status
│  ├─ item/tool/call → tool_name, arguments
│  └─ item/agentMessage/delta → delta text
│
└─ Return ProcessedNotification with context
```

---

## Logging Strategy

With threadId tracking, logs become much more useful:

### Current (Without threadId)
```
[DEBUG] Tool called: update_checklist
[DEBUG] Arguments: {"item": "req-123", "status": "done"}
[ERROR] Unexpected token in response
```

### Improved (With threadId)
```
[DEBUG] Notification: item/tool/call (task=task-456, thread=thr_abc, turn=turn_xyz)
        Tool: update_checklist, Args: {"item": "req-123", "status": "done"}
[DEBUG] Notification: turn/completed (task=task-456, thread=thr_abc, turn=turn_xyz)
        Status: completed
[ERROR] Notification from unknown thread: thr_unknown
        Active thread: thr_abc, Known threads: [thr_abc]
```

---

## Future: Parallel Task Support

When executor is extended for parallel tasks, notification routing is ready:

```python
async def process_parallel_notifications(session: CodexServerSession):
    """
    Read notifications from a Codex process handling multiple threads.
    Routes each to the correct thread handler.
    """
    pending_executions: dict[str, asyncio.Task] = {}  # task_id -> execution task

    while True:
        # Check for new tasks to start
        task = session.find_next_pending_task()
        if task:
            thread_id = await session.create_task_thread(task.context)
            execution = asyncio.create_task(
                session.execute_thread(thread_id)
            )
            pending_executions[task.id] = execution

        # Read any notification and route to correct thread
        notification = await session.recv_notification()

        result = await session.process_notification(notification)
        if result.type == "turn_completed":
            # Signal the thread handler that turn is done
            await session.complete_thread(result.thread_id, result.status)

        # Check if any tasks completed
        done_tasks = []
        for task_id, execution in pending_executions.items():
            if execution.done():
                await execution  # Get result
                done_tasks.append(task_id)

        for task_id in done_tasks:
            del pending_executions[task_id]

        # Continue until all pending tasks complete
        if not pending_executions and not task:
            break
```

The threadId-based routing already handles distributing notifications to the correct thread, so parallelism becomes straightforward.

---

## Test Fixtures

Update test notifications to include threadId/turnId:

```python
def _turn_completed(
    status: str = "completed",
    thread_id: str = "thr_test001",
    turn_id: str = "turn_test001"
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "turn/completed",
        "params": {
            "threadId": thread_id,      # ← Added
            "turnId": turn_id,           # ← Added
            "turn": {
                "id": turn_id,
                "status": status,
                "items": [],
                "error": None,
            }
        },
    }

def _agent_message_delta(
    text: str,
    item_id: str = "item_msg_001",
    thread_id: str = "thr_test001",
    turn_id: str = "turn_test001"
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "item/agentMessage/delta",
        "params": {
            "threadId": thread_id,      # ← Added
            "turnId": turn_id,           # ← Added
            "delta": text,
        },
    }

def _tool_call(
    tool: str,
    arguments: dict,
    thread_id: str = "thr_test001",
    turn_id: str = "turn_test001",
    item_id: str = "item_tool_001"
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "item/tool/call",
        "params": {
            "threadId": thread_id,      # ← Added
            "turnId": turn_id,           # ← Added
            "item": {
                "id": item_id,
                "type": "tool",
                "tool": tool,
                "arguments": arguments,
            }
        },
    }
```

---

## Implementation Checklist

- [ ] Update `codex_server_common.py` notification parsers to extract threadId/turnId
- [ ] Create `ThreadState` class to track thread metadata
- [ ] Update `CodexServerSession` to maintain active thread tracking
- [ ] Implement `_validate_thread_id()` with stale notification detection
- [ ] Implement `_route_notification()` with method-specific handling
- [ ] Add comprehensive logging with thread context
- [ ] Update all test fixtures to include threadId/turnId
- [ ] Add unit tests for threadId validation
- [ ] Add unit tests for stale notification detection
- [ ] Add integration tests for multi-task sequential execution
- [ ] Document parallelism path for future extension

---

## Benefits Summary

✅ **Current Sequential Execution:**
- Better validation and logging
- Detects and discards stale notifications
- Clear debugging of notification routing

✅ **Future Parallel Execution:**
- Notification routing already thread-aware
- Can implement parallel tasks without architectural changes
- Just update executor to manage multiple active threads

✅ **Robustness:**
- Validates all notifications against known threads
- Logs thread context for every notification
- Easy to detect anomalies or protocol errors

✅ **Maintainability:**
- Clear separation of concerns (notification routing vs. processing)
- Easy to add new notification types
- Extensible for future protocol changes
