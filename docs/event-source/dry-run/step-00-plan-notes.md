# Step 00 Plan - Dry-Run Analysis Notes

## Summary

Step 00 is a preparatory migration that converts workflow events from dataclasses to
Pydantic models. It is a critical dependency for Step 01 because the new event store
serializes events with `model_dump_json()`. The plan is directionally correct, but the
dry run found several places where a mechanical conversion can silently break existing
journal, WebSocket, and equality behavior.

---

## Task 0.1: Convert WorkflowEvent base and subclasses to Pydantic BaseModel

### Assumptions

- Every concrete event currently inherits from `WorkflowEvent` in
  `src/orchestrator/workflow/events/types.py`.
- Call sites still construct events using keyword arguments, so a Pydantic conversion
  should not require broad constructor rewrites.
- The serialized event shape must remain compatible with the legacy JSONL reader during
  the transition.

### Failure Modes

**F0.1-A - Datetime default semantics can drift**

The dataclass implementation relied on default factories and a few custom constructors.
If `timestamp` is declared as `datetime = datetime.now(timezone.utc)`, every instance will
share the import-time timestamp. This is easy to miss because tests that only assert type
validity will still pass.

**Hardening**: Require `Field(default_factory=lambda: datetime.now(timezone.utc))` on the
base `WorkflowEvent.timestamp` field. Add a test that creates two events after advancing a
fake or real clock boundary and asserts their timestamps are not the same object/value.

**F0.1-B - Mutable defaults must use Field(default_factory=...)**

Several events carry lists and dictionaries. If any conversion uses `[]` or `{}` directly,
Pydantic v2 usually copies defaults, but relying on that behavior obscures intent and can
trip static analysis. The current plan already calls out list/dict replacements, but this
needs to be treated as mandatory for every nested container field.

**Hardening**: Extend the verification to grep for `= []` and `= {}` in `types.py` after
conversion. Any mutable collection default should be a `Field(default_factory=...)`.

**F0.1-C - Event type discriminators are not automatic**

Dataclass serialization stores `event_type` as a field. Pydantic subclasses will not infer
the subclass name unless `event_type` remains a concrete field/default on each event or is
provided by the base class plus existing subclass defaults. If it disappears, legacy event
store deserialization and activity filtering will break.

**Hardening**: Require every event instance to expose the same `event_type` value as before.
Add a table-driven test for representative events (`RunStatusChanged`, `TaskStatusChanged`,
`AgentOutputEvent`, `ClarificationRequested`) that checks `model_dump(mode="json")["event_type"]`.

**F0.1-D - Enum serialization can change from string to enum object**

Existing JSON consumers expect status and runner fields as strings. Pydantic `model_dump()`
without `mode="json"` can preserve enum objects, while `model_dump(mode="json")` emits string
values. Mixed use across call sites can produce inconsistent payloads.

**Hardening**: In all serialization paths, use `model_dump(mode="json")` or
`model_dump_json()`. Add tests that assert `RunStatus.ACTIVE` serializes as `"active"` and
round-trips back to the enum member.

---

## Task 0.2: Replace dataclasses.asdict with model_dump at serialization call sites

### Failure Modes

**F0.2-A - Legacy EventStore payload shape can diverge from JSONL shape**

`src/orchestrator/db/access/event_store.py` and `src/orchestrator/api/websocket.py` currently
depend on dataclass conversion. If one call site switches to `model_dump()` and another uses
`model_dump(mode="json")`, journal records and WebSocket payloads can differ for datetimes and
enums.

**Hardening**: Standardize on `event.model_dump(mode="json")` for dict payloads and
`event.model_dump_json()` for persisted raw JSON. Keep one helper in the legacy event store so
future event serialization is not repeated ad hoc.

**F0.2-B - Type lookup during deserialization must be explicit**

The legacy event store reads `event_type` strings and reconstructs concrete classes. Pydantic
does not automatically choose a subclass from a base class. A simple `WorkflowEvent.model_validate`
would produce the base class and lose subclass fields.

**Hardening**: Preserve the existing event type registry or add an explicit map from
`event_type` to concrete model class. Include a round-trip test through the real legacy
`EventStore` path, not just through direct class validation.

---

## Task 0.3: Add Pydantic round-trip test suite

### Failure Modes

**F0.3-A - The test matrix can miss rarely used event classes**

If the round-trip suite is hand-written only for common events, Step 03 can later add command
events on top of an untested serialization pattern. The plan says every concrete event type
should be covered, which is the right target.

**Hardening**: Build the test list from the module exports or from `WorkflowEvent.__subclasses__()`
where practical, then require an explicit fixture constructor for each class. This makes newly
added events fail tests until they get serialization coverage.

**F0.3-B - Equality assertions can hide timezone normalization issues**

Pydantic may parse equivalent ISO timestamps into timezone-aware datetimes that compare equal
but serialize differently. Journal tooling is sensitive to the string format.

**Hardening**: In addition to field equality, assert the JSON output contains ISO-8601 strings
with UTC offsets and no raw datetime objects. Re-serialize the validated event and compare the
JSON-compatible dict shape.

---

## Cross-Cutting Concerns

### CC-0.1 - Import boundary

The plan references files inside `orchestrator.workflow.events.types.py`. External modules should
continue importing from `orchestrator.workflow.events` rather than reaching into `types.py`.

**Hardening**: Ensure all converted and newly added event classes are exported from
`src/orchestrator/workflow/events/__init__.py`. Add a smoke import from the top-level package.

### CC-0.2 - Compatibility with Step 01

Step 01's `SqliteEventStore` depends on `model_dump_json()`. If Step 00 is skipped or partially
completed, Step 01 will fail at runtime with `AttributeError`.

**Hardening**: Add a Step 01 prerequisite check that imports `RunStatusChanged`, constructs one,
and asserts `hasattr(event, "model_dump_json")`.

---

## Summary of Required Hardening Actions

| ID | Severity | Task | Action |
|----|----------|------|--------|
| F0.1-A | HIGH | 0.1 | Use a timestamp default factory, not an import-time value |
| F0.1-B | HIGH | 0.1 | Require `Field(default_factory=...)` for every mutable default |
| F0.1-C | HIGH | 0.1 | Preserve `event_type` values and test representative events |
| F0.1-D | HIGH | 0.1/0.2 | Standardize serialization on JSON mode |
| F0.2-A | HIGH | 0.2 | Keep legacy DB and WebSocket payload shapes aligned |
| F0.2-B | MED | 0.2 | Preserve explicit event type to model class lookup |
| F0.3-A | MED | 0.3 | Make newly added event classes require round-trip fixtures |
| CC-0.1 | MED | all | Export events from the public package API |
| CC-0.2 | HIGH | all | Add a Step 01 prerequisite check for `model_dump_json()` |
