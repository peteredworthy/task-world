# Step Plan: DB Migration (M1 Remaining)

## Purpose

Create and apply the Alembic migration that adds all new columns from Step 1 to the live database schema. This step is deliberately isolated so the migration is reviewable on its own, and any DB-level issues (default constraints, nullable rules, FK references) are caught before logic is built on top.

## Prerequisites

- **Step 1 complete** — all ORM model column definitions finalized in `db/models.py`.

## Functional Contract

### Inputs

- Existing database with `tasks`, `steps`, `runs` tables.
- ORM model definitions from Step 1.

### Outputs

- Alembic migration file in `alembic/versions/` that adds:
  - `tasks`: `expanded_from_task_id` (VARCHAR, FK → `tasks.id`, nullable), `expansion_justification` (VARCHAR, nullable), `is_expansion` (BOOLEAN, NOT NULL, default False)
  - `steps`: `is_expansion` (BOOLEAN, NOT NULL, default False), `expanded_from_task_id` (VARCHAR, FK → `tasks.id`, nullable)
  - `runs`: `expansion_count` (INTEGER, NOT NULL, default 0)
- Migration applies cleanly to an existing DB with data (additive only, no column drops or type changes)
- Migration is reversible (downgrade removes the columns)

### Error Cases

- If Alembic autogenerate produces extra diffs due to unrelated model changes, manually trim the migration to include only expansion columns.
- FK self-reference on `tasks.expanded_from_task_id → tasks.id` must use `use_alter=True` or equivalent to avoid circular FK creation issues in SQLite.

## Tasks

1. **Run `alembic revision --autogenerate -m "add_expansion_columns"`** to generate the migration skeleton.

2. **Review and trim** the generated migration to include only the six new columns (three on `tasks`, two on `steps`, one on `runs`).

3. **Verify FK handling**: confirm `expanded_from_task_id` FK references `tasks.id` correctly. For SQLite compatibility, check that the FK syntax is acceptable or use `batch_alter_table`.

4. **Write downgrade path**: drop the six columns in reverse order.

5. **Apply migration**: `alembic upgrade head` against a test DB, verify `alembic current` shows the new revision.

6. **Update `scripts/seed_db.py`** if needed so seed data creation is compatible with the new nullable/default columns.

7. **Confirm existing tests pass** after migration is applied: `uv run pytest tests/unit/ tests/integration/ -v`.

## Verification Approach

### Auto-Verify

- `alembic upgrade head` completes without error on a fresh DB
- `alembic upgrade head` completes without error on a DB seeded with existing data
- `alembic downgrade -1` reverses cleanly
- `uv run pytest tests/unit/ tests/integration/ -v` — no regressions

### Manual Verification

- Inspect the migration file to confirm no unexpected table drops or column modifications
- Confirm all new columns have appropriate defaults (existing rows get `is_expansion=False`, `expansion_count=0`, NULLs for optional text columns)

## Context & References

- Plan: `docs/orchestrated-expansion/plan.md` — Step 2 specification
- Architecture: `docs/orchestrated-expansion/architecture.md` — DB model section
- Step 1: column definitions in `src/orchestrator/db/models.py`
- Existing migration pattern: check `alembic/versions/` for conventions used in prior migrations
