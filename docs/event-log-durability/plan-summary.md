# Event-Log Durability Plan Summary

## Intent Satisfaction Summary

The executable plan satisfies the intent by reducing the broad event-log durability goal to one verifiable first slice: prove that accepted workflow events can be treated as authoritative in `events_v2`, while run/task projections remain rebuildable and `.orchestrator/state/history.jsonl` remains a secondary compatibility surface.

The slice is intentionally incremental. It does not claim full production cutover, full write-path migration, or removal of the legacy journal. Instead, it requires real evidence that one workflow/service/API path writes accepted events to `events_v2` before committed projection state, can rebuild run/task projections from ordered database events alone, and can survive append retry boundaries without losing or duplicating accepted events.

The restored reference documents are treated as authoritative for this slice:

- `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`
- `docs/graph-approach/execution-graph-prd-plus.md`
- `docs/graph-approach/execution-graph-evaluation.md`
- `docs/event-log-durability/step-01-plan.md`

No unresolved reference conflict is recorded in the planning, dry-run, or verification reports. Any later conflict between implementation evidence and those references is a replan trigger.

## Thin Routine Header

```yaml
id: event-log-durability
title: Event-log Durability
planning_mode: incremental_oversight
steps:
  - file: steps/step-01-plan.yaml
```

## Ordered Step List

| Order | Step file | Step title | Task count | Requirement count |
| --- | --- | --- | ---: | ---: |
| 1 | `routines/event-log-durability/steps/step-01-plan.yaml` | Verification-Path Proof For DB-Authoritative Events | 9 | 16 |

### Step 1 Task Order

1. T-01 - Confirm references and define proof boundaries
2. T-02 - Add canonical projection-state comparison helper
3. T-03 - Confirm `events_v2` schema and migration contract
4. T-04 - Verify event-store append and ordered reads
5. T-05 - Add duplicate-prevention durability tests
6. T-06 - Prove DB append authority and secondary journal behavior
7. T-07 - Add projection rebuild durability drill
8. T-08 - Add crash/retry durability drill
9. T-09 - Record evidence and run targeted verification

## Key Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Planning mode | Incremental oversight | The durability work crosses storage, projection rebuild, transaction boundaries, migration safety, and verification. The first slice must prove the real path before wider migration. |
| First executable target | One workflow path plus rebuild and crash/retry drills | This tests the architecture without rewriting the whole workflow engine or REST API. |
| Event authority | `events_v2` | Accepted workflow events must be durable database records and ordered for replay. |
| Projection posture | Disposable read models | Run/task projection state must be comparable before clearing and after rebuild from database events. |
| JSONL journal posture | Best-effort secondary sink/import source | Journal failures must not invalidate accepted database appends, and rebuild proof must not depend on JSONL. |
| Retry identity | Explicit stable identity decision | The slice must either add a stable identity or explicitly prove the `(aggregate_id, version)` retry identity behavior and limitation. |
| Verification style | Real SQLite, real journal files, no mocks or monkeypatching | Durability claims require real transaction, filesystem, and projector behavior. |
| Migration safety | Backup evidence if import/cutover is touched | Live journal and database data are precious; backup-before-touch remains mandatory. |

## Risks And Mitigations

| Risk | Mitigation |
| --- | --- |
| A schema-only change could pass without proving real workflow authority. | T-06 requires standard service/API dependency-path evidence and observable `events_v2` rows. |
| Projection comparison could omit important fields and hide rebuild mismatch. | T-02 requires canonical run, step, task, and attempt fields, deterministic JSON normalization, and justified volatile-field exclusions. |
| Duplicate prevention could only assert an exception, not durable state. | T-05 requires row-count and ordered-stream assertions after duplicate attempts. |
| Rebuild could accidentally replay an in-memory event list or JSONL instead of the database log. | T-07 requires clearing projection state and reading ordered rows from `events_v2` after the clear. |
| Stale projection checkpoints could make recovery evidence misleading. | T-07 requires clearing `projection_checkpoints` or recording a deliberate checkpoint deferral. |
| Journal write failure could be confused with projection transaction failure. | T-06 requires separate evidence for projection rollback boundaries and post-commit secondary-sink failure. |
| Crash/retry testing could miss one side of the transaction boundary. | T-08 requires both pre-commit interruption and post-commit retry coverage. |
| Cutover or migration behavior could be over-claimed. | Step scope guards and T-09 require explicit backup/import evidence if touched, or an explicit deferred-cutover note if not touched. |

## Caveats For Execution

- This plan is ready to execute as slice 1, not as the full event-log durability cutover.
- Frontend changes, external streaming systems, full workflow-engine rewrites, and JSONL removal are out of scope.
- Do not delete, reset, or directly modify live `orchestrator.db` or live `.orchestrator/state/history.jsonl`.
- If migration/import behavior is touched, the execution evidence must include verified backup paths for both the SQLite database and journal.
- If any real verification surface cannot run, or if a fallback passes while the real path fails, stop and replan instead of broadening the slice.
- Final acceptance must include the targeted `uv run pytest` commands and evidence artifacts named in T-09.

