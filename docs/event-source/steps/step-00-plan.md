# Step 0: Pydantic Event Conversion

**Milestone:** M0 — Pydantic Event Conversion (Preparatory)
**Plan:** [step-00-plan.md](../step-00-plan.md)
**Architecture:** [architecture.md](../architecture.md) — all event types are Pydantic BaseModel subclasses before M1 begins
**Intent:** [intent.md](../intent.md) — [I-03a] convert existing event dataclasses to Pydantic; [I-22] Pydantic for all event and projection models

## Dry-Run Hardening Applied

- Use `Field(default_factory=lambda: datetime.now(timezone.utc))` for event timestamps; never bind
  `datetime.now(...)` at import time.
- Use `Field(default_factory=...)` for every list/dict field and add a verification grep for raw
  `= []` / `= {}` defaults in event models.
- Preserve every existing `event_type` value and add representative tests that assert serialized
  event type strings for status, task, output, and clarification events.
- Standardize serialization call sites on `model_dump(mode="json")` or `model_dump_json()` so
  enums and datetimes stay JSON-compatible across DB, JSONL, and WebSocket paths.
- Keep a public import smoke test through `orchestrator.workflow.events`; do not rely on external
  imports from the private `types.py` module.

## Tasks

### Task 0.1: Convert WorkflowEvent base and all subclasses to Pydantic BaseModel

Replace the `@dataclass` decorator on `WorkflowEvent` and all ~30 subclasses
in `types.py` with Pydantic `BaseModel` inheritance. Changes per class:

- `from dataclasses import dataclass, field` → `from pydantic import BaseModel, Field`
- `@dataclass` / `@dataclass(init=False)` decorators removed
- `field(default_factory=lambda: [])` → `Field(default_factory=list)`
- `field(default_factory=lambda: {})` → `Field(default_factory=dict)`
- `GradeDetail` (nested dataclass, not a `WorkflowEvent`) also converted

For `WorkflowEvent` base class: make `timestamp` optional with
`Field(default_factory=lambda: datetime.now(timezone.utc))` (mirrors the
existing custom `__init__` behavior in `ClarificationRequested` and
`ClarificationResponded`). Remove the custom `__init__` methods on those two
classes — Pydantic field defaults cover the same semantics.

`BufferingEmitter` is not a dataclass; leave it unchanged.

**Files:** `src/orchestrator/workflow/events/types.py`
**LOC estimate:** ~150
**Verify:** `python -c "from orchestrator.workflow.events.types import *"` imports
without error. `model_dump_json()` and `model_validate_json()` round-trip on
a manually constructed `RunStatusChanged` and `AgentOutputEvent` return the
correct JSON shape and reconstitute the correct object. `uv run pyright
src/orchestrator/workflow/events/types.py` passes.

### Task 0.2: Replace dataclasses.asdict with model_dump at serialization call sites

Two files call `dataclasses.asdict(event)` directly:

- `src/orchestrator/db/access/event_store.py` — `_serialize_event()` uses
  `dataclasses.asdict(event)`. Replace with `event.model_dump()` (Pydantic
  serializes enums and datetimes differently from `asdict`; align the
  `_json_default` helper if needed, or remove it and rely on
  `model_dump(mode="json")` which handles enums and datetimes natively).
- `src/orchestrator/api/websocket.py` — broadcast path calls
  `dataclasses.asdict(event)`. Replace with `event.model_dump(mode="json")`.

**Files:** `src/orchestrator/db/access/event_store.py`,
`src/orchestrator/api/websocket.py`
**LOC estimate:** ~15
**Verify:** `uv run pytest tests/unit/test_event_store.py
tests/integration/test_event_store.py` passes. WebSocket broadcast integration
test passes. JSON shapes produced by the new paths match the old JSONL journal
entries for `RunStatusChanged` and `TaskStatusChanged`.

### Task 0.3: Add Pydantic round-trip test suite

Create `tests/unit/test_pydantic_events.py` covering every concrete event
type defined in `types.py`. For each type:

1. Construct an instance with representative field values (not just defaults).
2. Serialize with `.model_dump_json()`.
3. Deserialize with `<EventType>.model_validate_json(json_str)`.
4. Assert the round-tripped instance equals the original (field-by-field).

Additionally assert:
- `model_dump(mode="json")` output contains no raw `datetime` objects (all
  timestamps are ISO 8601 strings).
- Enum fields (`RunStatus`, `TaskStatus`, `AgentRunnerType`) serialize to
  their `.value` string and deserialize back to the enum member.
- `GradeDetail` embedded in `GradesEvaluated.grade_details` round-trips
  correctly.

**Files:** `tests/unit/test_pydantic_events.py` (new)
**LOC estimate:** ~120
**Verify:** `uv run pytest tests/unit/test_pydantic_events.py` passes for
all event types. `uv run pytest` full suite passes with no regressions.
`uv run pyright` reports no new errors introduced by the Pydantic conversion.
