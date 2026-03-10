# DB Recovery Remaining Work (Backup + Event Log Replay)

## Goal

Fully recover a destroyed database by:
1. Restoring a DB backup.
2. Replaying external event log entries after the backup point.

This requires the DB to persist enough replay metadata to determine exactly where replay should start.

## Current State (as of 2026-03-09)

- External JSONL event journaling exists (`event_journal.py`).
- Journal replay command exists (`orchestrator runs replay-journal`).
- Replay currently applies events to existing runs but does not yet provide full, deterministic, end-to-end DB reconstitution guarantees.
- There is no durable replay checkpoint model in DB that records the last journal position successfully applied.

## Must-Have Outcomes

- Recovery is deterministic and idempotent.
- Replay can resume safely after interruption.
- DB stores a durable replay checkpoint so startup/tools can compute replay start point without manual guesswork.
- Recovery process is scripted/documented and testable.

## Remaining Work

## 1) Replay Checkpoint Model (Highest Priority)

- [ ] Add DB table (or equivalent persisted model) for replay checkpoints.
- [ ] Store at least:
  - [ ] `journal_path` (or stream identifier)
  - [ ] `last_applied_offset` (byte offset) OR `last_applied_event_id` (monotonic id)
  - [ ] `last_applied_timestamp` (UTC)
  - [ ] `updated_at`
  - [ ] optional: `backup_snapshot_id` / `backup_created_at`
- [ ] Define uniqueness constraints so one active checkpoint exists per `(journal_path, recovery_scope)`.
- [ ] Add migration + repository methods.
- [ ] Decide scope granularity:
  - [ ] global checkpoint, or
  - [ ] per-run checkpoint.

Acceptance:
- `replay-journal` can run with no `--since` and derive start point from DB checkpoint.

## 2) Journal Record Identity + Ordering Guarantees

- [ ] Extend journal entry schema with a stable monotonic replay key (preferred over timestamp-only).
- [ ] Ensure key generation is deterministic and strictly ordered for append order.
- [ ] Preserve backward compatibility for existing journal files without the new key.

Acceptance:
- Replay never depends solely on wall-clock timestamps for ordering/cutover.

## 3) Idempotent Replay Semantics

- [ ] Define idempotency rules per event type (safe reapply behavior).
- [ ] Prevent duplicate side effects if an event is replayed twice.
- [ ] Add dedupe strategy:
  - [ ] processed-event ledger, or
  - [ ] event version checks, or
  - [ ] deterministic upsert rules per state transition.

Acceptance:
- Running replay twice from same checkpoint produces no additional state changes.

## 4) Crash-Safe Replay Transaction Strategy

- [ ] Apply replay in chunks/batches.
- [ ] Commit state + checkpoint atomically per batch.
- [ ] On crash mid-replay, restart from last committed checkpoint.

Acceptance:
- Simulated crash during replay resumes cleanly with no corruption or missed events.

## 5) Coverage Expansion Beyond Run Status

- [ ] Audit all persisted entities that must be reconstructed from backup+log.
- [ ] Add replay handlers for missing event/state types (if any).
- [ ] Confirm whether clarifications, approvals, metrics, and artifacts are fully recoverable from events + backup baseline.
- [ ] If not, add new emitted events for missing state mutations.

Acceptance:
- Explicit matrix exists: each DB state field is either:
  - recoverable from replay, or
  - intentionally backup-only.

## 6) Backup Metadata Integration

- [ ] Standardize backup metadata file/table with:
  - [ ] backup timestamp
  - [ ] journal replay start marker (offset/id at backup time)
- [ ] Update backup procedure to capture this marker transactionally with backup creation.

Acceptance:
- “Restore + replay” process can always derive exact replay start without manual input.

## 7) Tooling and UX

- [ ] Extend CLI with:
  - [ ] `orchestrator runs replay-journal --from-checkpoint`
  - [ ] `orchestrator runs replay-journal --show-checkpoint`
  - [ ] `orchestrator runs replay-journal --advance-checkpoint/--dry-run`
- [ ] Add preflight validation:
  - [ ] journal exists/readable
  - [ ] checkpoint consistency
  - [ ] backup timestamp sanity.

Acceptance:
- One documented command sequence performs recovery end-to-end.

## 8) E2E Recovery Test Suite

- [ ] Add deterministic E2E test:
  - [ ] create active run state
  - [ ] take backup
  - [ ] append more events
  - [ ] restore backup
  - [ ] replay from checkpoint
  - [ ] assert final DB equals pre-destruction state.
- [ ] Add interruption test (kill replay midway, rerun).
- [ ] Add duplicate replay test.

Acceptance:
- E2E recovery tests pass reliably in CI.

## 9) Operational Runbook

- [ ] Document production procedure:
  - [ ] how to create backup + marker
  - [ ] how to restore
  - [ ] how to replay
  - [ ] how to verify correctness post-recovery
  - [ ] rollback plan on replay failure.

Acceptance:
- Runbook is sufficient for on-call execution without tribal knowledge.

## Open Design Decisions

- [ ] Checkpoint key: byte offset vs event id vs both.
- [ ] Checkpoint scope: global vs per-run.
- [ ] Whether to support multi-journal rotation and archival replay.
- [ ] Retention/compaction strategy for long-lived journal files.

## Suggested Implementation Order

1. Replay checkpoint model + migration.
2. Monotonic journal replay key.
3. Idempotent replay + batch atomic checkpoint updates.
4. Backup marker capture integration.
5. E2E recovery tests.
6. CLI/runbook finalization.
