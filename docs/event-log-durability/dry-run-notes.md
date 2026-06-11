# Event-Log Durability Dry-Run Notes

## Summary

This file consolidates the per-step dry-run notes in `docs/event-log-durability/dry-run/`.
The current routine has one executable step, `Step 01 - Verification-Path Proof For
DB-Authoritative Events`, with tasks T-01 through T-09. The dry run found that the
incremental oversight shape is sound, but several checks needed hardening so the next slice
cannot pass with schema-only stubs, weak greps, in-memory replay, or simulated durability
evidence.

The recommended plan changes have been applied to
`routines/event-log-durability/steps/step-01-plan.yaml`.

## Per-Step Simulation Results

| Step / Task | Result | Key Risks Found | Applied to step files |
|-------------|--------|-----------------|-----------------------|
| T-01 - Confirm references and define proof boundaries | Viable | Reference check omitted `docs/event-log-durability/step-01-plan.md`; event-store import check did not prove standard wiring; conflict handling needed to remain a replan trigger | YES |
| T-02 - Add canonical projection-state comparison helper | Viable with stricter comparison rules | Helper could omit projection fields or pass grep-only checks without covering runs, steps, tasks, and attempts; JSON ordering could create noisy diffs | YES |
| T-03 - Confirm events_v2 schema and migration contract | Viable if retry identity is explicit | Baseline schema has global position and aggregate/version uniqueness, but no separate stable import identity; column-only checks could miss uniqueness constraints | YES |
| T-04 - Verify event-store append and ordered reads | Viable | Direct store tests could pass while active services bypass the wired store; mixed-aggregate ordering and call-site compatibility remain important | YES |
| T-05 - Add duplicate-prevention durability tests | Viable if row counts are asserted | Duplicate tests could only catch an exception without proving no second row was accepted; aggregate sequence and stable identity coverage could be conflated | YES |
| T-06 - Prove DB append authority and secondary journal behavior | High-risk but necessary | Workflow authority could be tested only with fabricated store calls; post-commit JSONL failure semantics needed explicit evidence; projection failure and secondary-sink failure are different boundaries | YES |
| T-07 - Add projection rebuild durability drill | Viable with checkpoint and source controls | Drill could replay pre-captured in-memory events instead of reading `events_v2`; clearing projections could leave stale `projection_checkpoints`; skipped rebuild tests could mask missing proof | YES |
| T-08 - Add crash/retry durability drill | Viable with transaction-boundary proof | A single retry test could miss pre-commit rollback or post-commit duplicate behavior; process-kill simulation is unnecessary if real transactions prove the boundary | YES |
| T-09 - Record evidence and run targeted verification | Viable | Evidence could omit migration SQL, before/after state, event counts, temp paths, or next-cycle recommendation; mock scans only covered one possible file | YES |

## Persistence Mapping Audit

No new state fields were added by this dry-run merge. The audit below maps the planned
durability surfaces that the next implementation slice must prove.

| State / Event Surface | Authoritative Source | Projection / Consumer | Required Persistence Detail | Status |
|-----------------------|----------------------|-----------------------|-----------------------------|--------|
| Accepted workflow events | `events_v2` | `SqliteEventStore.get_stream()` / `get_all()` | Durable `position`, `aggregate_id`, `event_type`, `payload`, `timestamp`, per-aggregate `version`, and explicit retry/import identity decision | Applied to T-03/T-05 |
| Duplicate aggregate sequence | `events_v2` unique constraint | Append/import retry path | Constraint-backed rejection or idempotent handling; duplicate attempt must not create a second accepted row | Applied to T-03/T-05 |
| Standard event-store wiring | `create_wired_event_store_v2` and service/API dependency path | Workflow service/API event emission | Real path must create observable `events_v2` rows, not only direct repository calls | Applied to T-01/T-06 |
| JSONL journal continuity | Best-effort JSONL secondary sink | Legacy journal readers/import tools | Temporary journal exercised; write failure cannot invalidate accepted DB event row | Applied to T-06 |
| Run, step, task, attempt projections | Ordered `events_v2` replay | `ProjectionRegistry`, run/task projectors | Canonical deterministic fields compare equal before and after clearing projections and rebuilding | Applied to T-02/T-07 |
| Projection checkpoints | Ordered replay position | `projection_checkpoints` | Clear or explicitly defer checkpoint correctness during rebuild drill | Applied to T-07 |
| Crash/retry evidence | SQLite transaction boundary and constraints | Append retry path | Pre-commit interruption creates no accepted event; post-commit retry creates no duplicate | Applied to T-08 |

## Incremental Oversight Audit

| Audit Item | Result |
|------------|--------|
| Assumption tested | The existing `events_v2` model, `SqliteEventStore`, emitter wiring, and projector rebuild surfaces can prove one real workflow run/task lifecycle is recoverable from the DB event log without rewriting the workflow engine or REST API. |
| Real verification surface | SQLAlchemy metadata, Alembic migration, temp-file SQLite, temporary JSONL journal file, existing workflow service/API surface, real event-store reads/writes, and existing `ProjectionRegistry`/projectors. |
| Stop/replan conditions | Stop if real workflow activity cannot produce durable run/task events; if projection rebuild needs a larger event taxonomy change; if deterministic ordering cannot be achieved; if a crash drill shows acceptance before DB commit; if implementation evidence conflicts with restored graph references; if fallback verification passes while real verification fails. |
| Evidence artifacts required | Migration revision/SQL shape, exact `uv run pytest` commands/output, serialized before/after projection state, event counts and aggregate sequence ranges, temp DB/journal paths, backup/import evidence if touched, graph-reference conflict note, and next-cycle recommendation. |
| Continue or stop after dry-run execution | Continue. The dry run found hardening actions, not a contradiction requiring a stop. The first implementation slice remains one real workflow path plus rebuild/crash drills. |

## Failure Mode Analysis

| Step | Failure Mode | Likelihood | Hardening Action | Applied to step files |
|------|--------------|------------|------------------|-----------------------|
| T-01 | Restored references or the executable step plan are not actually checked | Medium | Added `docs/event-log-durability/step-01-plan.md` to `references_exist` | YES |
| T-01 | Store imports pass while standard service wiring still bypasses the durable store | Medium | Added `create_wired_event_store_v2` to the contract import check and kept service/API proof in T-06 | YES |
| T-02 | Projection helper omits relevant rows or masks mismatches | High | Required deterministic coverage of runs, steps, tasks, and attempts, with justified volatile-field exclusions | YES |
| T-02 | JSON fields compare unreliably by incidental ordering | Medium | Required deterministic JSON normalization before comparison | YES |
| T-03 | Schema check sees columns but misses uniqueness/idempotency constraints | High | Strengthened metadata check to inspect the aggregate/version unique constraint and require an explicit retry/import identity decision | YES |
| T-04 | Direct store tests pass while active call sites regress | Medium | Kept event-store regressions and required workflow/service wiring evidence in T-06 | YES |
| T-05 | Duplicate test catches an error but does not prove no duplicate row exists | High | Required row-count and ordered-stream assertions after duplicate attempts | YES |
| T-05 | Stable identity and aggregate sequence duplicate cases are conflated | Medium | Required duplicate test names/evidence covering identity, retry, or aggregate behavior | YES |
| T-06 | Journal failure is mistaken for projection transaction failure | Medium | Required evidence distinguishing projection rollback from post-commit secondary-sink failure | YES |
| T-06 | Workflow authority proof uses fabricated events only | High | Required a real service/API dependency-path assertion | YES |
| T-07 | Rebuild uses an in-memory event list captured before clearing projections | High | Required reading ordered events from `events_v2` after projection rows are cleared | YES |
| T-07 | Stale `projection_checkpoints` leave misleading recovery state | Medium | Required clearing checkpoints or explicitly deferring checkpoint correctness | YES |
| T-07 | Rebuild proof is skipped or xfailed | Medium | Added a no skip/xfail check for the durability test file | YES |
| T-08 | Crash drill covers retry but not rollback before commit | Medium | Required both pre-commit and post-commit boundary coverage | YES |
| T-09 | Evidence file omits the artifacts needed for follow-on planning | Medium | Kept explicit evidence artifact list and next-cycle recommendation requirement | YES |
| T-09 | Mocking is hidden in a helper file | Low | Expanded forbidden mocking scan to all event-log durability integration test files | YES |

## Cross-Step Risk Synthesis

- T-03 and T-05 are coupled: retry/import identity must be decided before duplicate-prevention tests can make a durable claim.
- T-04 and T-06 are coupled: ordered store behavior is necessary but insufficient unless at least one real workflow/service/API path uses the wired durable store.
- T-02 and T-07 are coupled: the rebuild drill is only meaningful if the canonical comparison helper includes all deterministic projection fields.
- T-06, T-07, and T-08 share the accepted-event boundary. Projection failures should roll back the DB event transaction, while JSONL failures after DB acceptance should not erase the event row.
- T-07 and T-09 share evidence needs: before/after projection snapshots, event counts, and sequence ranges must be captured where verification failures are diagnosable.
- Migration/import backup behavior is not proven by this planning-only dry run. If the implementation slice touches import or cutover behavior, backup evidence must be collected before claiming that surface.

## Plan Changes Recommended

| Change | Applied to step files |
|--------|-----------------------|
| Add `docs/event-log-durability/step-01-plan.md` to reference checks | YES |
| Include `create_wired_event_store_v2` in the event-store contract import check | YES |
| Require canonical projection helper coverage for runs, steps, tasks, and attempts | YES |
| Require deterministic JSON normalization and justified volatile-field omissions | YES |
| Make retry/import identity explicit in T-03/T-05 | YES |
| Strengthen schema verification to inspect uniqueness constraints, not only columns | YES |
| Require duplicate tests to assert row counts and ordered stream contents | YES |
| Require workflow authority proof through a real service/API dependency path | YES |
| Distinguish projection rollback from post-commit secondary JSONL failure | YES |
| Require rebuild to read ordered rows from `events_v2` after projection clearing | YES |
| Require clearing `projection_checkpoints` or an explicit checkpoint deferral note | YES |
| Forbid skipped/xfail rebuild proof in the durability test file | YES |
| Require separate pre-commit and post-commit crash/retry boundary coverage | YES |
| Expand forbidden mocking scan to event-log durability helper files | YES |

## Source Notes

Consolidated from `docs/event-log-durability/dry-run/step-01-plan-notes.md`.
