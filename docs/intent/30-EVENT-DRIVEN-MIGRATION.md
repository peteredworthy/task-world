# Event-Driven Migration Plan

**Goal:** Make events the **sole driver** of state changes. State must be 100% reconstructible from the event log.

**End state:** Every mutation to `RunModel`, `TaskModel`, `AttemptModel`, `StepModel` is the result of applying an event via a single `apply(state, event)` projection function. The same function is used at runtime and during replay. The DB row becomes a derived cache of the event log; the event log is the source of truth.

**Prerequisites:** None — this plan absorbs and replaces the implicit Phase 3 goal (`13-SLICES-PHASE-3.md`) which was specified but never wired as the runtime read path.

---

## 1. Why

The original design (`13-SLICES-PHASE-3.md:3-5`) committed to "event sourcing for recovery — replay rebuilds state." Phase 2 (`12-SLICES-PHASE-2.md:409`) framed events as "observability." Phase 2 was implemented first and its interpretation became the working pattern. Initial commit `6d5ae012` loaded state from DB rows, mutated Pydantic models, then emitted events as post-mutation audit. Every feature since has followed that pattern.

**Resulting fragility** (concrete examples, all traceable to multi-source-of-truth coordination):

- `oversight_state` JSON blob: 8 direct mutation sites in `parent_oversight.py` + `service.py`, zero event coverage. Reducer reads its own prior output (`oversight.py:265`) — cached accumulator masquerading as projection.
- Four parallel `pause_reason` allowlists (`service.py:106`, `app.py:53`, `oversight.py:571`, `parent_oversight.py:1360`) must stay in sync by hand. Three commits in the last month (`d14ed0d8`, `f7e5bd9f`, `568c2134`) fixed drift between them.
- Cascade pause/resume on server restart loses state because event replay does not reconstruct `oversight_state`, and the `child_spawned`/`child_completed`/`child_failed` events are tagged `informational` (skipped by replay, `recovery.py:41-44`).
- Wall-clock-microsecond fence for child command staleness (`super_parent.py:120`) — would not exist if commands were sequence-ordered events on a per-aggregate log.

The bugs are not implementation defects. They are the predictable consequence of asking concurrent API handlers to coordinate state via three independent stores (SQLite row, in-memory projection, JSON blob accumulator) plus a string-keyed vocabulary repeated across files. An event-sourced model collapses all three stores into one log.

---

## 2. Target Architecture

### 2.1 Single mutation point

```python
# Runtime command handler (formerly: service method)
async def apply_start_run(self, run_id: str) -> None:
    run = await self._repo.get(run_id)              # load current projection
    event = RunStatusChanged(
        run_id=run_id,
        sequence_number=run.next_sequence(),
        timestamp=self._frozen_now(),
        previous_status=run.status,
        new_status=RunStatus.ACTIVE,
    )
    self._projection.apply(run, event)              # in-process mutation via projection
    async with self._repo.transaction() as txn:
        await self._events.append(txn, [event])     # atomic with row write
        await self._repo.save(txn, run)
    await self._outbox.observe(event)               # post-commit side effects
```

The `apply()` function is the **only** place in the codebase that mutates `run.status`, `task.status`, `attempt.outcome`, etc. Replay invokes the same function over events in sequence order. Runtime and replay produce byte-identical state by construction.

### 2.2 Layer responsibilities

| Layer | Owns | Forbidden |
|---|---|---|
| **Command handler** (service/engine) | Validation, event construction, single transaction | Direct field mutation |
| **Projection** (`projection.apply`) | Applying event payload to in-memory state | I/O, randomness, `datetime.now()`, network |
| **Event store** | Append-only durable log, per-aggregate sequencing | State derivation |
| **Repository** | Cached row + index lookup of latest projection | Mutating rows outside an `apply()` call |
| **Outbox** | Post-commit side effects (subprocess, git, file I/O) keyed by `(event_id)` | Mutating run state directly |

### 2.3 Event store contract

- Every event has `aggregate_id` (run_id) + monotonic per-aggregate `sequence_number`.
- `UNIQUE(aggregate_id, sequence_number)` enforced by DB.
- Append is atomic with row cache update (same SQLAlchemy transaction).
- No JSONL fallback in the write path. JSONL becomes a derived export artifact (see §4 phase 0).

### 2.4 Replay contract

- `replay_events(events: Iterable[Event]) -> RunState` is pure. Same input → same output, every call.
- For every event type that affects state, there is an `apply()` handler. No `informational` skip-list.
- Replay starts from an empty `RunState`, applies events in `(aggregate_id, sequence_number)` order.
- Snapshot mechanism (phase 5) caches `RunState` at sequence `N` to avoid replay-from-zero at scale.

---

## 3. Non-Goals

- **Not** removing SQLAlchemy or moving to a different store. Cache stays in SQLite.
- **Not** introducing a new event-streaming infrastructure (Kafka, NATS). In-process append to a DB table is sufficient.
- **Not** rewriting the agent execution path. Builder/verifier/CLI agents unchanged; only the coordination layer changes.
- **Not** changing the public REST API. Endpoint signatures preserved.
- **Not** introducing CQRS read models. The DB row remains the read model; only the write path changes.

---

## 4. Phases

Six phases, each independently shippable. Phases 0–2 deliver most of the stability win even if 3–5 are deferred.

### Phase 0 — Mechanical correctness (1 PR per item, ~1 week total)

Prep work that has value standalone and does not depend on the rest. Land first.

#### 0.1 Per-aggregate sequence numbers
- **Add** `sequence_number: Mapped[int]` column to `EventModel` (`orm/models.py:245`).
- **Add** `UNIQUE(run_id, sequence_number)` index. Alembic migration.
- **Add** `RunModel.next_event_sequence: Mapped[int] = mapped_column(default=0)` — server-side monotonic counter incremented in same transaction as event insert.
- **Bootstrap**: backfill `sequence_number` for existing events by `(run_id, id)` order.
- **Acceptance:** concurrent attempts to insert two events for the same run with the same sequence raise `IntegrityError`; existing test suite passes.

#### 0.2 Row-level optimistic locking on `RunModel`
- **Add** `version: Mapped[int]` column to `RunModel` mirroring `TaskModel.version` (`orm/models.py:175`).
- **Wire** `__mapper_args__ = {"version_id_col": version}`.
- **Acceptance:** two concurrent `apply_start_run` calls for the same run produce one success + one `StaleDataError`; verified by new integration test `tests/integration/test_run_optimistic_lock.py`.

#### 0.3 Freeze timestamps at transition start
- **Change** `ClarificationRequested.__init__` (`events/types.py:182`) and `ClarificationResponded.__init__` (`events/types.py:206`) to require `timestamp: datetime` rather than defaulting to `datetime.now(timezone.utc)`.
- **Audit** all call sites in `engine/engine.py`, `engine/transitions.py`, `service.py` — each transition method must call `now()` exactly once and pass that timestamp to every event it emits.
- **Acceptance:** grep for `datetime.now` inside `events/` returns zero matches; existing tests pass.

#### 0.4 Atomic event journal
Choose one of:
- **(a) Drop JSONL from write path.** Remove `JsonlEventJournal.append_events` from `_persist`. Add `scripts/export_journal.py` that renders `EventModel` rows to JSONL on demand. JSONL becomes an export, not a write target.
- **(c) Promote `EventModel` to journal authority.** Same outcome as (a); keep the table, drop the file write.

Recommendation: **(a)**. Smallest diff, removes the failure mode where DB commit succeeds but file flush crashes.
- **Acceptance:** `aiofiles` no longer imported in `_persist` path; existing journal-replay tests still pass after running export script first.

#### 0.5 Fix broken `approval_requested` replay
- `recovery.py:374-394` currently no-ops the pending state.
- **Add** `Step.approval_pending: bool` field (or extend `HumanApproval` with `pending` flag).
- **Update** projection to set pending on `approval_requested`, clear on `approval_decision`.
- **Acceptance:** new test `tests/unit/test_replay_approval_pending.py` proves replay reconstructs pending state.

**Phase 0 risk:** Low. All changes are additive or local. Reversible per-PR.

---

### Phase 1 — Pilot inversion on one transition (1 PR, ~3 days)

Prove the emit-then-project pattern end-to-end on the simplest transition before refactoring at scale.

**Target:** `apply_start_run` (`service.py:498`).

**Deliverables:**

```
src/orchestrator/
├── workflow/
│   └── projection.py          # NEW — pure apply(state, event) function
└── workflow/
    └── service.py             # MODIFIED — apply_start_run uses projection
tests/unit/
└── test_projection_start_run.py   # NEW — round-trip property test
```

**Implementation:**

1. Create `workflow/projection.py` with `apply(run: Run, event: WorkflowEvent) -> None`. Handle `RunStatusChanged` only.
2. Refactor `apply_start_run`:
   ```python
   # Before: mutate run.status, repo.save, emit
   # After:
   event = RunStatusChanged(...)
   projection.apply(run, event)
   async with txn:
       await events.append(txn, [event])
       await repo.save(txn, run)
   await outbox.observe(event)   # env_lifecycle.on_run_start moves here
   ```
3. Property test: for any sequence of `[apply_start_run, pause, resume, complete]`, replay of events from sequence 0 produces same `RunStatus`, `pause_reason`, `started_at`, `completed_at` as live state.

**Acceptance:**
- `apply_start_run` is the only function in the codebase that emits `RunStatusChanged` for the `DRAFT→ACTIVE` transition (grep proves it).
- Round-trip test passes 1000 randomly-generated transition sequences.
- No regression in `test_api_full_lifecycle.py`.

**Phase 1 risk:** Medium. Surfaces hidden coupling. If pilot fails, the architecture is wrong and we stop before mass refactor.

---

### Phase 2 — Inversion at scale (~2 weeks)

Apply the Phase 1 pattern to all 60+ mutation sites identified in the audit:

| File | Mutation count | Owner |
|---|---|---|
| `workflow/service.py` | 43 | command handlers |
| `workflow/engine/transitions.py` | 44 | core transitions (called by service) |
| `workflow/engine/engine.py` | 14 | top-level run lifecycle |
| `workflow/parent_oversight.py` | 7 | oversight (defer to phase 3) |

**Approach:** one PR per transition family. Order:

1. **Run lifecycle**: start, pause, resume, stop, cancel, complete, fail.
2. **Step transitions**: advance, skip, complete.
3. **Task lifecycle**: build, submit, verify, complete-verification, revert, fail.
4. **Attempt metadata**: grade, auto-verify, agent error, clarification.

Each PR follows the Phase 1 shape: command handler → emit event → projection → atomic write → outbox.

**Deliverables per PR:**
- One transition family migrated.
- `workflow/projection.py` extended with handlers for the new events touched.
- Round-trip property tests for that family.
- All grep results for `run.<field> =` in the migrated file return zero matches outside `projection.py`.

**Acceptance (whole phase):**
- `grep -rn '\.status\s*=' src/orchestrator/workflow/ | grep -v projection.py` returns zero matches.
- All existing integration tests pass.
- New `tests/integration/test_replay_full_lifecycle.py` proves that after a full build→verify→complete run, replaying events from sequence 0 against an empty `Run` produces identical state.

**Phase 2 risk:** Medium-high. Surface area is large. Mitigation: incremental PRs, each independently shippable, with feature flag if needed.

---

### Phase 3 — Cover the gaps (~1 week)

Add event types for the ~20 mutable columns with no event coverage today.

**New event types:**

| Event | Replaces direct write to | Carries |
|---|---|---|
| `oversight_state_changed` | `run.oversight_state` (8 sites) | Full new state OR delta + reason |
| `run_worktree_assigned` | `run.worktree_path`, `run.runner_started_at` | path, started_at |
| `run_metrics_updated` | `run.total_tokens_*`, `run.token_usage_by_model`, `run.total_duration_ms`, `run.total_num_actions` | delta amounts |
| `run_resume_scheduled` | `run.scheduled_resume_at` | scheduled timestamp |
| `attempt_metadata_recorded` | `attempt.runner_type`, `agent_model`, `agent_settings`, `verifier_comment`, `builder_prompt`, `verifier_prompt`, `tokens_*`, `duration_ms`, `action_log_json`, `paused_at` | full metadata bundle |
| `task_fan_out_recorded` | `task.fan_out_output`, `task.child_id` | output, child_id |

**Reclassification:** Move `child_spawned`, `child_completed`, `child_failed`, `fan_out_spawned`, `fan_out_completed` out of `informational` (`recovery.py:41-44`) and add projection handlers. These ARE state changes; they create the parent↔child linkage that drives oversight.

**Deliverables:**
- `events/types.py` extended with new event classes.
- `workflow/projection.py` extended with new `apply()` cases.
- `workflow/parent_oversight.py` and `service.py` direct writes converted to event emission.
- New tests proving each event reconstructs its target column on replay.

**Acceptance:**
- `grep '\.oversight_state\s*=' src/orchestrator/workflow/ | grep -v projection.py` returns zero matches.
- `tests/integration/test_oversight_replay.py` proves that a parent run with 3 child runs, after full lifecycle, can be reconstructed from events alone (drop DB, replay, compare).
- `RECOVERY_MATRIX` in `recovery.py` no longer contains `informational` category for events that carry state.

---

### Phase 4 — Outbox for side effects (~1 week)

Move all I/O out of transition methods into post-commit observers.

**Targets:**

| File:line | Side effect | New observer |
|---|---|---|
| `service.py:514` | `env_lifecycle.on_run_start` | `EnvironmentLifecycleObserver` reacting to `run_status_changed → ACTIVE` |
| `service.py:459, 2220, 3551` | `handle_run_completion`, worktree teardown | `WorktreeTeardownObserver` reacting to terminal `run_status_changed` |
| `service.py:1820, 1052` | `subprocess` launches | `ScriptRunnerObserver` reacting to `task_status_changed → BUILDING` for script tasks |
| `parent_oversight.py:941` | nested write from inside transition | becomes observer reacting to `child_*` events |

**Deliverables:**

```
src/orchestrator/
├── outbox/
│   ├── __init__.py
│   ├── observer.py            # base + dispatch
│   ├── env_lifecycle.py       # NEW observer
│   ├── worktree_teardown.py   # NEW observer
│   └── script_runner.py       # NEW observer
```

**Contract:**
- Observers are async, idempotent, keyed by `(event_id)`.
- Failure to run an observer does NOT roll back the state change. Failed observer attempts are retried via `outbox_pending` table.
- Observers may emit new events (e.g., teardown completion) but cannot mutate state directly.

**Acceptance:**
- No `subprocess`, `aiofiles`, `git` or `worktree_manager` calls in `workflow/service.py` or `workflow/engine/`.
- Observer retry tested: kill server mid-side-effect, restart, side-effect runs to completion.

---

### Phase 5 — Bootstrap legacy + drop redundant cache (~1 week)

Make the event log authoritative for ALL runs (not just post-migration ones), then demote the DB row to derived cache.

#### 5.1 Bootstrap synthetic events

```
scripts/
└── bootstrap_event_log.py     # NEW
```

For every existing `RunModel`, emit synthetic events backdated to `created_at`:
- `run_bootstrapped` carrying full row snapshot (status, pause_reason, current_step_index, oversight_state, worktree_path, metrics, ...)
- Per-step: `step_bootstrapped`
- Per-task: `task_bootstrapped` + per-attempt `attempt_bootstrapped`

**Verification harness:**
- For each run, drop derived columns, replay from sequence 0, compare reconstructed `RunState` to pre-bootstrap DB row. Must match byte-for-byte (modulo non-mutable creation metadata).

**Acceptance:**
- Script runs to completion on a production-size DB (~thousands of runs).
- Verification harness reports 0 mismatches.
- `ReplayCheckpointModel` updated so subsequent replays start after bootstrap events.

#### 5.2 Drop redundant cache columns (optional, lowest priority)

Once event log is proven authoritative, the following columns become pure read cache:
- `run.oversight_state` — derived; can be lazy-computed on read.
- `run.total_tokens_*`, `run.total_duration_ms` — derived from `run_metrics_updated` events.

Decision deferred to phase 5b. Keeping the cache is fine; the constraint is that no code writes to it outside `projection.apply()`.

---

## 5. Migration Risk + Rollback

| Phase | Rollback strategy |
|---|---|
| 0 | Revert per-PR. Each item is additive. |
| 1 | Revert pilot PR. Pattern not adopted at scale; no migration needed. |
| 2 | Per-family PRs revert individually. Mixed state (some transitions inverted, others not) is OK during migration window. |
| 3 | New events can be added without breaking old ones. Reclassifying `informational` is one-line revert. |
| 4 | Observers can be disabled per-event-type via config flag. Inline calls can be reinstated as escape hatch. |
| 5 | Bootstrap script is idempotent. Re-running it produces same events. If verification fails for any run, that run is excluded from bootstrap and remains row-only. |

**Feature flag:** During phases 1–2, add `settings.event_driven_transitions: set[str]` listing which transitions use the new path. Default empty (old behavior); flip per-transition as migrated. Remove flag after phase 2 completes.

---

## 6. Open Questions

1. **Per-aggregate sequence numbers — generated where?** Options: (a) `SELECT MAX(sequence_number) WHERE run_id = ?` in same transaction (simple, contended); (b) sequence column on `RunModel` incremented via `UPDATE runs SET next_event_sequence = next_event_sequence + 1 RETURNING ...` (atomic, row-locked). Recommend (b).

2. **`oversight_state` event payload — full snapshot or delta?** Full snapshot is simpler to replay; delta is smaller and matches the reducer's natural input. Recommend full snapshot until we measure size; the BLOB is rarely >10KB.

3. **Backfill events for legacy runs — what timestamp?** Options: (a) all backdated to `run.created_at` (loses ordering); (b) reconstruct from `updated_at` + `EventModel.created_at` for each field. (b) is more accurate but more code. Recommend (a) for bootstrap simplicity — these events exist for replay only, not audit.

4. **Outbox retry boundary.** When an observer fails permanently (e.g., worktree teardown can't delete a locked file), what is the escalation? Options: (a) emit a `side_effect_failed` event, surface in UI; (b) retry forever. Recommend (a).

5. **Replay performance at scale.** Without snapshots, a 10,000-event run replays in ~? seconds. If unacceptable, add `RunSnapshotModel` cached every N events. Defer until measured.

6. **MCP / external agent commands.** External agents post commands via MCP (`api/mcp/server.py:484`). These currently land in `parent_oversight.py` and mutate `oversight_state` directly. Migration must route them through command handlers that emit events. No structural blocker, just refactor scope.

---

## 7. Acceptance for "Done"

The migration is complete when **all** of the following are true:

1. `grep -rn '\.status\s*=\s*\(Run\|Task\|Attempt\)Status\.' src/orchestrator/ | grep -v 'projection.py'` returns zero matches.
2. `grep -rn '\.oversight_state\s*=' src/orchestrator/ | grep -v 'projection.py'` returns zero matches.
3. `grep -rn 'datetime\.now' src/orchestrator/events/` returns zero matches.
4. For any run in the system, `drop_columns_and_replay(run_id)` produces an identical `RunState` to the pre-drop row, verified for 100% of runs in a production-size DB.
5. The four `pause_reason` allowlists collapse to one shared module.
6. `_SELF_PAUSING_REASONS` and `_is_startup_recoverable_pause_reason` are deleted; recovery is driven by event replay, not string matching.
7. New integration test `tests/integration/test_concurrent_writers_safe.py` proves that two concurrent API requests mutating the same run never produce inconsistent state (one succeeds, one retries cleanly).
8. The graph-approach docs in `docs/graph-approach/` can be implemented (or deferred) on top of this foundation without re-introducing the multi-store coordination problem.

---

## 8. Effort Estimate

| Phase | Calendar | Engineer time |
|---|---|---|
| 0 | 1 week | 4-5 days |
| 1 | 3 days | 2 days |
| 2 | 2-3 weeks | 10-12 days |
| 3 | 1 week | 4-5 days |
| 4 | 1 week | 4-5 days |
| 5 | 1 week | 3-4 days |
| **Total** | **~7 weeks** | **~30 engineer-days** |

Phases 0–2 alone (~3.5 weeks, ~17 days) deliver most of the stability win. Phases 3–5 can be deferred or run in parallel with other work.

---

## 9. References

- `docs/intent/13-SLICES-PHASE-3.md` — original event-sourcing spec, never wired to runtime
- `docs/intent/12-SLICES-PHASE-2.md:409` — competing "events are observability" constraint
- `docs/intent/01-ARCHITECTURE.md:179` — design statement of event sourcing
- `docs/intent/26-SLICES-PHASE-11` — super-parent feature that exposed the coordination weakness
- `docs/graph-approach/` — dynamic intent graph proposal that should sit on top of the event-driven foundation, not alongside it
- Commits documenting the recurring fragility: `d14ed0d8`, `f7e5bd9f`, `568c2134`, `672efc7`, `a4b28d1`
