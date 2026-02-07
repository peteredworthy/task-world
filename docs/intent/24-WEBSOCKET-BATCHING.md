# WebSocket Event Batching

## Overview

WebSocket event batching reduces message floods by collecting events within a configurable time window and sending them as a single batch message. This improves performance under heavy load while maintaining near-real-time updates.

## Implementation

### BatchingConnectionManager

Location: `src/orchestrator/api/websocket.py`

The `BatchingConnectionManager` extends `ConnectionManager` with optional batching capability:

- **Batching enabled (default)**: Events are collected for a configurable window (default 100ms) and sent as a batch
- **Batching disabled**: Falls back to immediate broadcast with per-client throttling (same as `ConnectionManager`)

### Configuration

Batching is controlled via global config (`~/.orchestrator/config.yaml`):

```yaml
websocket:
  batching_enabled: true       # Enable event batching (default: true)
  batch_window_seconds: 0.1    # Collect events for 100ms before sending (default: 0.1)
```

### Batch Message Format

When batching is enabled, clients receive messages in the following format:

```json
{
  "type": "batch",
  "run_id": "run-abc123",
  "count": 3,
  "events": [
    {"event_type": "task_status_changed", "task_id": "T-01", ...},
    {"event_type": "checklist_gate_evaluated", "task_id": "T-01", ...},
    {"event_type": "run_status_changed", ...}
  ]
}
```

When batching is disabled, clients receive individual event messages as before.

## Architecture

### Per-Run Buffers

- Each run has its own event buffer and timer
- Events for different runs never interfere with each other
- Buffers are automatically cleaned up when no subscribers remain

### Timer Management

- When first event arrives for a run, a timer is started
- Additional events within the window are added to the buffer
- When timer expires, all buffered events are sent as a batch
- Timer is reset if buffer is flushed manually

### Thread Safety

- All buffer access is protected by an async lock
- Safe for concurrent broadcasts from multiple workflow events

### Interaction with Throttling

Batching works alongside the existing per-client throttling:

1. Events are collected in the batch buffer
2. After the batch window expires, the batch is broadcast
3. Per-client throttling (10 updates/sec) is applied to the batch message

This means under very heavy load, some batches may be dropped per client (same behavior as before, but now dropping batches instead of individual events).

## API

### Key Methods

**`broadcast_to_run(run_id: str, data: dict[str, Any])`**
- Batching enabled: Adds event to buffer, starts/resets timer
- Batching disabled: Broadcasts immediately (same as parent)

**`broadcast_event(event: object)`**
- Serializes dataclass event and calls `broadcast_to_run`
- Inherits batching behavior from `broadcast_to_run`

**`flush_all()`**
- Immediately sends all pending batches for all runs
- Useful for graceful shutdown or testing
- Cancels pending timers

**`disconnect(run_id: str, websocket: WebSocket)`**
- Cleans up buffers and timers when no subscribers remain
- Calls parent's disconnect for connection cleanup

## Testing

Location: `tests/integration/test_api_websocket.py`

Seven comprehensive tests verify batching behavior:

1. **test_batching_manager_disabled_mode**: Batching disabled works like regular ConnectionManager
2. **test_batching_collects_events_within_window**: Multiple events are batched correctly
3. **test_batching_multiple_runs_independent**: Different runs batch independently
4. **test_batching_flush_all**: Manual flush sends pending batches immediately
5. **test_batching_event_broadcast**: `broadcast_event()` works with batching
6. **test_batching_disconnect_cleans_up**: Cleanup happens on disconnect
7. **test_batching_respects_per_client_throttle**: Batches respect per-client throttling

All tests use mock WebSocket objects to avoid actual network I/O.

## Usage Example

### Frontend (JavaScript/TypeScript)

```typescript
const ws = new WebSocket('ws://localhost:8000/ws/runs/run-123');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === 'batch') {
    // Batching enabled - process multiple events
    console.log(`Received batch of ${data.count} events for run ${data.run_id}`);
    data.events.forEach(evt => handleEvent(evt));
  } else {
    // Batching disabled - process single event
    handleEvent(data);
  }
};
```

### Backend (Python)

```python
from orchestrator.api.app import create_app

# Default: batching enabled with 100ms window
app = create_app(db_path="orchestrator.db")

# Access the manager
manager = app.state.connection_manager  # BatchingConnectionManager

# Broadcast events (batching is automatic)
await manager.broadcast_to_run("run-123", {"event_type": "test"})

# Flush pending batches (e.g., during shutdown)
await manager.flush_all()
```

## Performance Considerations

### Benefits

- **Reduced message count**: Under heavy load, N events become 1 batch message
- **Better network efficiency**: Fewer WebSocket frames, less overhead
- **Preserved order**: Events within a batch maintain their order
- **Per-run isolation**: High activity in one run doesn't affect others

### Trade-offs

- **Increased latency**: Events are delayed by up to `batch_window_seconds` (default 100ms)
- **Memory overhead**: Small buffer per active run (negligible unless thousands of runs)
- **Complexity**: Clients must handle both batch and single-event formats

### When to Disable Batching

Disable batching if:
- You need truly real-time updates (< 100ms latency)
- Your event rate is very low (< 10 events/sec)
- Your frontend can't handle batch message format

Set `websocket.batching_enabled: false` in global config to disable.

## Future Enhancements

Potential improvements:

1. **Adaptive batching**: Adjust window size based on event rate
2. **Size-based flushing**: Flush when batch reaches N events, regardless of time
3. **Priority events**: Some events bypass batching for immediate delivery
4. **Compression**: Compress batch messages for large batches
5. **Per-run configuration**: Different batch windows for different runs
