# Step 02 Plan - Dry-Run Analysis Notes

## Summary

Step 02 introduces projection infrastructure and starts maintaining read-model tables from
the new event stream. This is the first point where write-side event persistence and read-side
state reconstruction meet. The plan is mostly coherent, but several failure modes can leave
projections silently stale or make rebuild behavior differ from live dispatch.

---

## Task 2.1: ProjectionCheckpointModel ORM Model and Alembic Migration

### Failure Modes

**F2.1-A - Migration chain can fork from Step 01**

This step adds a migration after Step 01's `events_v2` migration. If the `down_revision` points
to the wrong migration, file-backed databases can fail or Alembic can report multiple heads.

**Hardening**: Require the migration's `down_revision` to be the exact Step 01 migration id.
Verification should include `uv run alembic heads` and assert there is one head.

**F2.1-B - `ProjectionCheckpointModel` export can bypass module boundaries**

The task exports the model from `orchestrator.db`, which is correct. Implementors may import from
`orchestrator.db.orm.models` elsewhere because the model is defined there.

**Hardening**: State that external modules import `ProjectionCheckpointModel` from
`orchestrator.db` after the export is added. This preserves the repository import boundary.

---

## Task 2.2: Projector Protocol and ProjectionRegistry

### Failure Modes

**F2.2-A - Projector exceptions are swallowed after partial state mutation**

The provided registry sketch catches projector exceptions, logs them, and continues. If a projector
mutates part of the read model and then raises, the event append can still commit with corrupted or
stale projections.

**Hardening**: Decide explicitly whether projection failure should abort the event append. Because
the intent says current consistency guarantees are maintained, projector exceptions should propagate
and roll back the transaction. Logging is useful, but the append must fail rather than committing a
partially projected event.

**F2.2-B - Checkpoints can advance for projectors that did not handle the batch**

The registry sketch updates every projector's checkpoint to the last appended position, even when
that projector handled none of the events in the batch. This can make later incremental rebuild or
catch-up logic skip relevant events after a projector is added or its handled event set changes.

**Hardening**: Update a projector's checkpoint only after it successfully handles at least one event
or after a full rebuild. Alternatively, document checkpoints as global "registry processed through"
positions and do not treat them as per-projector progress.

**F2.2-C - Live dispatch and rebuild can use different event objects**

Live dispatch receives `workflow_events` directly from the append call, while rebuild reads stored
events from `events_v2`. If deserialization has any type or enum bug, live tests pass and rebuild
tests fail later.

**Hardening**: Add a test that appends events through `SqliteEventStore`, reads them back with
`get_all()`, then rebuilds projections from those read-back events.

---

## Task 2.3: RunStateProjector

### Failure Modes

**F2.3-A - Creation events are placeholders but empty-DB rebuild requires them later**

The step says `RunCreated` and `TaskCreated` are placeholders until Step 03. If the projector code
omits explicit branches and tests, Step 03 implementors may add the events without updating rebuild
logic, breaking [I-24].

**Hardening**: Add failing placeholder tests marked as expected TODO in the step file or add no-op
branches with comments that name the Step 03 task that must fill them. Step 03 should explicitly
replace those placeholders.

**F2.3-B - Status event order matters**

`RunStatusChanged`, `StepCompleted`, `StepSkipped`, `RunStepBackward`, and checklist events can
arrive in a precise order. A projector that applies them idempotently must still preserve the final
state for repeated rebuilds.

**Hardening**: Unit tests should feed a realistic sequence for a run that pauses, resumes, completes
a step, rewinds, then resumes again. Assert the final `RunModel.status`, `pause_reason`, and
`current_step_index`.

---

## Task 2.4: TaskStateProjector

### Failure Modes

**F2.4-A - Fan-out child events can reference missing parent rows during rebuild**

During empty-DB rebuild, child and parent creation order must be deterministic. If a fan-out event
updates children before their task rows exist, SQLAlchemy updates can affect zero rows without
failing.

**Hardening**: Projector updates should verify row existence when the event semantically requires
it. Step 03 creation events must be replayed before fan-out mutation events in tests.

**F2.4-B - Clarification and approval events update both task and run-level action state**

Clarification and approval events may affect pending user-action fields as well as task status.
If TaskStateProjector only updates task rows, the UI can show stale pending actions.

**Hardening**: Add assertions against pending action fields in projection tests, not just task
status. Include one clarification request/response sequence and one approval decision sequence.

---

## Task 2.5: CLI rebuild-projections and emitter wiring

### Failure Modes

**F2.5-A - Server lock detection can be a false negative**

The step requires rebuild to refuse if the server appears to be running. If the lock file path is
not shared with the running application, the command can rebuild projections while live events are
being appended.

**Hardening**: Define the exact lock file path or helper function used by both server startup and
the CLI. Add a test that creates that lock file and asserts the command refuses to run.

**F2.5-B - Rebuild must clear read models before replay**

Resetting checkpoints to 0 is not enough. If read-model rows already exist and the replay uses
insert-only logic, stale rows can survive or inserts can conflict.

**Hardening**: Rebuild must either truncate/recreate projection-owned tables or projectors must
upsert every row deterministically and remove stale rows. The step should state which approach is
used. For this single-instance server-stop rebuild, clearing projection-owned tables first is the
simplest behavior to verify.

**F2.5-C - Wiring only in API deps misses non-API emitters**

The task wires `ProjectionRegistry` into `PersistentEventEmitter` via `api/deps.py`. If CLI or test
construction paths build their own emitters, those paths can continue writing events without
projecting them.

**Hardening**: Centralize emitter/event-store construction in one factory used by API, workflow,
and tests. Add an integration test that creates a run through the API and verifies projected state
changes in the database.

---

## Cross-Cutting Concerns

### CC-2.1 - Transaction boundaries

Projectors are supposed to run synchronously after append in the same transaction. That means
listener signatures need access to both stored events and the active `AsyncSession`.

**Hardening**: Ensure Step 01's listener interface passes the session and original workflow events
to listeners. If it only passes `StoredEvent`, Step 02 will need a breaking interface change.

### CC-2.2 - Import boundaries

Projection modules live under `orchestrator.db`; workflow/service code should import projections
through public exports where practical.

**Hardening**: Update `src/orchestrator/db/__init__.py` or `db/projections/__init__.py` with stable
exports before wiring from API dependencies.

---

## Summary of Required Hardening Actions

| ID | Severity | Task | Action |
|----|----------|------|--------|
| F2.1-A | HIGH | 2.1 | Verify a single Alembic head after adding the checkpoint migration |
| F2.2-A | HIGH | 2.2 | Projection exceptions should abort append, not be swallowed |
| F2.2-B | HIGH | 2.2 | Do not advance per-projector checkpoints for unhandled events |
| F2.2-C | HIGH | 2.2 | Test rebuild from stored events read back from `events_v2` |
| F2.3-A | HIGH | 2.3 | Make creation-event placeholders explicit and tied to Step 03 |
| F2.4-A | MED | 2.4 | Verify referenced rows exist when fan-out events mutate them |
| F2.5-B | HIGH | 2.5 | Clear or deterministically upsert projection-owned tables on rebuild |
| CC-2.1 | HIGH | all | Confirm listener interface carries session and original events |
