# Plan: Event-log Durability

Planning mode: incremental oversight

## Overview

This is a large slice because it crosses storage schema, event append ordering, projection rebuild, migration safety, crash behavior, and e2e workflow verification. The first executable slice is intentionally narrow: prove that the real verification path can observe a workflow event stream, rebuild disposable projections from a database-backed event log, and compare equivalent run/task state using real SQLite and real journal files.

The plan below does not decompose the full implementation into phases. Later slices are deferred until the first proof slice produces evidence about the existing event abstractions, projection rebuild entry points, and test harness viability.

## Resolved Design Questions

No open human design questions remain for this planning pass.

- The missing graph references have been restored as `docs/graph-approach/execution-graph-prd-plus.md` and `docs/graph-approach/execution-graph-evaluation.md`.
- The restored references reinforce the same decision already captured here: `events_v2` is the authoritative event log, projection tables are disposable, and `.orchestrator/state/history.jsonl` is a secondary sink/import source.
- The next slice should work with the existing implementation surfaces rather than start from an empty design: `EventV2Model`, `SqliteEventStore`, `PersistentEventEmitter`, `ProjectionRegistry`, run/task projectors, JSONL bootstrap, and the restore wrapper already exist.

## First Executable Slice

### Slice 1: Verification-path proof for DB-authoritative events

Build the smallest vertical proof that can fail for the right reasons:

- Verify and harden the existing `events_v2` schema and migration in additive form.
- Use the existing event-store adapter to append and read enough workflow events to support one real lifecycle path.
- Keep the existing journal path present as a secondary outbox/import path, while the database event row remains the authoritative record.
- Add a rebuild drill in a temporary SQLite database that runs real workflow activity, captures run/task projection state, drops the relevant projection tables or clears their rows, rebuilds from `events_v2`, and compares state.
- Add a crash/retry drill around append boundaries that proves uniqueness constraints and stable event identity prevent loss or duplication.

## Exact Assumption Being Tested

The existing event model and projection code can be made to use a database event log as the source of truth without first rewriting the entire workflow engine or REST API.

## Target Failing Behavior Or Missing Proof

Today the planning premise lacks proof that a real workflow can be reconstructed from a DB-backed event log alone after projections are removed. The target missing proof is an executable e2e or integration drill that:

- creates real workflow activity,
- persists accepted events into `events_v2`,
- removes projection state,
- rebuilds from `events_v2`,
- asserts the rebuilt run/task state matches the pre-drop state,
- verifies retry after interrupted append does not duplicate or lose accepted events.

## Real Verification Surface

Final proof for this first slice must run through real project surfaces:

- SQLAlchemy metadata and Alembic migration for `events_v2`.
- Real SQLite database, preferably temp-file SQLite for migration and crash drills.
- Real temporary JSONL journal file for import and secondary-sink behavior.
- Real workflow service/API/CLI surface sufficient to create run and task activity.
- Real projection rebuild code, not a generated shim or file-existence check.
- `uv run pytest` against the targeted unit, integration, and e2e tests.

## Milestones

### Milestone 1: Evidence Harness

- Identify the smallest real workflow activity that produces durable run/task events.
- Add the test fixture shape using temp-file SQLite and temporary journal paths.
- Capture pre-rebuild state through the same read models the application uses.

### Milestone 2: Minimal `events_v2` Authority

- Add the additive schema and migration.
- Append accepted events to `events_v2` before projection updates in the selected proof path.
- Read events back in deterministic order using stable event IDs and per-aggregate sequence numbers.

### Milestone 3: Rebuild And Crash Proof

- Drop or clear disposable projection state in the test database.
- Rebuild from `events_v2` alone and compare run/task state.
- Exercise interrupted append/retry behavior and assert no event loss or duplication.

## Implementation Order

1. **Step 1: Confirm reference certainty**
   - Prerequisites: None.
   - Deliverables: Treat `docs/graph-approach/execution-graph-prd-plus.md` and `docs/graph-approach/execution-graph-evaluation.md` as restored references; document any later conflict between those references and implementation evidence as a replan trigger.

2. **Step 2: Define the proof state comparison**
   - Prerequisites: Step 1.
   - Deliverables: A test helper that captures the canonical run/task fields to compare before and after rebuild, excluding volatile timestamps only when the existing domain model explicitly treats them as non-deterministic.

3. **Step 3: Harden additive `events_v2` storage**
   - Prerequisites: Step 2.
   - Deliverables: SQLAlchemy model, Alembic migration, append/read repository, and constraints for stable event identity, aggregate ordering, and idempotent import/retry. Existing surfaces should be reused where they satisfy the contract and extended where they do not.

4. **Step 4: Route one real event path through `events_v2`**
   - Prerequisites: Step 3.
   - Deliverables: One workflow path where event append succeeds in `events_v2` before the projection update commits, with journal write demoted to best-effort behavior.

5. **Step 5: Prove rebuild and crash behavior**
   - Prerequisites: Step 4.
   - Deliverables: Real tests for projection drop/rebuild equivalence and interrupted append/retry behavior.

## Replan And Stop Conditions

- Stop if the real workflow test cannot create durable run/task activity without requiring unrelated engine rewrites.
- Stop if current projection code cannot rebuild from event data without a larger event taxonomy change.
- Stop if event ordering cannot be made deterministic from existing event payloads plus additive metadata.
- Stop if the crash drill exposes a transaction boundary where an event can be considered accepted before `events_v2` commit.
- Stop if the restored graph-approach reference documents are found to contain requirements that materially change the first proof slice.

## Evidence Artifacts To Capture

- Alembic migration revision name and generated SQL shape for `events_v2`.
- Test names and command output for targeted `uv run pytest` runs.
- Before/after serialized run/task state from the rebuild drill.
- Event counts and sequence ranges before crash, after retry, and after rebuild.
- Backup file paths and verification output from migration/import tests.
- Notes from the required human review gate before any cutover-like migration behavior.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Planning mode | Incremental oversight | The work spans multiple subsystems and must first prove the verification path. |
| First proof target | One real workflow path plus rebuild/crash drills | This validates the architecture before broad migration of all event write paths. |
| Event authority | `events_v2` | The slice goal explicitly makes the DB-backed log authoritative. |
| Journal role | Best-effort secondary sink | Existing journal users remain supported while journal write failure stops being fatal. |
| Migration safety | Backup-before-import is mandatory | The live journal and database are precious data. |
| Test style | Real DB/files, no mocks or monkeypatching | Matches project constraints and makes durability claims meaningful. |
| Reference status | Graph references restored | Planning can proceed without a clarification gate about missing files. |

## Deferred Slice Candidates

These are not yet planned and must wait for Slice 1 evidence:

- Migrate every event write/read call site to the `events_v2` store.
- Expand rebuild coverage from run/task projections to all derived projection tables.
- Build the full journal import/cutover command for production-like repositories.
- Add operational rollback and export tooling around `events_v2`.
- Remove any remaining dependency on JSONL ordering in recovery paths.
- Add performance tuning, batching, or snapshots for large event logs.

## References

- `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`
- `routines/_archived/idea-to-plan/scaffolding/plan.md`
- `docs/graph-approach/execution-graph-prd-plus.md`
- `docs/graph-approach/execution-graph-evaluation.md`
