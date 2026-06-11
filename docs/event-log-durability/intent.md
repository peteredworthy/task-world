# Intent: Event-log Durability

## Original Request

Implement Slice 0.1 "Event-log durability" from the execution-graph kernel sequencing plan. Make the DB-backed event log the single authoritative event store through a new `events_v2` table, while demoting `.orchestrator/state/history.jsonl` to a best-effort secondary sink. The work must preserve existing event write/read call sites, protect live data with mandatory backups before migration, support projection rebuilds from `events_v2`, and prove durability through kill-and-rebuild and crash-mid-append drills.

## Goal

The orchestrator records every accepted workflow event in `events_v2` transactionally before any projection update, making the database event log the authoritative source of truth. [I-01]

Existing run, task, and related projection state can be rebuilt from `events_v2` alone without relying on `.orchestrator/state/history.jsonl`. [I-02]

The legacy JSONL journal remains available as a secondary best-effort sink and import source, but journal write failures never fail an accepted event append. [I-03]

The migration path protects existing production-like data with verifiable backups before cutover and can be rerun safely without duplicating events. [I-04]

The implementation provides real durability evidence through end-to-end workflow activity, projection drop/rebuild comparison, and crash-mid-append checks. [I-05]

## Resolved Design Questions

No further human clarification is required before the next implementation slice. The previously missing graph references have been restored in this worktree:

- `docs/graph-approach/execution-graph-prd-plus.md`
- `docs/graph-approach/execution-graph-evaluation.md`

Those references confirm the same authority model used here: accepted events are authoritative, projections are disposable, and the JSONL journal is only a secondary compatibility/recovery surface. The first implementation slice remains incremental oversight rather than a full graph-kernel rewrite.

## Scope

### In Scope

- Harden the existing `events_v2` database schema and Alembic migration surface with durable ordering, append-only semantics, stable idempotency identity for import/retry, and uniqueness constraints that prevent duplicate aggregate sequence numbers. [I-06]
- Route accepted event writes through `events_v2` in the same database transaction that precedes projection updates. [I-07]
- Keep existing event write/read call sites working through the new store so the slice changes storage authority without forcing a public API rewrite. [I-08]
- Demote `.orchestrator/state/history.jsonl` to a best-effort secondary sink after DB append succeeds or is safely accepted by the transaction boundary. [I-09]
- Add an idempotent migration/import tool for the existing journal that copies both the journal file and SQLite database aside before migration. [I-10]
- Add rebuild support that can drop disposable projection tables and reconstruct equivalent run/task state from `events_v2`. [I-11]
- Add real tests using temporary SQLite databases and real journal files, with no mocks, no monkeypatching, and no direct edits to the live database or live journal. [I-12]
- Run the slice in routine mode with human review gates before risky migration or cutover behavior is accepted. [I-13]

### Out of Scope

- Frontend changes are out of scope for this slice. [I-14]
- Removing the legacy JSONL journal entirely is out of scope; it is demoted, not deleted. [I-15]
- Deleting, resetting, or directly modifying the live `orchestrator.db` is out of scope. [I-16]
- Rewriting the whole workflow engine or public REST API is out of scope unless the first proof slice shows the existing event abstraction cannot support the durability contract. [I-17]
- Introducing external event-streaming infrastructure such as Kafka, NATS, or a separate database is out of scope. [I-18]

## Constraints

- The live `.orchestrator/state/history.jsonl` journal is precious data and must be backed up before any import or cutover operation touches it. [I-19]
- The live SQLite database is precious data and must be backed up before any migration tool performs cutover or destructive rebuild behavior. [I-20]
- Migration must be idempotent and re-runnable, using stable event identity and sequence constraints to avoid duplicate imports. [I-21]
- Projection tables are disposable read models; event data in `events_v2` is not disposable. [I-22]
- Event append must be append-only at the application contract level; corrections happen through new events rather than mutation or deletion of prior events. [I-23]
- Tests must use real in-memory or temporary-file SQLite databases and real temporary journal files. [I-24]
- Tests must not use `patch`, `MagicMock`, monkeypatching, generated fake proof surfaces, or `must: false` commands as final acceptance evidence. [I-25]
- Reference documents expected by the task are present and authoritative for this slice: `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`, `docs/graph-approach/execution-graph-prd-plus.md`, and `docs/graph-approach/execution-graph-evaluation.md`. [I-26]

## Definition of Complete

- [ ] `events_v2` exists through SQLAlchemy metadata and Alembic migration with durable position ordering, per-aggregate sequence ordering, payload metadata, timestamps, and uniqueness/idempotency constraints needed for append/import retry safety. [I-27]
- [ ] Every accepted event is persisted to `events_v2` transactionally before the corresponding projection update is committed. [I-28]
- [ ] JSONL journal writes are best-effort secondary writes, and a journal write failure cannot fail or roll back a successful database event append. [I-29]
- [ ] A migration/import command backs up the journal and SQLite database, verifies those backups exist, imports existing journal events into `events_v2`, and can be rerun without duplication. [I-30]
- [ ] A rebuild command or service path can drop relevant projection tables in a test database and rebuild equivalent run/task state from `events_v2` alone. [I-31]
- [ ] An end-to-end kill-and-rebuild test runs real workflow activity, captures pre-drop state, drops projections, rebuilds from `events_v2`, and asserts identical run/task state. [I-32]
- [ ] A crash-mid-append drill proves no accepted event is lost and no event is duplicated across restart/retry boundaries. [I-33]
- [ ] Existing event write/read call sites continue to work through the new durable store. [I-34]
- [ ] The implementation documentation identifies cutover procedure, rollback posture, evidence artifacts, and human review gates. [I-35]
- [ ] Relevant unit, integration, and e2e tests pass under `uv run pytest` without mocks or monkeypatching. [I-36]
