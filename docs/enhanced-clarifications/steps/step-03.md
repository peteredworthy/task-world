# Step 03: WebSocket Push (10b)

Ensure that when a clarification is requested or responded to, a WebSocket event is broadcast to all connected clients immediately. This eliminates the 10-second polling delay and allows the frontend to react instantly. The existing 10s polling in `usePendingClarification` is preserved as a fallback.

## Intent Verification
**Original Intent**: `docs/enhanced-clarifications/intent.md` – "WebSocket push – `ClarificationRequested` events broadcast immediately so the UI reacts without waiting for the 10s poll cycle"

**Functionality to Produce**:
- `ClarificationRequested` and `ClarificationResponded` events are broadcast to WebSocket clients
- `ClarificationRequested` payload includes at minimum `task_id`, `request_id`, and `question_count`
- `ClarificationResponded` payload includes at minimum `task_id` and `request_id`
- No full question/answer payload in the WS message (minimal payload per Q4 decision)

**Final Verification Criteria**:
- Integration test for `clarification_requested` WS message passes
- Integration test for `clarification_responded` WS message passes
- `mypy` reports no errors on `events.py` and `websocket.py`
- Existing WS broadcast tests for other event types continue to pass

---

## Task 1: Audit and update ClarificationRequested event dataclass

**Description**: Ensure `ClarificationRequested` has all required fields including `question_count` and a forward-compatible `questions` list.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/workflow/events.py` and read it fully.
- [ ] Locate the `ClarificationRequested` dataclass. Verify it has `run_id`, `task_id`, and `request_id` fields.
- [ ] If `question_count: int` is missing, add it:
```python
@dataclass
class ClarificationRequested:
    run_id: str
    task_id: str
    request_id: str
    question_count: int
    questions: list[dict] = field(default_factory=list)  # forward-compat; empty by default
```
- [ ] Verify `ClarificationResponded` has `run_id`, `task_id`, and `request_id`. Add `run_id` or `task_id` if missing (check usage in the rest of the codebase first to avoid breaking changes):
```python
@dataclass
class ClarificationResponded:
    run_id: str
    task_id: str
    request_id: str
```
- [ ] Find wherever `ClarificationRequested` is instantiated (likely `workflow/service.py` `request_clarification`). Pass `question_count=len(questions)` when constructing the event.

**Dependencies**
- [ ] Step 1 complete: `ClarificationRequested` dataclass exists and is stable.

**References**
- `docs/enhanced-clarifications/architecture.md` – "Modified Components: workflow/events.py"
- `docs/enhanced-clarifications/design-questions.md` – Q4 (minimal WS payload: IDs + counts only)
- `docs/enhanced-clarifications/step-03-plan.md` – Task 1

**Constraints**
- [ ] Only `ClarificationRequested` and `ClarificationResponded` dataclasses in `events.py` may change.
- [ ] Changes must be backward-compatible with existing event consumers.
- [ ] Do not populate `questions` list—leave it empty (forward-compat only).

**Side Effects**
- [ ] Any existing test that constructs `ClarificationRequested` must be updated to pass `question_count`.

**Functionality (Expected Outcomes)**
- [ ] `ClarificationRequested(run_id='r1', task_id='t1', request_id='req1', question_count=2)` instantiates without error
- [ ] `ClarificationResponded(run_id='r1', task_id='t1', request_id='req1')` instantiates without error

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `mypy src/orchestrator/workflow/events.py` reports no errors
- [ ] `ruff check src/orchestrator/workflow/events.py` reports no errors
- [ ] Existing tests that use these dataclasses still pass

---

## Task 2: Verify and add WebSocket broadcast for clarification events

**Description**: Confirm the WS broadcaster serializes `ClarificationRequested` and `ClarificationResponded` events; add serialization branches if missing.

**Implementation Plan (Do These Steps)**

- [ ] Open `src/orchestrator/api/websocket.py` (or the equivalent file containing the WS broadcaster). Read it fully.
- [ ] Find the section where events are serialized and broadcast to connected clients (likely a `match`/`if-elif` block on `event_type` or a generic serializer).
- [ ] If there is no branch for `ClarificationRequested`, add:
```python
elif isinstance(event, ClarificationRequested):
    payload = {
        "event_type": "clarification_requested",
        "run_id": event.run_id,
        "task_id": event.task_id,
        "request_id": event.request_id,
        "question_count": event.question_count,
    }
    await broadcast_to_run(event.run_id, payload)
```
- [ ] If there is no branch for `ClarificationResponded`, add:
```python
elif isinstance(event, ClarificationResponded):
    payload = {
        "event_type": "clarification_responded",
        "run_id": event.run_id,
        "task_id": event.task_id,
        "request_id": event.request_id,
    }
    await broadcast_to_run(event.run_id, payload)
```
  Adapt `broadcast_to_run` to the actual broadcast function name used in the codebase.
- [ ] Confirm that disconnected clients are handled silently (the existing exception-swallowing pattern for disconnected WS clients should already cover this).

**References**
- `docs/enhanced-clarifications/architecture.md` – "Interactions" diagram; WS payload spec
- `docs/enhanced-clarifications/step-03-plan.md` – Tasks 2 and 3

**Constraints**
- [ ] Only add new serialization branches; do not modify existing branches.
- [ ] Do not change the WS connection management logic.
- [ ] Payload must be minimal (IDs + counts only, per Q4). Do not include full question text.

**Functionality (Expected Outcomes)**
- [ ] After `request_clarification` is called, the WS broadcaster emits a message with `event_type='clarification_requested'`
- [ ] After `respond_to_clarification` is called, the WS broadcaster emits a message with `event_type='clarification_responded'`
- [ ] A disconnected client does not cause an unhandled exception

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `mypy src/orchestrator/api/websocket.py` reports no errors
- [ ] `ruff check src/orchestrator/api/websocket.py` reports no errors

---

## Task 3: Write integration tests for WS clarification events

**Description**: Verify that the correct WS messages are received when clarification events fire.

**Implementation Plan (Do These Steps)**

- [ ] Find the existing WS integration test file (likely `tests/integration/test_websocket.py` or in `test_api_runs.py`). Read patterns for how WS messages are captured in tests.
- [ ] Add a test for `clarification_requested`:
```python
async def test_ws_clarification_requested(client, run_with_task):
    run_id, task_id = run_with_task
    ws_messages = []
    async with client.websocket_connect(f"/ws/runs/{run_id}") as ws:
        # Trigger a clarification POST
        resp = client.post(
            f"/api/runs/{run_id}/tasks/{task_id}/clarifications",
            json={...valid multi-select payload...}
        )
        assert resp.status_code == 201
        msg = await ws.receive_json(timeout=2)
        ws_messages.append(msg)
    assert any(m.get("event_type") == "clarification_requested" for m in ws_messages)
    cl_msg = next(m for m in ws_messages if m.get("event_type") == "clarification_requested")
    assert cl_msg["task_id"] == task_id
    assert cl_msg["question_count"] >= 1
```
- [ ] Add a test for `clarification_responded` using a similar pattern: POST the response, capture the WS message, assert `event_type='clarification_responded'`, `task_id`, and `request_id` are present.

**References**
- `docs/enhanced-clarifications/step-03-plan.md` – Tasks 4 and 5, Verification

**Functionality (Expected Outcomes)**
- [ ] WS test for `clarification_requested` passes
- [ ] WS test for `clarification_responded` passes
- [ ] Existing WS tests still pass

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `pytest tests/integration/ -k ws_clarification -v` all green
- [ ] Existing WS broadcast tests continue to pass
