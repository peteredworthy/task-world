# Event-Log Durability Verification Report

## Status

Status: ✓ Ready to execute as slice 1.

The routine has one executable YAML step:
`routines/event-log-durability/steps/step-01-plan.yaml`. It aligns with the
incremental oversight plan by proving one real workflow path, database-backed
event authority, projection rebuild, and crash/retry durability before broader
cutover work is claimed.

## Dry-Run Gap Application

Every critical or significant dry-run gap is marked `YES` in
`docs/event-log-durability/dry-run-notes.md` and is reflected in the YAML step:

| Gap Area | Applied To YAML |
| --- | --- |
| Restored reference and executable step-plan checks | YES |
| `create_wired_event_store_v2` standard wiring check | YES |
| Canonical projection coverage for runs, steps, tasks, attempts | YES |
| Deterministic JSON normalization and volatile-field discipline | YES |
| Explicit retry/import identity decision | YES |
| Schema uniqueness/idempotency checks beyond column existence | YES |
| Duplicate tests asserting row counts and ordered streams | YES |
| Real workflow/service/API authority proof | YES |
| Projection rollback vs secondary JSONL failure distinction | YES |
| Rebuild from ordered `events_v2` after projection clearing | YES |
| `projection_checkpoints` clearing or explicit deferral | YES |
| No skip/xfail rebuild proof | YES |
| Separate pre-commit and post-commit crash/retry coverage | YES |
| Expanded forbidden mocking scan | YES |

No critical or significant gap has `NO` or a missing applied field. There are no
unresolved critical conflicts.

## Persistence Mapping Audit

The dry-run notes state that no new state model fields were added by the
dry-run merge. The persistence mapping table has no `MISSING` cells. Each
planned durability surface has an authoritative source, projection/consumer,
required persistence detail, and YAML status:

| Surface | YAML Coverage |
| --- | --- |
| Accepted workflow events | T-03, T-05 |
| Duplicate aggregate sequence | T-03, T-05 |
| Standard event-store wiring | T-01, T-06 |
| JSONL journal continuity | T-06 |
| Run, step, task, attempt projections | T-02, T-07 |
| Projection checkpoints | T-07 |
| Crash/retry evidence | T-08 |

Result: no persistence mapping update is required.

## Auto-Verify Quality

All tasks now have a contract-level strongest auto-verify check. Static grep
checks remain as supplementary guards, but no task relies only on file
existence or weak text presence as its strongest proof.

| Task | Strongest Auto-Verify Check | Classification |
| --- | --- | --- |
| T-01 | Imports `EventV2Model`, `SqliteEventStore`, `create_wired_event_store_v2` and asserts required columns/callables plus scope checks | Contract-level |
| T-02 | Runs pytest selection for canonical projection state/snapshot helper | Contract-level |
| T-03 | Runs schema/migration/ordering tests and asserts aggregate/version uniqueness | Contract-level |
| T-04 | Runs event-store unit/integration regressions and ordered-read durability tests | Contract-level |
| T-05 | Runs duplicate tests and requires row-count/stream assertions | Contract-level |
| T-06 | Runs workflow/authority/journal tests through real wiring and checks secondary-sink boundary evidence | Contract-level |
| T-07 | Runs rebuild drill, requires `events_v2` replay after projection clearing, and forbids skip/xfail | Contract-level |
| T-08 | Runs crash/retry tests and requires pre-commit plus post-commit boundary evidence | Contract-level |
| T-09 | Runs full durability tests and existing event-store/projection regressions | Contract-level |

Existence-only strongest checks: none.

## Integration Test Quality

The integration-test tasks specify assertion logic, not only scenario names:

| Task | Required Assertion Logic |
| --- | --- |
| T-03 | Assert schema columns, aggregate/version unique constraint, migration/ordering behavior, and retry/import identity decision. |
| T-05 | Assert duplicate attempts do not create a second row and ordered stream contents remain correct. |
| T-06 | Assert real workflow/service/API path creates observable `events_v2` rows before committed projections; assert JSONL failure does not roll back accepted DB rows. |
| T-07 | Assert projections are cleared, rebuild reads ordered `events_v2` rows, checkpoints are handled, and canonical before/after state matches. |
| T-08 | Assert pre-commit interruption creates no accepted event and post-commit retry creates no duplicate. |
| T-09 | Assert real targeted pytest commands pass and forbidden mocking tokens are absent. |

Result: integration assertion logic is sufficient.

## Intent Coverage

Intent coverage: complete for the slice-1 executable contract. Items that are
full cutover concerns are covered as guarded/deferred evidence requirements and
must not be claimed complete unless implemented in the slice.

| Intent Item | YAML Coverage |
| --- | --- |
| I-01 | T-06 |
| I-02 | T-02, T-07 |
| I-03 | T-06 |
| I-04 | Step scope guard, T-09 backup/import evidence if touched |
| I-05 | T-06, T-07, T-08 |
| I-06 | T-03, T-05 |
| I-07 | T-06 |
| I-08 | T-04, T-09 |
| I-09 | T-06 |
| I-10 | Step scope guard, T-09 backup/import evidence if touched |
| I-11 | T-07 |
| I-12 | T-06, T-07, T-08, T-09 |
| I-13 | T-01, T-09 |
| I-14 | Step scope guard |
| I-15 | Step scope guard, T-06 |
| I-16 | Step scope guard |
| I-17 | Step scope guard, T-01 |
| I-18 | Step scope guard |
| I-19 | T-09 backup/import evidence if touched |
| I-20 | T-09 backup/import evidence if touched |
| I-21 | T-03, T-05, T-08 |
| I-22 | T-07 |
| I-23 | T-03, T-08 |
| I-24 | T-06, T-07, T-08, T-09 |
| I-25 | T-06, T-09 |
| I-26 | T-01 |
| I-27 | T-03 |
| I-28 | T-06 |
| I-29 | T-06 |
| I-30 | T-09 backup/import evidence if touched; explicit deferred-cutover guard if not touched |
| I-31 | T-07 |
| I-32 | T-07 |
| I-33 | T-08 |
| I-34 | T-04, T-09 |
| I-35 | T-09 |
| I-36 | T-09 |

## Incremental Oversight Readiness

Planning mode is `incremental oversight`, and exactly one executable YAML step
exists under `routines/event-log-durability/steps/`.

Assumption under test: the existing `events_v2` model, `SqliteEventStore`,
service/API event wiring, and `ProjectionRegistry`/projectors can prove one
durable workflow run/task lifecycle without replacing the workflow engine.

Target behavior or missing proof: accepted events for the proof path are written
to `events_v2` before committed projection state, can be ordered and replayed
from the database alone, survive retry without duplication, and do not depend on
the JSONL journal for acceptance or rebuild.

Real verification surface: SQLAlchemy metadata, Alembic migration SQL,
temporary SQLite files, temporary JSONL journal files, the standard
`create_wired_event_store_v2` service/API dependency path, real event-store
reads/writes, and existing `ProjectionRegistry`/projector code.

Stop/replan conditions:

- Real workflow activity cannot create durable run/task events without unrelated
  workflow engine rewrites.
- Existing real-surface tests already fully cover the missing proof.
- Required SQLite, Alembic, journal, workflow, or projection rebuild surfaces
  cannot run in this environment.
- The slice expands beyond one workflow path plus rebuild/crash drills.
- Implementation evidence contradicts restored graph references.
- Projection rebuild needs a larger event taxonomy change.
- Deterministic event ordering cannot be achieved from existing payloads plus
  additive metadata.
- Crash/retry shows an event can be considered accepted before `events_v2`
  commit.
- A fallback or shim passes while the real verification path fails.

Evidence artifacts:

- Migration revision and inspected/generated `events_v2` SQL shape.
- Exact `uv run pytest` commands and relevant output.
- Before/after canonical projection snapshots.
- Event counts and aggregate version ranges.
- Temporary database and journal path patterns.
- Backup/import evidence if migration/import behavior is touched.
- Graph-reference conflict status.
- Next-cycle recommendation.

## Builder Reference Recheck

Rechecked on 2026-06-11 for the step-01 builder gate:

- Inspected `docs/graph-approach/execution-graph-prd-plus.md`,
  `docs/graph-approach/execution-graph-evaluation.md`,
  `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`, and
  `docs/event-log-durability/step-01-plan.md`.
- Conflict status: no conflict found between the restored graph references,
  the event-driven migration intent, and the current slice-1 durability plan.
  If later implementation evidence contradicts these references, treat that as
  a replan trigger rather than broadening this step.
- Scope status: this remains limited to one workflow path plus rebuild/crash
  drills. No `step-02-plan.md` or later executable step plan exists under
  `docs/event-log-durability/`.
- Cutover status: production-like migration/import cutover is still deferred
  unless a later implementation slice explicitly touches it and captures backup
  and import evidence.

Preserved stop/replan conditions for handoff:

- Real workflow activity cannot create durable run/task events without
  unrelated workflow engine rewrites.
- Existing real-surface tests already fully cover the missing proof.
- Required SQLite, Alembic, journal, workflow, or projection rebuild surfaces
  cannot run in this environment.
- The chosen slice expands beyond one workflow path plus rebuild/crash drills.
- Implementation evidence contradicts the restored graph references.
- Projection rebuild needs a larger event taxonomy change.
- Deterministic event ordering cannot be achieved from existing payloads plus
  additive metadata.
- The crash drill shows an event can be considered accepted before the
  `events_v2` commit.
- A fallback or shim passes while the real verification path fails.

## Masked Verification Check

No frontend work is in scope. Integration readiness is based on blocking
`uv run pytest` commands with `must: true`; there are no `must: false` real
surface commands, fallback-only harnesses, shim-only checks, or commands that
report success after the real surface fails.

## Final Determination

The output is ready to execute as slice 1. It does not need to return to
planning before execution.
