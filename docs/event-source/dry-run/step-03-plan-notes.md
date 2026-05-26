# Step 03 Plan - Dry-Run Analysis Notes

## Summary

Step 03 is the highest-risk step in the migration. It changes repository writes into command
handlers that emit events, adds creation events, and makes the existing repository read-only.
The plan has the right decomposition, but the dry run found places where partial conversion can
leave two competing write paths or make empty-DB rebuild impossible.

---

## Task 3.1: New event types for entity creation and mutations

### Failure Modes

**F3.1-A - Creation events may not contain enough state for empty-DB rebuild**

`RunCreated` and `TaskCreated` must include enough fields to reconstruct `RunModel`, `StepModel`,
`TaskModel`, checklist rows, fan-out parent links, and routine metadata. The provided sketch is
intentionally flat, but `RunModel` reconstruction also needs fields such as source branch, worktree
metadata, routine source/embedded config, merge strategy, agent runner data, and timestamps if the
current schema requires them.

**Hardening**: Before implementing events, compare `RunModel` and `TaskModel` constructor-required
fields against the event payload. Add a checklist in the step file: every non-nullable projection
column has either an event field or a documented deterministic default.

**F3.1-B - Event payloads that store raw routine config can become too large or unstable**

Storing the entire routine config enables rebuild, but it also means serialized event compatibility
depends on the current Pydantic model shape. Future schema changes can make older `RunCreated`
payloads fail validation.

**Hardening**: Store JSON-compatible dicts and version the payload where needed. Rebuild code should
accept unknown keys and provide defaults for missing fields.

---

## Task 3.2: Command module structure + run/task creation handlers

### Failure Modes

**F3.2-A - Command handlers can duplicate validation already enforced at API boundaries**

If command models loosen validation relative to API schemas, invalid enum/path data can enter the
event stream and later project into read models.

**Hardening**: Command models should use Pydantic constrained fields or existing enum types. Avoid
bare strings for constrained values that already have enums in `orchestrator.config`.

**F3.2-B - Creation handlers can append events but not project in the same transaction**

If command handlers append to `SqliteEventStore` but projectors are not registered in that store
instance, API responses may read stale data immediately after creation.

**Hardening**: Creation handler tests should assert both the stored event and the projected row
exist after one committed transaction.

---

## Task 3.3 and 3.4: Status, attempt, and fan-out command handlers

### Failure Modes

**F3.3-A - Buffered WorkflowEngine events can be double-emitted**

The current workflow engine emits domain events while repository methods mutate state. During the
transition, command handlers may also emit corresponding events. If both remain wired, JSONL and
`events_v2` can contain duplicate logical transitions.

**Hardening**: For every converted service method, identify the single source of event emission.
Tests should assert one event of each expected type is appended for a transition, not "at least one".

**F3.3-B - Attempt output updates can overwrite rather than append**

`AttemptUpdated.output_lines` is a delta. Projectors must append those lines to the attempt log
without replacing prior output. A naive update can retain only the most recent batch.

**Hardening**: Include a test with two `AttemptUpdated` events for the same attempt and assert the
projected log contains both batches in order.

**F3.4-A - Fan-out retry must rewind the step index consistently**

Retrying a fan-out child needs to reset the child, parent, and run current step index together. If
`FanOutChildRetried` and `StepIndexRewound` are separate events but one append succeeds without the
other, the run can be active at the wrong step.

**Hardening**: Batch logically inseparable fan-out retry events in one `SqliteEventStore.append`
call and one transaction. Add an integration test for retrying a failed fan-out child.

---

## Task 3.5 and 3.6: WorkflowService wiring

### Failure Modes

**F3.5-A - Mixed old/new write paths are easy to leave behind**

The plan ends with a grep for `_repo.save` and write method names, which is necessary but not
sufficient. A repository write can also be hidden behind helper methods or direct model mutation
followed by session commit.

**Hardening**: Add targeted tests for the major lifecycle transitions and assert they append
events to `events_v2`. Keep the grep, but also add a code review checklist for direct mutation of
`RunModel` / `TaskModel` inside workflow service methods.

**F3.5-B - API response timing can expose stale projections**

If service methods return before projector listeners complete, the API can report the old state even
though the event append was accepted.

**Hardening**: The command handler contract should be "append, project, then return." Integration
tests should call API endpoints and assert the immediate response contains the new status.

---

## Task 3.7: Remove write methods from RunRepository

### Failure Modes

**F3.7-A - Tests may still import repository write helpers**

Removing methods can break grandfathered tests that exercise workflow behavior through repository
helpers rather than services.

**Hardening**: Update tests to use command handlers or `WorkflowService`, not repository writes.
Do not preserve repository write methods as compatibility shims; that would undermine the read-only
contract.

**F3.7-B - Read-only repository still exposes mutable ORM objects**

Even if write methods are removed, callers can mutate returned SQLAlchemy model objects and commit
through a session.

**Hardening**: Document that the repository is a query layer, and keep mutation inside command
handlers. Longer term, consider returning domain snapshots instead of live ORM objects for code that
does not need persistence identity.

---

## Task 3.8 and 3.9: Tests

### Failure Modes

**F3.8-A - Unit tests can accidentally depend on API stack**

New command handler tests belong in unit tests and should not import `create_app` or `TestClient`.
The unit conftest will reject those imports.

**Hardening**: Use real in-memory DB sessions via `orchestrator.db.create_engine(":memory:")` and
direct command handler invocation.

**F3.9-A - Empty-DB rebuild must start from no projection rows**

The key guarantee is not "rebuild updates existing rows"; it is "rebuild creates rows from an empty
database using only events." A test that starts with existing `runs` and `tasks` rows misses the
intent.

**Hardening**: The integration test should create a database with `events_v2` populated and empty
read-model tables, run `rebuild-projections`, and assert all run/task rows are recreated.

---

## Cross-Cutting Concerns

### CC-3.1 - Transactional batching

Multi-event transitions must be appended in one batch when they represent one atomic state change.
This is especially important for fan-out creation, fan-out retry, and task completion plus grades.

**Hardening**: Add a command handler convention: each handler returns the exact emitted event list
and appends the whole list in one store call.

### CC-3.2 - JSONL compatibility after old write path removal

Step 03 removes the practical reliance on the old repository writes. If JSONL outbox records do not
match the legacy `history.jsonl` shape, existing tools can stop reading current events.

**Hardening**: Carry forward the Step 01 hardening that the outbox writes `run_id` and
`sequence_number` keys compatible with existing tooling.

---

## Summary of Required Hardening Actions

| ID | Severity | Task | Action |
|----|----------|------|--------|
| F3.1-A | HIGH | 3.1 | Map creation event fields against all non-nullable projection columns |
| F3.3-A | HIGH | 3.3 | Prevent double emission during mixed old/new transition |
| F3.3-B | HIGH | 3.3 | Test output-line deltas append instead of replace |
| F3.4-A | HIGH | 3.4 | Batch fan-out retry events atomically |
| F3.5-A | HIGH | 3.5/3.6 | Test each lifecycle transition writes to `events_v2` |
| F3.7-A | MED | 3.7 | Remove repository write helpers rather than preserving shims |
| F3.9-A | HIGH | 3.9 | Rebuild from events into empty read-model tables |
| CC-3.2 | HIGH | all | Keep JSONL output readable by existing tooling |
