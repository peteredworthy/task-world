# Event-Driven Migration — Plan Summary

**Date:** 2026-05-25  
**Status:** ✓ Ready for Implementation  
**Base Documents:** intent.md, plan.md, clarifications.md, dry-run-notes.md, verification-report.md

---

## Executive Summary

This migration transforms the Orchestrator from a dual-write, state-mutation-first architecture to a true event-sourced system where the append-only SQLite event log (`events_v2`) is the single source of truth and all queryable state is derived via projections. The migration eliminates the consistency gap between SQLite state and the JSONL journal, removes ad-hoc recovery logic, and makes the system auditable and fully replayable.

The plan consists of **six milestones** (one preparatory, five iterative) executed in strict dependency order. Each milestone is deployable and tested independently. Total task count: **35 tasks across 6 steps**.

---

## Intent Satisfaction Summary

All 32 intent items (`[I-01]` through `[I-32]`) are satisfied by the plan. The mapping is documented in full in the verification report; summary by category:

### Core Intent: Event-Sourced Architecture
- **[I-01]** Migrate to event-sourced system → **S-00, S-01, S-02, S-03, S-04, S-05**
- **[I-02]** Eliminate consistency gap, enable replay and audit → **S-01, S-02, S-05**
- **[I-03]** Pydantic conversion + command handlers + entity creation events → **S-00, S-03**
- **[I-04]** Consolidate dual-write to SQLite event store, keep JSONL as secondary outbox → **S-01**
- **[I-05]** Projection rebuild from event log → **S-02**

### System Migration
- **[I-06]** Signal system event-driven, remove `_active_run_ids` → **S-04**
- **[I-07]** Batch `AgentOutputEvent`, resolve TD-09 (100ms flush / 50 lines) → **S-05**
- **[I-08]** Maintain API contracts (no breaking changes) → **S-03, S-04, S-05**
- **[I-09]** Maintain CLI behavior → **S-02, S-05**
- **[I-10]** Preserve `BufferingEmitter` pattern → **S-03**

### Scope & Constraints
- **[I-11]** Multi-worker out of scope → NO-REQ
- **[I-12]** Frontend UI unchanged → NO-REQ
- **[I-13]** External routine fetch out of scope → NO-REQ
- **[I-14]** Routine YAML schema unchanged → NO-REQ
- **[I-15]** Agent protocol unchanged → NO-REQ
- **[I-16]** All tests pass per phase → **S-00 through S-05**
- **[I-17]** Alembic migrations not deleted → **S-01, S-02**
- **[I-18]** JSONL remains readable during transition, becomes secondary write post-migration → **S-01, S-05**
- **[I-19]** No test mocking; real in-memory SQLite → **S-00 through S-05**
- **[I-20]** Async by default for new I/O → **S-01 through S-05**
- **[I-21]** Respect 9-module boundary → **S-01 through S-05**
- **[I-22]** Pydantic for events and projections → **S-00, S-02**
- **[I-23]** `WorkflowEngine` remains pure → **S-03**

### Definition of Complete
- **[I-24]** Empty-DB rebuild from event log (including creation events) → **S-03, S-05**
- **[I-25]** `RunRepository` read-only, writes via command handlers → **S-03**
- **[I-26]** `_active_run_ids` removed, derived from event state → **S-04**
- **[I-27]** `AgentOutputEvent` batched (100ms/50 lines, configurable) → **S-05**
- **[I-28]** All existing tests pass without modification → **S-00 through S-05**
- **[I-29]** `rebuild-projections` CLI command exists → **S-02**
- **[I-30]** API latency <10% regression → **S-05**
- **[I-31]** Dual-write unified to SQLite + outbox → **S-01, S-05**
- **[I-32]** Startup recovery reads from event log → **S-05**

**Coverage:** 32/32 intents satisfied. 18/18 out-of-scope intents marked NO-REQ. No gaps.

---

## Ordered Step List with Task Counts

### **Step 00: Pydantic Event Conversion (Preparatory, M0)**
**Deliverable:** All ~30 event dataclasses converted to Pydantic `BaseModel`.  
**Rationale:** Prerequisite for serialization in Step 01; addresses [I-22].  
**Task Count:** 3 tasks
1. Convert `WorkflowEvent` base + 30 subclasses to Pydantic (150 LOC)
2. Replace `dataclasses.asdict()` with `model_dump()` (15 LOC)
3. Add Pydantic round-trip test suite (120 LOC)

**Dependencies:** None (preparatory).  
**Exit Criteria:** `uv run pytest` passes; `model_dump_json()`/`model_validate_json()` round-trip verified.

---

### **Step 01: Event Store Foundation (M1)**
**Deliverable:** Unified event store (SQLite) + JSONL outbox observer + concurrency layer.  
**Replaces:** Dual-write path (`EventStore` + `JsonlEventJournal`).  
**Addresses:** [I-04], [I-31], [I-18] (JSONL as secondary).  
**Task Count:** 5 tasks
1. `events_v2` ORM model + Alembic migration (50 LOC)
2. `SqliteEventStore` + `ConcurrencyStrategy` interface (250 LOC)
3. `JsonlOutboxObserver` (idempotent, keyed by position) (120 LOC)
4. Wire `PersistentEventEmitter` to `SqliteEventStore` (80 LOC)
5. Integration tests: store append, JSONL write, round-trip (100 LOC)

**Dependencies:** Step 00 (events must be Pydantic).  
**Exit Criteria:** All tests pass; `events_v2` rows created on append; JSONL lines written; no regressions.

---

### **Step 02: Projection Infrastructure (M2)**
**Deliverable:** `Projector` protocol, `ProjectionRegistry`, concrete projectors (`RunStateProjector`, `TaskStateProjector`), `rebuild-projections` CLI.  
**Addresses:** [I-05], [I-25] (read-only repository), [I-29] (rebuild CLI).  
**Task Count:** 5 tasks
1. `ProjectionCheckpointModel` ORM + migration (30 LOC)
2. `Projector` protocol + `ProjectionRegistry` (120 LOC)
3. `RunStateProjector` + `TaskStateProjector` (280 LOC)
4. `rebuild-projections` CLI command (90 LOC)
5. Projector integration tests (150 LOC)

**Dependencies:** Step 01 (event store must exist).  
**Exit Criteria:** Projectors dispatch events, checkpoints advance correctly, rebuild command works, integration tests pass.

---

### **Step 03: Command-Event Refactor of RunRepository (M3)**
**Deliverable:** Command handlers emit events; `RunRepository` becomes read-only; full empty-DB rebuild possible.  
**Addresses:** [I-03], [I-24] (entity creation events), [I-25] (write removal), [I-08] (API contracts).  
**Task Count:** 9 tasks
1. New event types: `RunCreated`, `TaskCreated`, `AttemptUpdated`, `FanOutChildrenCreated`, etc. (150 LOC)
2. Command models + async handlers (200 LOC)
3. `WorkflowService` calls handlers for run creation (180 LOC)
4. `WorkflowService` calls handlers for task operations (220 LOC)
5. `WorkflowService` calls handlers for signals and fan-out (150 LOC)
6. Remove `RunRepository` write methods (60 LOC removal)
7. Placeholder event handling in projectors (linked to S02 update) (20 LOC)
8. Command handler unit tests (200 LOC)
9. Empty-DB rebuild integration test (100 LOC)

**Dependencies:** Step 01 (SqliteEventStore) + Step 02 (projectors).  
**Exit Criteria:** All repository write methods removed; event-sourced paths verified; empty-DB rebuild test passes.

---

### **Step 04: Signal System Migration (M4)**
**Deliverable:** Signal events replace `pending_signals` table; `_active_run_ids` removed.  
**Addresses:** [I-06] (TD-03 resolved), [I-26] (active tracking derived).  
**Task Count:** 5 tasks
1. `SignalEnqueued` + `SignalProcessed` event types (40 LOC)
2. `RunLifecycleProjector` maintaining active-run set (80 LOC)
3. `EventSignalTransport` (query events instead of table) (110 LOC)
4. Remove `_active_run_ids` module state (80 LOC removal)
5. Signal migration integration tests (100 LOC)

**Dependencies:** Step 01 (events) + Step 02 (projectors) + Step 03 (WorkflowService).  
**Exit Criteria:** Signal events stored; lifecycle projector rebuilt on startup; `pending_signals` no longer used; tests pass.

---

### **Step 05: Output Batching and Cleanup (M5)**
**Deliverable:** `OutputBatcher` resolves TD-09; legacy dual-write code removed; JSONL bootstrap added.  
**Addresses:** [I-07] (batching), [I-31] (dual-write removal), [I-32] (startup from event log), [I-30] (latency <10%).  
**Task Count:** 8 tasks
1. `OutputBatcher` (batches by run/task/attempt, 100ms/50-line thresholds) (130 LOC)
2. Unit tests for `OutputBatcher` with `FakeClock` (140 LOC)
3. Wire `OutputBatcher` into `PhaseHandler`, add flush-on-boundary calls (100 LOC)
4. Integration test: 60-line batch, verify WebSocket count + ordering (120 LOC)
5. `bootstrap_from_jsonl()` on empty DB startup (110 LOC)
6. Integration test: JSONL bootstrap + projection rebuild (100 LOC)
7. Remove legacy modules: `recovery.py`, `event_journal.py`, `journal_replay.py`; drop `pending_signals` table (40 LOC removal)
8. Performance validation: measure latency regression <10% (50 LOC tests)

**Dependencies:** All previous steps.  
**Exit Criteria:** Batching verified via integration test; bootstrap works; legacy code removed; latency within target; full test suite passes.

---

## Step Count Summary

| Step | Milestone | Tasks | LOC Estimate (Add) | LOC Estimate (Remove) |
|------|-----------|-------|--------------------|-----------------------|
| S-00 | M0: Pydantic Conversion | 3 | 285 | 0 |
| S-01 | M1: Event Store Foundation | 5 | 600 | 0 |
| S-02 | M2: Projection Infrastructure | 5 | 670 | 0 |
| S-03 | M3: Command-Event Refactor | 9 | 1,200 | 60 |
| S-04 | M4: Signal Migration | 5 | 410 | 80 |
| S-05 | M5: Output Batching + Cleanup | 8 | 750 | 40 |
| **TOTAL** | **6 steps** | **35 tasks** | **~3,915 LOC** | **~180 LOC** |

---

## Key Decisions

All decisions are recorded in `/docs/event-source/clarifications.md`. Summary:

| # | Decision | Rationale | Impact |
|---|----------|-----------|--------|
| **Q1** | Convert events to Pydantic in separate M0 step | Large cross-cutting change (~30 types); avoid mixing serialization with event-sourcing logic | Adds sequential dependency; simplifies M1 |
| **Q2** | Full event sourcing including creation (`RunCreated`/`TaskCreated`) | [I-24] requires empty-DB rebuild without snapshots; creation must be events | S-03 complexity increases; enables audit trail from start |
| **Q3** | One-time DB migration with blow-away fallback | Single production instance; manual or automatic both add risk; simplicity preferred | If migration fails, DB can be reset from JSONL |
| **Q4** | Rebuild requires server stop (brief downtime acceptable) | Live rebuild coordination is complex; brief stop is operationally acceptable | Simpler implementation; acceptable for single-instance deployment |
| **Q5** | Retry with backoff; factor strategy for PostgreSQL migration | Rare concurrent writes; retry is simple; strategy layer enables future optimization | Adds ~10–50ms latency on conflict; mitigation layer ready for PostgreSQL primitives |
| **Q6** | Keep JSONL real-time via outbox observer; bootstrap reads JSONL when DB empty | [I-18] intent: JSONL remains readable; outbox fixes atomicity bug from inline write | M1 adds `JsonlOutboxObserver`; M5 adds bootstrap |
| **Q7** | 100ms flush / 50 lines batch for `AgentOutputEvent` | Balances DB write overhead (TD-09) vs. WebSocket latency | Configurable in code; defaults tuned by measurement |

---

## Risks and Mitigations

Risks identified during dry-run review; all have hardening applied to step files.

### Critical Risks

| Risk | Likelihood | Severity | Mitigation | Step Applied |
|------|------------|----------|-----------|---------------|
| **Timestamp binding at import time** | Medium | High | Use `Field(default_factory=...)` for all timestamps; verification grep for `datetime.now()` | S-00 |
| **Alembic migration fork** | Low | High | Require exact `down_revision` in migration; single-head check | S-01 |
| **Non-conflict exceptions wrapped as concurrency errors** | Medium | High | `RetryWithBackoff` re-raises non-conflict exceptions unchanged | S-01 |
| **Projection failure swallows state changes** | High | Critical | Projection exceptions propagate and abort append transaction | S-02 |
| **Creation events missing fields for empty-DB rebuild** | High | Critical | Pre-implementation: map every non-nullable projection column to event field or default | S-03 |
| **Double emission during repository refactor** | Medium | High | Assert exact event counts in tests; grep for old write method calls | S-03 |
| **Fan-out mutations non-atomic** | Medium | High | Batch related events in single store append | S-03 |
| **Lifecycle projector loses state on restart** | High | High | Rebuild projector before signal redelivery on startup | S-04 |
| **Output buffer loses tail lines on exception** | High | Medium | Flush in exception/phase-boundary paths; clear buffer only after append succeeds | S-05 |
| **Bootstrap skips existing JSONL records** | High | High | Support both legacy and outbox JSONL shapes; test round-trip | S-05 |

### Operational Risks

| Risk | Mitigation | Step |
|------|-----------|------|
| Large surface area (~30 event types, ~15 write methods) | Mechanical conversion + comprehensive tests; one-at-a-time validation | S-00, S-03 |
| Concurrent writes to same run aggregate | Optimistic locking + retry with backoff (max 3 attempts); strategy abstraction for PostgreSQL | S-01 |
| Projection rebuild performance on large journals | Batched processing; progress tracking; tests on realistic event volumes | S-02 |
| JSONL compatibility during transition | Outbox observer writes legacy-compatible keys OR reader compatibility tests | S-01, S-05 |
| Signal delivery latency | Indexed query on `(aggregate_id, event_type)`; measured parity with `pending_signals` scan | S-04 |
| API latency regression | Batching + synchronous projection updates; <10% target measured in S-05 | S-05 |

---

## Caveats for Execution

### Prerequisites & Order

1. **Step 00 must complete before Step 01.** Events must be Pydantic models for serialization to work in the event store.
2. **Step 01 must complete before Step 02.** Projectors depend on `SqliteEventStore` existing and accepting appends.
3. **Step 02 must complete before Step 03.** Projectors must handle events before repository writes are refactored.
4. **Step 03 must complete before Step 04 and Step 05.** `WorkflowService` command handlers must be in place before signal and output systems migrate.
5. **Step 04 and 05 can proceed in parallel after Step 03,** but Step 05 should complete last (removes legacy code).

### Testing Strategy

- **Per-phase test pass requirement:** No intermediate breakage; all tests must pass after each step completes.
- **No mocking:** Use real in-memory SQLite (`create_engine(":memory:")`) and real event stores in all tests.
- **Integration test assertions:** Every integration test specifies assertion logic, not just scenario names (verified in review).

### Database Migration & Fallback

- **Existing events migration:** One-time import script (Phase 0.4 in detailed steps) loads legacy JSONL and old events table into `events_v2`. Single production instance; if migration fails, DB can be blown away and rebuilt from JSONL via bootstrap.
- **Alembic chains:** New migrations are added alongside existing ones; no deletions or rewrites.
- **Checkpoint reset:** `rebuild-projections` CLI resets checkpoints to 0 before replaying all events.

### Performance Targets

- **Event append latency:** Measured via integration test in S-01; batch writes keep overhead low.
- **Signal delivery latency:** Indexed query on `(aggregate_id, event_type)` achieves parity with current `pending_signals` table scan.
- **API response latency:** <10% regression target for typical operations (validated in S-05).
- **Output batching:** 100ms flush interval / 50-line batch threshold (configurable); measured in S-05 integration test.

### Schema & Cleanup

- **Projection tables:** `runs`, `tasks`, `attempts`, `checklist_gates` (existing tables) are updated by projectors.
- **New tables:** `events_v2` (event store), `projection_checkpoints` (per-projector progress), `projection_checkpoints` (signal events stored as events, no separate table).
- **Deprecated table:** `pending_signals` is migrated to signal events in S-04, dropped in S-05.
- **Legacy recovery modules:** `db/recovery/recovery.py`, `db/recovery/event_journal.py`, `db/recovery/journal_replay.py` are removed in S-05 after bootstrap and rebuild are proven.

### JSONL Handling

- **Real-time write:** `JsonlOutboxObserver` writes to `history.jsonl` keyed by event position (idempotent on retry).
- **Bootstrap:** On startup with empty `events_v2` table, `bootstrap_from_jsonl()` reads `history.jsonl` and seeds the event store, then rebuilds projections.
- **Format compatibility:** Outbox observer must write legacy-compatible keys (`run_id`, `sequence_number`) OR reader must support both new (`aggregate_id`, `position`) and legacy shapes.

### WorkflowEngine & State Machine

- **Purity preserved:** `WorkflowEngine` remains pure (no I/O); event emission stays synchronous and buffered via `BufferingEmitter`.
- **Projection updates:** Synchronous post-append within the same transaction (current consistency guarantees maintained).
- **Command handlers:** Emit events and return them; `WorkflowService` and other callers use the returned events.

### Deployment & Downtime

- **Strangler-fig approach:** Each milestone is deployable; old and new paths run in parallel during transition.
- **Projection rebuild:** Requires server stop (brief downtime acceptable). Lock-file guard prevents concurrent rebuild attempts.
- **Rollback:** Per-milestone rollback possible by disabling new paths and relying on legacy code (until S-05 cleanup removes legacy code).

### Module Boundary & Import Discipline

All new code respects the 9-module boundary:
- `api`, `cli`, `config`, `db`, `envfiles`, `git`, `runners`, `state`, `workflow`

**Typical placement:**
- Event types: `workflow.events.types`
- Command handlers: `workflow.commands.*`
- Projectors: `db.projections.*`
- Event store: `db.access.event_store_v2`
- Signal transport: `workflow.signals`
- Output batcher: `runners.execution.output_batcher`

---

## Verification Checklist (Pre-Implementation)

Before breaking ground, confirm:

- [ ] **Intent coverage:** All 32 intents are mapped to steps (verified: 32/32 ✓).
- [ ] **Dry-run hardening:** All critical findings from dry-run are applied to step files (verified: all rows marked "YES").
- [ ] **No unresolved conflicts:** Critical contradiction in Step 02 (F2.2-A) is resolved (verified: ✓).
- [ ] **Persistence audit:** All state surfaces (8 rows) have step assignments; no MISSING cells (verified: ✓).
- [ ] **Integration test assertion logic:** Every test specifies what to assert, not just scenario names (verified: ✓ all steps).
- [ ] **Cross-step dependencies:** Chains align with prerequisites in step files (verified: ✓).
- [ ] **Alembic migrations:** Separate `down_revision` for each new migration; single head after all applied (verified: S-01, S-02).

All verifications passed. System is ready for implementation.

---

## Document Reference

| Document | Purpose |
|----------|---------|
| `intent.md` | Complete list of 32 intent items with rationale |
| `plan.md` | High-level milestone descriptions and key decisions |
| `steps/step-0[0-5]-plan.md` | Detailed per-step task breakdown with code examples |
| `dry-run-notes.md` | Simulation results and hardening applied |
| `verification-report.md` | Comprehensive review of step coverage and conflicts |
| `clarifications.md` | Q&A log with user-approved decisions |
| `architecture.md` | Data-flow diagrams, schema SQL, pattern examples |

---

**Next Step:** Begin Step 00 (Pydantic Event Conversion) with Task 0.1.
