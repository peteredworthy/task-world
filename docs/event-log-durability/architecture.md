# Architecture: Event-log Durability

Planning mode: incremental oversight

## Current State

The orchestrator is a Python FastAPI application using SQLAlchemy and Alembic. File-backed database initialization runs Alembic migrations, while in-memory test databases use metadata creation. Workflow events now have an existing `events_v2` implementation surface, with `.orchestrator/state/history.jsonl` retained as a secondary outbox/import surface. The requested slice hardens that direction into a tested durability contract: the database event log is authoritative, and projection tables are rebuildable read models.

The graph-approach reference documents named by the task are present in this worktree and support the same state-layer model: event log as authority, projections as disposable caches, agent/session state as non-authoritative runtime context.

## Proposed Changes

For the first executable slice, harden the existing `events_v2` event store beside the existing journal path and prove one real workflow path can use it as the authoritative event source. The system should append the event row inside the database transaction before projection state is committed, then attempt the JSONL journal write as a best-effort secondary action that cannot invalidate the accepted database append.

### Components

- **`events_v2` table**: Durable append-only event log with global position, aggregate/run ID, per-aggregate version, event type, payload, and timestamp. The hardening work must add or confirm the stable import/retry identity and metadata needed by the durability contract.
- **Event store repository**: Existing async SQLAlchemy-facing component that appends events, reads ordered event streams, and enforces aggregate ordering through database constraints.
- **Journal secondary sink**: Existing JSONL outbox retained as best-effort output after DB authority is established.
- **Migration/import command**: Existing restore/bootstrap path plus required hardening that copies the journal and SQLite database aside, verifies backups, imports JSONL events into `events_v2`, and safely skips already imported events.
- **Projection rebuild service**: Existing registry/projector path that clears or overwrites disposable projection state and rebuilds equivalent run/task state from ordered `events_v2` events.
- **Durability drills**: Integration/e2e tests for projection drop/rebuild and interrupted append/retry.

### Data Models

The first `events_v2` hardening target should include:

- `position`: global durable ordering cursor.
- `aggregate_id`: run/workflow aggregate identifier used for per-run ordering.
- `version`: monotonic sequence within the aggregate.
- `event_type`: constrained event name used by projection dispatch.
- `payload`: JSON event body.
- `timestamp`: event timestamp from the accepted event.
- durable metadata for source, importer, schema version, correlation details, and stable import/retry identity where the existing table does not yet provide it.
- Unique constraints on the stable import/retry identity and on `(aggregate_id, version)`.

The append contract is application-level append-only: prior rows are not edited to correct history, and replay behavior is changed by appending compensating or replacement events.

### External Dependencies

No new external services or libraries are planned for the first slice. The implementation should use existing SQLAlchemy, Alembic, Pydantic, pytest, and temporary filesystem support.

## Tech Choices

| Aspect | Choice | Rationale |
|--------|--------|-----------|
| Backend | Existing FastAPI and workflow services | Public API shape should keep working while storage authority changes. |
| Frontend | No changes | Frontend is out of scope for this slice. |
| Storage | Existing SQLite-backed `events_v2` through SQLAlchemy and Alembic | Fits the current stack and makes DB event authority transactional. |
| Integration | Existing event write/read abstractions | Preserves call sites and limits blast radius during the proof slice. |
| Secondary sink | Existing JSONL journal, best effort only | Maintains compatibility without making the file a source of truth. |
| Migration | Idempotent importer with backup verification | Protects precious live data and supports reruns. |

## Testing Strategy

### Unit Tests

- Validate pure event ordering and idempotency helpers without filesystem or network access.
- Validate event serialization/deserialization against Pydantic models and constrained event type values.
- Validate append contract helpers with in-memory SQLite only when no Alembic behavior is under test.

### Integration Tests

- Run Alembic migration against a temp-file SQLite database and assert `events_v2` schema, indexes, and constraints exist.
- Append duplicate event IDs and duplicate `(aggregate_id, sequence_number)` pairs to prove database constraints reject duplication.
- Import a real temporary JSONL journal twice and assert the second run is a no-op with the same event count.
- Force a journal secondary-sink write failure using real filesystem permissions or invalid temp paths, not mocks, and assert DB append remains durable.
- Verify backup-before-import by checking copied journal and database files exist and match source size or checksum before import proceeds.

### E2E Tests

- Run real workflow activity through the smallest available API/CLI/service surface that creates run/task events.
- Capture canonical run/task projection state before rebuild.
- Drop or clear projection tables in the temp database.
- Rebuild projections from `events_v2` only.
- Assert rebuilt state is identical to captured state.
- Exercise crash-mid-append behavior by interrupting or simulating retry around real transaction boundaries without monkeypatching; verify accepted events are neither lost nor duplicated.

## Performance & Scalability

The first slice should favor correctness and observability over optimization. Required indexes are `id`, `(aggregate_id, sequence_number)`, and any timestamp/type ordering needed for replay. Batching, snapshots, compaction, and export performance are deferred until the proof slice shows real replay costs.

## Security Considerations

Migration tooling must sanitize file paths and refuse traversal outside intended project or backup directories. Backup files should not expose secrets beyond what is already present in the local database and journal, and they should be written with local filesystem permissions appropriate for developer data. The importer must never delete the source journal or database.

## Cutover And Review

Human review is required before any migration command is used against non-test data. The review should inspect backup verification, event counts, sequence ranges, duplicate handling, and the rebuild drill output. If any evidence is missing, cutover stops and the team replans from the failed proof.

## References

- `docs/intent/30-EVENT-DRIVEN-MIGRATION.md`
- `routines/_archived/idea-to-plan/scaffolding/architecture.md`
- `docs/graph-approach/execution-graph-prd-plus.md`
- `docs/graph-approach/execution-graph-evaluation.md`
