# Step Plan: Schema and State Machine

## Purpose

Lay the data foundation for the single-queue signal model without changing any
runtime behavior. This includes restructuring the `pending_signals` table (integer
PK, delivery tracking columns), adding the `STOPPING` run state with transition
guards, and defining the `RUN_START` signal type.

## Prerequisites

- None — this is the first step with no dependencies.
- Migration assumes clean server stop with no pending signals (decided in clarifications).

## Functional Contract

### Inputs

- Existing `pending_signals` table with UUID string PK, `processed_at` column,
  `created_at`-based ordering.
- Existing `RunStatus` enum without `STOPPING`.
- Existing `WorkflowSignal` enum without `RUN_START`.

### Outputs

- **Alembic migration** in `src/orchestrator/db/migrations/versions/` that:
  - Replaces UUID PK with `INTEGER PRIMARY KEY AUTOINCREMENT`.
  - Renames `processed_at` to `handled_at`.
  - Adds `delivered_at TIMESTAMP NULL`.
  - Uses `batch_alter_table()` for SQLite compatibility.
- **`PendingSignal` model** updated to reflect new schema.
- **Drain/query code** in `signals.py` updated to `ORDER BY id` (integer PK)
  instead of `created_at`.
- **`RunStatus.STOPPING`** added with state machine guards:
  - Valid transitions: `ACTIVE → STOPPING`, `STOPPING → PAUSED`, `STOPPING → FAILED`.
  - `start_task()` and `submit_for_verification()` reject STOPPING runs.
  - API returns 409 for resume/restart/duplicate pause/cancel on STOPPING runs.
- **`WorkflowSignal.RUN_START`** type defined (no handler wiring yet).

### Error Cases

- Migration fails on existing DB — mitigated by `batch_alter_table()` and assumption
  of no pending signals at migration time.
- Hard-coded SQLite constraint names in migration — avoided by using batch operations.
- STOPPING guard misses a code path — mitigated by comprehensive unit tests.

## Tasks

1. Create Alembic migration for `pending_signals` restructuring (integer PK,
   `delivered_at`, rename `processed_at` → `handled_at`).
2. Update `PendingSignal` model in `models.py`.
3. Update drain/query code in `signals.py` to ORDER BY integer PK.
4. Add `STOPPING = "stopping"` to `RunStatus` enum.
5. Add state machine guards in `engine.py` for STOPPING transitions.
6. Add API guards in `routers/runs.py` (409 for disallowed STOPPING transitions).
7. Add `RUN_START` to `WorkflowSignal` enum.
8. Write unit tests for STOPPING transitions (`tests/unit/test_stopping_state.py`).

## Verification Approach

### Auto-Verify

- Migration applies cleanly on a fresh DB and an existing DB (with no pending signals).
- All existing signal tests pass with new schema.
- `grep -r "ORDER BY.*created_at" src/orchestrator/workflow/signals/` returns no hits.
- Unit tests confirm all valid STOPPING transitions succeed and invalid ones raise.
- API returns 409 for resume/restart/pause/cancel on STOPPING runs.
- `RUN_START` signal can be created and serialized.

### Manual Verification

- Alembic `upgrade head` and `downgrade -1` both work cleanly.
- Existing integration tests pass without modification.

## Context & References

- Plan: `docs/single-queue-2/plan.md` — Phase 1 (§1.1, §1.2, §1.3)
- Architecture: `docs/single-queue-2/architecture.md` — Database Changes section
- Key files: `src/orchestrator/db/models.py`, `src/orchestrator/workflow/signals/signals.py`,
  `src/orchestrator/workflow/engine.py`, `src/orchestrator/api/routers/runs.py`
- Migration directory: `src/orchestrator/db/migrations/versions/`
- Caveat: Use `batch_alter_table()`, NOT hard-coded constraint names.
