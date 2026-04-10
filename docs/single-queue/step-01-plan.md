# Step 01: Schema and State Machine

**Phase:** 1
**Goal:** Lay the data foundation without changing any runtime behavior.

---

## Purpose and Functionality

Restructure the `pending_signals` table for FIFO ordering and delivery tracking,
add the `STOPPING` state to `RunStatus`, and define the `RUN_START` signal type.
No runtime behavior changes — only schema and type definitions.

---

## Prerequisites / Dependencies

- None. This is the first step — no prior steps required.
- Alembic migration infrastructure must be functional.
- Existing test suite must be green before starting.

---

## Functional Contract

### Inputs

| Input | Source | Description |
|-------|--------|-------------|
| Existing `pending_signals` table | DB | UUID PK, `created_at` used for ordering |
| Existing `RunStatus` enum | `db/models.py` | Does not include STOPPING |
| Existing `WorkflowSignal` enum | `signals/signals.py` | Does not include RUN_START |

### Outputs

| Output | Description |
|--------|-------------|
| Migrated `pending_signals` table | `INTEGER PRIMARY KEY AUTOINCREMENT`, `delivered_at TIMESTAMP NULL`, `handled_at TIMESTAMP NULL`; `created_at` retained for audit only |
| `RunStatus.STOPPING` | New enum value with transition guards: STOPPING → PAUSED or STOPPING → FAILED only |
| `WorkflowSignal.RUN_START` | New signal type (no handler wiring yet) |
| API guards for STOPPING | `start_task()`, `submit_for_verification()`, resume, restart, duplicate pause/cancel all reject STOPPING runs (409) |

### Errors

| Error | Condition | Behavior |
|-------|-----------|----------|
| Migration failure | Existing `pending_signals` rows can't be backfilled | Migration must handle existing rows: assign sequential integer PKs based on `created_at` order |
| Invalid STOPPING transition | API attempts resume/restart on STOPPING run | Return 409 Conflict |

---

## Verification Strategy

1. **Migration tests:**
   - Fresh DB: migration creates correct schema.
   - Existing signals: migration backfills integer PKs from existing UUID rows.
   - Rollback: downgrade migration restores previous schema.

2. **STOPPING state machine tests** (`tests/unit/test_stopping_state.py`):
   - All valid transitions from STOPPING (→ PAUSED, → FAILED) succeed.
   - All invalid transitions (→ ACTIVE, → DRAFT, etc.) are rejected.
   - API returns 409 for disallowed operations on STOPPING runs.

3. **RUN_START signal tests:**
   - Signal can be created and serialized.
   - Existing signal tests still pass.

4. **Regression:** Full existing test suite passes with no behavioral changes.

---

## Files Changed

- New: `alembic/versions/xxxx_single_queue_signals.py`
- Modify: `src/orchestrator/db/models.py` (PendingSignal model, RunStatus enum)
- Modify: `src/orchestrator/workflow/signals/signals.py` (drain queries, RUN_START)
- Modify: `src/orchestrator/workflow/engine.py` (STOPPING transition guards)
- Modify: `src/orchestrator/api/routers/runs.py` (API guards for STOPPING)
- New: `tests/unit/test_stopping_state.py`

---

## Traces

[I-07], [I-08], [I-16], [I-26]
