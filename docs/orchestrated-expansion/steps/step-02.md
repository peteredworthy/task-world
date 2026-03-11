# Step 2: DB Migration (M1 Remaining)

Create and apply the Alembic migration that adds all new expansion columns from Step 1 to the live database schema. Deliberately isolated so the migration is reviewable on its own and DB-level issues (defaults, nullable rules, FK references) are caught before logic is built on top.

## Intent Verification
**Original Intent**: Produce a reversible Alembic migration that adds the six new expansion columns to existing `tasks`, `steps`, and `runs` tables without breaking existing data (see `docs/orchestrated-expansion/plan.md` Step 2).
**Functionality to Produce**:
- Alembic migration in `alembic/versions/` that adds:
  - `tasks`: `expanded_from_task_id` (VARCHAR, FK → `tasks.id`, nullable), `expansion_justification` (VARCHAR, nullable), `is_expansion` (BOOLEAN, NOT NULL default False)
  - `steps`: `is_expansion` (BOOLEAN, NOT NULL default False), `expanded_from_task_id` (VARCHAR, FK → `tasks.id`, nullable)
  - `runs`: `expansion_count` (INTEGER, NOT NULL default 0)
- Migration applies cleanly to an existing seeded DB
- Downgrade removes all six columns

**Final Verification Criteria**:
- `alembic upgrade head` completes without error on a fresh DB
- `alembic upgrade head` completes without error on a seeded DB
- `alembic downgrade -1` reverses cleanly
- `uv run pytest tests/unit/ tests/integration/ -v` — no regressions

---

## Task 1: Generate Alembic Migration Skeleton

**Description**: Run `alembic revision --autogenerate` to produce a migration skeleton, then trim it to include only the six new expansion columns.

**Implementation Plan (Do These Steps)**
- [ ] Run: `uv run alembic revision --autogenerate -m "add_expansion_columns"`
- [ ] Open the generated file in `alembic/versions/`
- [ ] Remove any diff entries unrelated to the six expansion columns (autogenerate may include unrelated changes)
- [ ] Confirm the upgrade path adds exactly: `expanded_from_task_id`, `expansion_justification`, `is_expansion` on `tasks`; `is_expansion`, `expanded_from_task_id` on `steps`; `expansion_count` on `runs`

**Dependencies**
- [ ] Step 1 complete — ORM model column definitions finalized in `db/models.py`

**References**
- `docs/orchestrated-expansion/step-02-plan.md` — Task 1
- `docs/orchestrated-expansion/architecture.md` — DB model section
- Existing migrations in `alembic/versions/` for convention reference

**Constraints**
- Do not include unrelated table changes in this migration
- Only additive changes (no column drops or type changes)

**Functionality (Expected Outcomes)**
- [ ] Migration file exists in `alembic/versions/`
- [ ] Migration includes exactly the six new columns, nothing else

**Final Verification (Proof of Completion)**
- [ ] Migration file can be opened and its contents inspected for the six columns

---

## Task 2: Fix FK Handling and Write Downgrade Path

**Description**: Verify FK self-reference on `tasks.expanded_from_task_id` is SQLite-compatible, and implement the downgrade (column drop) path.

**Implementation Plan (Do These Steps)**
- [ ] In the migration, check that `expanded_from_task_id` FK references `tasks.id` — use `batch_alter_table` for SQLite compatibility if needed
- [ ] Check the `steps.expanded_from_task_id` FK references `tasks.id` correctly
- [ ] Write the `downgrade()` function: drop all six columns in reverse order
- [ ] For SQLite: use `op.batch_alter_table` pattern to add columns with FKs safely

**Dependencies**
- [ ] Task 1 complete (migration skeleton exists)

**References**
- `docs/orchestrated-expansion/step-02-plan.md` — Task 3, Task 4
- Existing migration: check `alembic/versions/` for `batch_alter_table` usage pattern

**Constraints**
- Self-referencing FK on `tasks` may need `use_alter=True` or `batch_alter_table` depending on DB
- Downgrade must drop columns in the reverse order they were added

**Functionality (Expected Outcomes)**
- [ ] Migration upgrades without FK constraint errors
- [ ] Downgrade removes all six columns cleanly

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` completes on a fresh DB
- [ ] `uv run alembic downgrade -1` completes without error

---

## Task 3: Apply and Validate Migration

**Description**: Apply the migration against a test DB (fresh and seeded), verify the schema, and confirm existing tests still pass.

**Implementation Plan (Do These Steps)**
- [ ] Apply to fresh DB: `uv run alembic upgrade head`; check `uv run alembic current` shows new revision
- [ ] Apply to seeded DB: run `uv run python scripts/seed_db.py`, then `uv run alembic upgrade head`
- [ ] Inspect the DB to confirm new columns exist with correct defaults
- [ ] Run `uv run alembic downgrade -1` and confirm columns removed
- [ ] Run `uv run alembic upgrade head` again (round-trip clean)
- [ ] Update `scripts/seed_db.py` if needed (new columns should not require seed changes given nullable/default design)

**Dependencies**
- [ ] Task 2 complete (migration fully written with downgrade)

**References**
- `docs/orchestrated-expansion/step-02-plan.md` — Tasks 5–6, Verification Approach

**Constraints**
- Existing rows must remain valid after upgrade (no NOT NULL columns without defaults on existing data)
- Do not manually modify existing data in the migration

**Functionality (Expected Outcomes)**
- [ ] All existing rows get `is_expansion=False`, `expansion_count=0`, NULLs for optional text columns
- [ ] Migration round-trip (up → down → up) completes cleanly

**Final Verification (Proof of Completion)**
- [ ] `uv run alembic upgrade head` succeeds on seeded DB
- [ ] `uv run alembic downgrade -1` succeeds
- [ ] `uv run pytest tests/unit/ tests/integration/ -v` — no regressions
