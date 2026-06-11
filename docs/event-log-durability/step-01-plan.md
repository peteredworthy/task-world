# Step 01 - Verification-Path Proof For DB-Authoritative Events

## Assumption Under Test

The existing `events_v2` event model, event-store adapter, and projection rebuild surfaces can prove one real workflow run/task lifecycle is recoverable from the database event log without rewriting the workflow engine or REST API first.

## Target Behavior Or Missing Proof

The missing proof is an executable durability drill that creates real workflow activity, persists accepted workflow events to `events_v2`, removes disposable run/task projection state, rebuilds those projections from `events_v2`, and verifies retry at append boundaries does not lose or duplicate accepted events.

## Real Verification Surface

Exercise the real SQLAlchemy and Alembic `events_v2` schema, temp-file SQLite databases, temporary JSONL journal files, existing workflow service/API/CLI surface sufficient to create run and task activity, existing event-store read/write code, and existing projection registry/projector rebuild path.

## Functional Contract

### Inputs

| Input | Contract |
|-------|----------|
| Restored references | `docs/graph-approach/execution-graph-prd-plus.md` and `docs/graph-approach/execution-graph-evaluation.md` are treated as authoritative references unless implementation evidence contradicts them. |
| Workflow activity | A smallest real workflow path that creates observable run and task lifecycle events through existing application surfaces. |
| Event authority | Accepted events must be appended to `events_v2` before corresponding projection updates are considered committed for the proof path. |
| Secondary journal | A temporary `.orchestrator/state/history.jsonl`-style file remains present as a secondary sink/import source and must not be required for successful projection rebuild. |
| Projection snapshot | Canonical run/task fields read through application read models before projection clearing. Volatile timestamps may be excluded only when existing domain models explicitly treat them as non-deterministic. |

### Outputs

| Output | Contract |
|--------|----------|
| Evidence harness | Tests or fixtures using real temp-file SQLite databases and real temporary journal files. |
| Hardened storage proof | Confirmed or additive `events_v2` schema/model/migration behavior for stable event identity, per-aggregate ordering, deterministic reads, and idempotent import/retry. |
| Rebuild drill | A test that clears or drops disposable run/task projection state, rebuilds from ordered `events_v2` rows alone, and compares rebuilt state with the pre-clear snapshot. |
| Crash/retry drill | A test around append retry boundaries showing accepted events are neither duplicated nor lost. |
| Handoff notes | Evidence artifacts listed below are recorded for the next planning or implementation cycle. |

### Error Cases

| Error | Required Handling |
|-------|-------------------|
| Duplicate stable event identity | The append/import path must be idempotent or fail with an explicit constraint-backed error that does not create duplicate accepted events. |
| Duplicate aggregate sequence | The database must reject conflicting `(aggregate_id, version)` or equivalent per-aggregate ordering keys. |
| JSONL write failure | The database event row remains authoritative; journal failure is captured as secondary-sink evidence and must not invalidate the accepted DB append. |
| Rebuild mismatch | Stop and return to planning with the before/after serialized state and event stream evidence. |
| Missing deterministic ordering metadata | Stop and replan instead of broadening the slice into an event taxonomy rewrite. |

## Dependencies

- No earlier executable step plan is required; this is the first and only executable step under incremental oversight.
- The references in `docs/graph-approach/` must stay consistent with the first-slice premise that `events_v2` is authoritative and projections are disposable.
- Existing surfaces to inspect and reuse include `EventV2Model`, `SqliteEventStore`, `PersistentEventEmitter`, `ProjectionRegistry`, run/task projectors, JSONL bootstrap/import behavior, and the restore wrapper.
- Later event-log durability slices are deferred until this step leaves evidence about event abstractions, projection rebuild entry points, and test harness viability.

## Stop Or Replan Conditions

- Stop if the real workflow path cannot create durable run/task activity without unrelated workflow engine rewrites.
- Stop if the bug or missing proof cannot be reproduced because projection rebuild from `events_v2` is already fully covered by existing real-surface tests.
- Stop if the environment cannot run the required real SQLite, Alembic, journal, workflow, or projection rebuild surface.
- Stop if the chosen slice expands beyond one workflow path plus rebuild/crash drills.
- Stop if implementation evidence contradicts the restored graph-approach references or materially changes the first proof slice.
- Stop if current projection code cannot rebuild from event data without a larger event taxonomy change.
- Stop if event ordering cannot be made deterministic from existing payloads plus additive metadata.
- Stop if the crash drill exposes a transaction boundary where an event can be considered accepted before the `events_v2` commit.
- Stop if real verification fails while a fallback/shim passes.

## Evidence Artifacts

- The Alembic migration revision name, if a migration is added, and the generated or inspected SQL shape for `events_v2`.
- Test file names and exact targeted commands, including relevant `uv run pytest ...` output.
- Serialized before/after canonical run/task state from the rebuild drill.
- Event counts and aggregate sequence ranges before crash, after retry, and after rebuild.
- Temporary database and journal paths used by the tests, plus backup/import verification output if migration/import behavior is exercised.
- Notes identifying any conflict between restored graph-approach references and implementation evidence.
- A short recommendation for whether the next cycle should broaden event write-path migration, expand projection rebuild coverage, or replan.

## Verification Approach

### Automated Verification

- Add targeted unit tests only for pure ordering, serialization, or idempotency helpers introduced by this slice.
- Add integration tests that run Alembic against temp-file SQLite, validate `events_v2` constraints, append/read events through the real store, and verify duplicate identity and duplicate aggregate-order behavior.
- Add a real rebuild drill that creates run/task workflow activity, captures canonical read-model state, clears disposable projection rows, rebuilds from `events_v2`, and asserts equivalence.
- Add a crash/retry drill using real database transaction boundaries and filesystem paths; do not use `patch`, `MagicMock`, or monkeypatching.

### Manual Verification

- Review the captured evidence artifacts before any follow-on slice is planned.
- Confirm the step created no `step-02-plan.md` or later executable step plan under `docs/event-log-durability/`.
- Confirm any later slice remains listed only in `docs/event-log-durability/plan.md` under deferred candidates until this proof completes.
