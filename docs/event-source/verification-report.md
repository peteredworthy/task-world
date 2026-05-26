# Event-Source Migration — Verification Report

**Date:** 2026-05-25
**Status: ✓ Ready** (after applying step-file corrections documented below)

---

## Executive Summary

The intent, plan, step files, and dry-run output are mutually consistent and execution-ready after
four targeted corrections applied to step files during this review:

1. **F2.2-A** (critical): Contradicting constraint corrected in `steps/step-02-plan.md` — projection
   failure must now propagate and abort the transaction (not be swallowed).
2. **F2.2-B** (significant): Checkpoint code updated to advance only for projectors that handled
   at least one event, not all projectors in the registry.
3. **F1.2-A** (significant): Buggy `RetryWithBackoff` code example corrected in
   `steps/step-01-plan.md` — non-conflict exceptions now re-raised unchanged.
4. **F1.3-A / F1.4-D** (significant): `JsonlOutboxObserver` code now includes the required
   `try/except` wrapper; Task 1.4 "manually confirm" changed to a mandatory integration test.
5. **F2.5-B** (significant): `rebuild-projections` CLI code in `steps/step-02-plan.md` now clears
   projection-owned tables before replaying events.

No intent items lack step-file coverage. The persistence mapping audit has no MISSING cells.
Integration test tasks specify assertion logic throughout.

---

## R1 — Step Files Align with Plan and Intent

**Status: ✓ Aligned** (after corrections)

| Step | Plan Milestone | Step-File Coverage | Notes |
|------|---------------|-------------------|-------|
| S-00 | M0: Pydantic Event Conversion | `steps/step-00-plan.md` | Full task coverage; timestamp/mutable-default/enum hardening applied |
| S-01 | M1: Event Store Foundation | `steps/step-01-plan.md` | Code examples corrected (RetryWithBackoff, try/except, mandatory integration test) |
| S-02 | M2: Projection Infrastructure | `steps/step-02-plan.md` | Corrected exception handling, checkpoint logic, and rebuild table-clearing |
| S-03 | M3: Command-Event Refactor | `steps/step-03-plan.md` | Full 9-task coverage; atomic fan-out batching; empty-DB rebuild tests specified |
| S-04 | M4: Signal System Migration | `steps/step-04-plan.md` | Lifecycle projector rebuild on startup; idempotent drain; dependency injection |
| S-05 | M5: Output Batching + Cleanup | `steps/step-05-plan.md` | OutputBatcher buffer-keying; flush-on-exception; JSONL bootstrap dual-format |

The architecture document (`architecture.md`) matches the data flow described in the plan.
Module placement table, schema SQL, and pattern examples are internally consistent.
The concurrency strategy abstraction and JSONL outbox observer are correctly described.

---

## R2 — All Critical/Significant Dry-Run Gaps Applied to Step Files

All rows in `dry-run-notes.md` show **"Applied to step files: YES"**. This section verifies
accuracy of each "YES" claim by checking both the step-level hardening section and the
per-task constraint/code.

### Step 00 Gaps

| ID | Severity | Claim Accurate? | Notes |
|----|----------|----------------|-------|
| F0.1-A | HIGH | ✓ | `Field(default_factory=...)` required for timestamps; stated in hardening section and task constraints |
| F0.1-B | HIGH | ✓ | Mutable defaults must use `Field(default_factory=...)`; verification grep included |
| F0.1-C | HIGH | ✓ | Preserve `event_type` values; round-trip tests cover representative events |
| F0.1-D | HIGH | ✓ | Standardize on `model_dump(mode="json")`; applies to DB, JSONL, and WebSocket paths |
| F0.2-A | HIGH | ✓ | `model_dump(mode="json")` standardized at serialization call sites |
| F0.2-B | MED | ✓ | Explicit event-type registry required; round-trip test covers legacy `EventStore` path |
| F0.3-A | MED | ✓ | Test list built from module exports; new event types fail until fixtures added |
| CC-0.1 | MED | ✓ | Public export from `workflow.events.__init__` required |
| CC-0.2 | HIGH | ✓ | Step 01 prerequisite check added to verify `model_dump_json()` attribute |

### Step 01 Gaps

| ID | Severity | Pre-Correction Status | Post-Correction Status |
|----|----------|-----------------------|------------------------|
| F1.1-A | HIGH | ✓ Accurate — `down_revision` stated in Dry-Run Hardening section | ✓ |
| F1.1-C | MED | ✓ No FK from `aggregate_id` to `runs.id`; explicit constraint added | ✓ |
| F1.2-A | HIGH | ✗ **Buggy code example shown in Task 1.2** | ✓ **Corrected** — non-conflict exceptions now re-raised |
| F1.2-B | HIGH | ✓ `list[Any]` for `_listeners` stated in note | ✓ |
| F1.2-C | HIGH | ✓ `PersistentEventEmitter.emit()` must pass `[event]`; stated in hardening | ✓ |
| F1.3-A | HIGH | ✗ **Code example lacked `try/except` wrapper** | ✓ **Corrected** — wrapper added to code |
| F1.4-A | HIGH | ✓ Interface mismatch addressed; `append_batch` alias noted | ✓ |
| F1.4-B | LOW | ✓ `request: Request` unused parameter noted | ✓ |
| F1.4-C | HIGH | ✓ `make_service_factory` update required | ✓ |
| F1.4-D | HIGH | ✗ **"Manually confirm" remained; not a mandatory test** | ✓ **Corrected** — mandatory integration test added |
| F1.5-A | HIGH | ✓ `orchestrator.db.create_engine(":memory:")` pattern specified | ✓ |
| F1.5-B | MED | ✓ `RetryWithBackoff` tested independently via callable injection | ✓ |
| F1.5-D | MED | ✓ Listener must be `async def`; constraint specified | ✓ |
| CC-1 | HIGH | ✓ Integration test verifying `events_v2` row required | ✓ (now mandatory) |
| CC-7 | HIGH | ✓ Legacy-compatible keys OR reader compatibility tests required | ✓ |

**CC-7 note**: The `_to_record` implementation code in Task 1.3 uses `aggregate_id`/`position`
keys, not the legacy `run_id`/`sequence_number`. The constraint allows either: use legacy keys OR
prove reader compatibility in tests. Since Step 05 Task 5.5 explicitly supports both JSONL shapes
in the bootstrap reader, this is covered by the "reader compatibility" route. However, an
implementing engineer should confirm in Task 1.5's `test_jsonl_outbox.py` that the output passes
through the bootstrap reader without silent omission.

### Step 02 Gaps

| ID | Severity | Pre-Correction Status | Post-Correction Status |
|----|----------|-----------------------|------------------------|
| F2.1-A | HIGH | ✓ Single Alembic head verified after checkpoint migration | ✓ |
| F2.2-A | HIGH | ✗ **Direct contradiction**: hardening said abort; constraint said swallow | ✓ **Corrected** — exceptions now propagate |
| F2.2-B | HIGH | ✗ **Code advanced ALL projectors regardless of handling** | ✓ **Corrected** — only projectors that handled events advance |
| F2.2-C | HIGH | ✓ Rebuild-from-stored-events test specified | ✓ |
| F2.3-A | HIGH | ✓ Placeholder tests for `RunCreated`/`TaskCreated` linked to Step 03 | ✓ |
| F2.4-A | MED | ✓ Row-existence check required for fan-out mutations | ✓ |
| F2.5-B | HIGH | ✗ **Rebuild CLI did not clear projection tables before replay** | ✓ **Corrected** — table clearing added to Task 2.4 |
| CC-2.1 | HIGH | ✓ Listener interface carries session and workflow events | ✓ |

### Step 03 Gaps

| ID | Severity | Claim Accurate? | Notes |
|----|----------|----------------|-------|
| F3.1-A | HIGH | ✓ | Creation-event field checklist against non-nullable columns required before implementation |
| F3.3-A | HIGH | ✓ | Single emission source per service method; grep verification in Task 3.6 |
| F3.3-B | HIGH | ✓ | Output-delta append test (two `AttemptUpdated` events, verify both batches in order) |
| F3.4-A | HIGH | ✓ | `RetryFanOutChildCommand` batches both events atomically in one `append` call |
| F3.5-A | HIGH | ✓ | Lifecycle transition tests assert `events_v2` entries |
| F3.7-A | MED | ✓ | Write helpers removed, not shimmed |
| F3.9-A | HIGH | ✓ | Empty-DB rebuild test starts with truncated read-model tables |
| CC-3.2 | HIGH | ✓ | JSONL compatibility carried forward from Step 01 hardening |

### Step 04 Gaps

| ID | Severity | Claim Accurate? | Notes |
|----|----------|----------------|-------|
| F4.2-A | HIGH | ✓ | Lifecycle projector rebuilt on startup before `_redeliver_on_startup`; integration test verifies |
| F4.3-A | HIGH | ✓ | `SignalProcessed.enqueued_position` idempotency / uniqueness guard |
| F4.3-C | MED | ✓ | Stale signals are no-ops in drain path |
| F4.4-B | HIGH | ✓ | `RunLifecycleProjector` injected into `SignalConsumer`; no global state |
| F4.5-A | HIGH | ✓ | All producers/consumers moved off `pending_signals` together; grep check included |
| F4.8-A | HIGH | ✓ | Startup recovery test creates fresh consumer/projector instance |

### Step 05 Gaps

| ID | Severity | Claim Accurate? | Notes |
|----|----------|----------------|-------|
| F5.1-B | HIGH | ✓ | Buffer keyed by `(run_id, task_id, attempt_id)` |
| F5.1-C | HIGH | ✓ | Buffer cleared only after successful append; hardening in task description |
| F5.3-A | HIGH | ✓ | `flush_immediate()` in `finally` blocks around agent execution |
| F5.3-B | HIGH | ✓ | Monotonic `line_offset` maintained; integration test asserts no gaps |
| F5.5-A | HIGH | ✓ | Bootstrap reads both legacy and outbox JSONL shapes |
| F5.5-C | MED | ✓ | Position conflict with differing identity raises corruption error |
| F5.7-A | HIGH | ✓ | Legacy recovery deletion depends on bootstrap/rebuild tests passing |
| F5.8-A | MED | ✓ | `pending_signals` migrated or asserted empty before drop |

---

## R3 — No Unresolved Critical Conflicts

**Status: ✓ Resolved** (after applying corrections)

The only unresolved critical conflict found was **F2.2-A**: the Dry-Run Hardening Applied section
in `steps/step-02-plan.md` required projection failures to abort the transaction, but Task 2.2's
constraint said the opposite ("must not propagate") and the code example swallowed exceptions.
This has been corrected: the constraint and code now align with the hardening decision.

All other potential conflicts between hardening sections and task constraints are either:
- Fully consistent (hardening and task constraints agree), or
- Addressed via the "OR" alternative (e.g., CC-7 allows legacy keys OR reader compatibility tests)

---

## R4 — Persistence Mapping Audit: No MISSING Cells

**Status: ✓ Pass**

From `dry-run-notes.md`, the persistence mapping audit table has 8 rows, all populated:

| State / Event Surface | Step Applied |
|----------------------|--------------|
| Workflow event history | Step 01 |
| JSONL journal continuity | Steps 01 and 05 |
| Run read model | Steps 02 and 03 |
| Task read model | Steps 02 and 03 |
| Projection progress | Step 02 |
| Signals | Step 04 |
| Agent output | Step 05 |
| Legacy queue cleanup | Step 05 |

The closing note in `dry-run-notes.md` confirms: "No MISSING cells remain in the persistence
mapping audit." Verified accurate.

---

## R5 — Integration Test Assertion Logic Quality

**Status: ✓ Pass** (all steps specify assertion logic, not just scenario names)

| Step | Integration Test | Assertion Logic Specified |
|------|-----------------|--------------------------|
| S-01 | `test_event_store_wiring.py` (newly mandatory) | Assert `events_v2` row via `get_stream(run_id)`; assert JSONL line present |
| S-02 | `test_projection_recovery.py` | Assert `GET /api/runs/{run_id}` returns correct status after rebuild |
| S-02 | `test_projection_recovery.py` | Idempotency: two rebuilds produce identical read-model state |
| S-03 | `test_event_sourced_workflow.py` | Assert `RunCreated` is first event in `get_stream(run_id)`; assert API response matches |
| S-03 | `test_event_sourced_workflow.py` | Empty-DB rebuild: assert API response matches pre-truncation snapshot field-by-field |
| S-04 | `test_signal_events.py` | Assert `SignalEnqueued` in `events_v2`; assert `SignalProcessed` appended; no `pending_signals` writes |
| S-04 | `test_signal_events.py` | Stale signal: assert no state change; startup recovery: assert redelivery |
| S-05 | `test_output_batching.py` | Assert < 60 `AgentOutputEvent` rows; assert all 60 lines in order; assert monotonic `line_offset` |
| S-05 | `test_jsonl_bootstrap.py` | Assert `events_v2` row count; assert `runs` projection row; assert checkpoint position |

All integration tests specify what to assert (observable behavior), not just what scenario to run.

---

## R6 — Intent Coverage: Complete

**Status: ✓ Complete**

All 32 `[I-XX]` items in `intent.md` carry a step reference or NO-REQ annotation. No bare
`[I-XX]` items exist.

### Coverage Map

| Range | Status |
|-------|--------|
| I-01 to I-10 | All annotated → S-0x references |
| I-11 to I-15 | All annotated → NO-REQ (explicitly out of scope) |
| I-16 to I-23 | All annotated → S-0x references |
| I-24 to I-32 | All annotated → S-0x references |

### Traceability Spot-Checks

| Intent | Annotation | Step Coverage Verified |
|--------|-----------|----------------------|
| I-04: Consolidate dual-write | → S-01 | ✓ Task 1.2 (`SqliteEventStore`) + Task 1.3 (`JsonlOutboxObserver`) |
| I-05: Projection rebuilds | → S-02 | ✓ Task 2.4 (`rebuild-projections` CLI) |
| I-06: Signal system migration | → S-04 | ✓ Tasks 4.2–4.5 (`RunLifecycleProjector`, `EventSignalTransport`) |
| I-07: AgentOutputEvent batching | → S-05 | ✓ Task 5.1 (`OutputBatcher`, 100ms/50-line defaults) |
| I-18: JSONL remains readable | → S-01, S-05 | ✓ CC-7 constraint in Task 1.3; Task 5.5 reads both JSONL formats |
| I-22: Pydantic for events/projections | → S-00, S-02 | ✓ S-00 converts events; S-02 projectors receive Pydantic events |
| I-23: WorkflowEngine pure | → S-03 | ✓ Task 3.5: `WorkflowEngine` does not receive `SqliteEventStore` |
| I-24: Empty-DB rebuild | → S-03, S-05 | ✓ Task 3.9 empty-DB rebuild test; Task 5.5 JSONL bootstrap |
| I-29: `rebuild-projections` CLI | → S-02 | ✓ Task 2.4: server-stop rebuild with lock-file guard |
| I-31: Dual-write unified | → S-01, S-05 | ✓ Task 1.4 wiring; Task 5.7 legacy removal |
| I-32: Recovery from event log | → S-05 | ✓ Task 5.5 bootstrap; Task 5.7 removes ad-hoc recovery.py |

### Intent Coverage Gaps

None. Intent coverage: complete.

---

## Cross-Step Dependency Alignment

The cross-step dependency chain in `dry-run-notes.md` is correctly reflected in step prerequisites:

| Dependency | Step File Prerequisite |
|------------|----------------------|
| S-00 → S-01 (events must be Pydantic for serialization) | S-01 states "Step 00 must be complete"; adds runtime check |
| S-01 → S-02 (event store must exist for projectors) | S-02 states "Step 01 must be complete" |
| S-02 → S-03 (projectors must handle events before command refactor) | S-03 states "Step 02 must be complete" |
| S-03 → S-04 (WorkflowService uses command handlers before signal migration) | S-04 states "Step 03 must be complete" |
| S-04 → S-05 (signal migration proven before legacy removal) | S-05 states "All previous steps must be complete" |
| S-05 cleanup → S-05 bootstrap proof | Task 5.7 depends on Task 5.6 passing |

---

## Corrections Applied During This Review

| Gap ID | Severity | File Modified | Change |
|--------|----------|--------------|--------|
| F2.2-A | Critical | `steps/step-02-plan.md` | Projection exceptions now propagate (not swallowed); code and constraint aligned |
| F2.2-B | High | `steps/step-02-plan.md` | Checkpoint advancement now per-projector (only projectors that handled ≥1 event) |
| F2.5-B | High | `steps/step-02-plan.md` | Rebuild CLI now clears projection-owned tables before replay |
| F1.2-A | High | `steps/step-01-plan.md` | `RetryWithBackoff` code corrected: non-conflict errors re-raised unchanged |
| F1.3-A | High | `steps/step-01-plan.md` | `JsonlOutboxObserver.__call__` code now includes required `try/except` wrapper |
| F1.4-D | High | `steps/step-01-plan.md` | "Manually confirm" replaced with mandatory integration test requirement |

All corrections bring step-file content into alignment with the Dry-Run Hardening Applied sections
and the decisions recorded in `dry-run-notes.md`.

---

## Verdict

| Requirement | Status | Grade |
|-------------|--------|-------|
| R1 [critical]: Step files align with plan and intent | ✓ Done | A |
| R2 [critical]: All dry-run gaps applied to step files | ✓ Done (corrections applied) | A |
| R3 [critical]: No unresolved critical conflicts | ✓ Done (F2.2-A resolved) | A |
| R4 [critical]: No MISSING cells in persistence mapping | ✓ Done | A |
| R5 [expected]: Integration tests specify assertion logic | ✓ Done | A |
| R6 [critical]: Every I-XX annotated; references verified | ✓ Done | A |

**Overall: ✓ Ready for implementation**
