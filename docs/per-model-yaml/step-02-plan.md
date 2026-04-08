# Step Plan: DB Migration and Persistence (M2)

## Purpose

Persist the new `token_usage_by_model` fields to the database via Alembic migration and ORM changes. After this step, per-model token data can be stored and retrieved from the database.

## Prerequisites

- Step 01 complete: `ModelTokenUsage` class exists in `state/models.py`, `token_usage_by_model` fields on `Attempt` and `Run`.

## Functional Contract

### Inputs

- `Attempt` and `Run` domain models with `token_usage_by_model: list[ModelTokenUsage]` (from Step 01)
- Existing `AttemptModel` and `RunModel` ORM classes in `db/orm/models.py`
- Existing repository methods in `db/access/repositories.py`

### Outputs

- `AttemptModel.token_usage_by_model`: JSON column, server default `'[]'`
- `RunModel.token_usage_by_model`: JSON column, server default `'[]'`
- Alembic migration file that adds both columns
- Repository serialization: when writing an attempt/run, serialize `list[ModelTokenUsage]` to JSON list of dicts; when reading, deserialize back to `list[ModelTokenUsage]`
- Existing rows get empty arrays (no backfill needed)

### Error Cases

- Migration on existing DB with data: safe -- new columns default to `'[]'`, no data loss
- Rollback: migration downgrade drops both columns (data in those columns lost, but legacy flat fields preserved)
- Corrupt JSON in column: deserialization should handle gracefully (return empty list)

## Tasks

1. Add `token_usage_by_model = Column(JSON, default=list)` to `AttemptModel` and `RunModel` in `src/orchestrator/db/orm/models.py`.
2. Create Alembic migration adding both columns with `server_default='[]'`.
3. Update `db/access/repositories.py` to serialize `token_usage_by_model` (list of ModelTokenUsage → list of dicts) when writing attempts/runs, and deserialize (list of dicts → list of ModelTokenUsage) when reading.
4. Write integration test: create a run with `token_usage_by_model` populated, persist, read back, verify round-trip correctness.

## Verification Approach

### Auto-Verify

- Alembic migration applies cleanly: `alembic upgrade head` succeeds
- Alembic migration rolls back cleanly: `alembic downgrade -1` succeeds
- All existing tests pass (existing runs get empty arrays)
- New integration test: round-trip serialization of `token_usage_by_model` data

### Manual Verification

- Inspect DB schema after migration: `sqlite3 orchestrator.db ".schema attempts"` shows new column
- Create a run, verify `token_usage_by_model` column contains `[]` by default

## Context & References

- Architecture: `docs/per-model-yaml/architecture.md` -- DB schema changes section
- Memory: DB schema migrations use Alembic for file-backed DBs, `create_all` for in-memory test DBs. `create_all` does NOT add new columns to existing tables.
- Memory: NEVER run `rm orchestrator.db`
- Requirement IDs: I-08, I-12, I-21, I-25
