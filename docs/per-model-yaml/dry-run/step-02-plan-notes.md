# Step 02 Dry-Run Notes: DB Migration and Persistence

*Generated: 2026-04-08*

---

## Executive Summary

**Tasks T-01, T-02, and T-03 are already fully implemented** in this worktree. The code matches the step requirements with two minor deviations (noted below). Only **T-04 (integration test)** remains to be built.

---

## Task-by-Task Analysis

---

### T-01: Add token_usage_by_model JSON columns to ORM models

**Status: ALREADY IMPLEMENTED**

Both columns exist in `src/orchestrator/db/orm/models.py`:
- `AttemptModel` (lines 219–221): `mapped_column(JSON, nullable=True, default=None)`
- `RunModel` (lines 87–89): `mapped_column(JSON, nullable=True, default=None)`

#### Deviation from step spec
The step specifies `Column(JSON, default=list)` but the implementation uses `mapped_column(JSON, nullable=True, default=None)`. This is a **benign deviation**:
- `default=None` vs `default=list`: in-memory objects get `None` instead of `[]` as default. The repository layer normalizes `None → []` on read, so this does not affect callers.
- `mapped_column(...)` is the SQLAlchemy 2.x style; functionally equivalent to `Column(...)`.
- `nullable=True` is explicit; the step implied nullable by not specifying otherwise.

#### Auto-verify quality
- `attempt_model_column` and `run_model_column`: **existence-only greps** — they verify the text `Column(JSON` exists but the actual ORM uses `mapped_column(JSON`. These greps would **FAIL** on the existing code even though the implementation is correct. The builder must use a more flexible regex or check for `mapped_column`.
- Recommended fix: Change grep to `grep -q 'token_usage_by_model'` with a count of 2 hits, OR grep for `JSON.*nullable=True` near `token_usage_by_model`.

---

### T-02: Create Alembic migration

**Status: ALREADY IMPLEMENTED**

File: `src/orchestrator/db/migrations/versions/p1a2b3c4d5e6_add_token_usage_by_model.py`

- Revises: `o1a2b3c4d5e6` (add_paused_at_to_attempts) — correct chain
- Adds `token_usage_by_model` JSON column to both `attempts` and `runs`
- Uses `batch_alter_table` (correct pattern for SQLite compatibility)
- Downgrade drops both columns in reverse order

#### Deviation from step spec
The step says to use `server_default='[]'` but the migration uses `nullable=True` with **no server_default** (existing rows get NULL, not `[]`). This means:
- Old rows will have `None` in the column, not `[]`
- The `_to_domain()` repo code already handles `None` gracefully (returns `[]`)
- **No functional impact** — the repo treats NULL and `[]` identically on read

This is acceptable but worth flagging: if anything directly queries the DB column (e.g., a raw SQL query counting non-null rows), it would behave differently than `server_default='[]'` would produce.

#### Auto-verify quality
- `migration_file_exists`: **existence-only** — passes if file exists, even if content is wrong. Acceptable as a smoke check paired with `alembic_upgrade`.
- `migration_has_attempts` and `migration_has_runs`: uses `xargs grep` chaining — fragile if `grep -l` returns multiple files. Acceptable for this simple case.
- `alembic_upgrade`: **contract-level** — actually runs the migration. This is the most valuable check. Mark as `must: true`.

#### Failure mode: revision chain
If the current head in the running DB is already `p1a2b3c4d5e6`, running `alembic upgrade head` is a no-op (correct). If a different migration was applied, the chain may not connect. **The migration file correctly identifies `o1a2b3c4d5e6` as the down_revision**, so the chain is valid as long as that migration exists.

---

### T-03: Update repository serialization and deserialization

**Status: ALREADY IMPLEMENTED AND COMPLETE**

`src/orchestrator/db/access/repositories.py` has full round-trip support:

**Deserialization (RunModel → Run)** — `_to_domain()`:
- Iterates `run_model.token_usage_by_model` (None-safe)
- Uses `ModelTokenUsage.model_validate(item)` per item with `try/except` for corrupt entries
- Returns empty list for None or missing data

**Serialization (Run → RunModel)** — `_to_model()`:
- Calls `[u.model_dump(mode="json") for u in run.token_usage_by_model]`
- Stores `None` (not `[]`) when list is empty — matches nullable column behavior

**Attempt serialization** — `update_latest_attempt()`:
- Accumulates per-model tokens at both attempt-level and run-level
- Merges by model name (additive across builder + verifier phases)
- Correct real-time update behavior matching the M2 plan intent

#### Auto-verify quality
- `repo_has_serialization`: **existence-only** — grep for string presence. Passes even if commented out.
- `repo_uses_model_dump`: partial contract check — verifies `model_dump` or `ModelTokenUsage` appear near `token_usage_by_model`. Reasonable but could be fooled by comment blocks.
- Recommended addition: `uv run pytest tests/unit/test_model_token_usage.py -x -q` as a `must: true` item — these unit tests actually exercise the serialization path.

---

### T-04: Write integration test for round-trip serialization

**Status: NOT IMPLEMENTED**

`tests/integration/test_token_usage_persistence.py` does **not exist**.

The unit test file `tests/unit/test_model_token_usage.py` exists and covers `ModelTokenUsage.total_cost_usd` and `PhaseHandler._extract_metrics_and_usage`, but it does **not** test database persistence (no ORM or repository layer involvement).

#### What the integration test must cover

Per the step requirements:

**R11 — Round-trip with populated data:**
- Create a run via the API
- Directly manipulate `token_usage_by_model` on the domain object (or trigger via `update_latest_attempt`)
- Read back via `GET /api/runs/{id}` or the task endpoint
- Assert each field: `model`, `cache_read_tokens`, `cache_creation_tokens`, `input_tokens`, `output_tokens`, `cost_per_m_*`, `total_cost_usd`

**R12 — Empty list default:**
- Create a run without any token data
- Read back; assert `token_usage_by_model == []` (not `None`, not missing)

**R13 — Corrupt JSON handling:**
- Directly insert a row with invalid JSON in `token_usage_by_model` (requires raw DB access in test)
- Read back via domain layer; assert returns `[]` without exception

#### Failure modes for T-04

1. **Fixture reuse**: The step references `client_and_drain`/`client` from `test_api_full_lifecycle.py`. This fixture is defined locally in that file, not in `conftest.py`. The integration test must either copy or import the pattern. **Recommended**: Copy the app/client fixture pattern rather than importing from another test file.

2. **API path for token_usage_by_model**: The step says "read back via API" but the current `GET /api/runs/{id}` response includes `token_usage_by_model` on the run (via `RunResponse`). The attempt-level field is accessible via `GET /api/runs/{id}/tasks/{task_id}` (AttemptSchema). The test should check both.

3. **Corrupt JSON test**: Inserting corrupt JSON requires bypassing the ORM (which would reject invalid Python objects). The test needs to either:
   - Use `AsyncSession` to execute raw SQL (`UPDATE runs SET token_usage_by_model = 'not-json'`), OR
   - Patch the repository's read path to return a corrupt dict
   - **Most robust**: use `AsyncSession.execute(text(...))` directly in the test.

4. **Auto-verify quality for T-04**:
   - `test_file_exists`: existence-only — passes even if file is empty.
   - `test_has_round_trip`: grep for string — passes even if the test is wrong.
   - `integration_tests_pass` (`must: false`): this is the only real contract check, and it's marked non-mandatory. **Change to `must: true`** — a test file that doesn't pass is worse than no test.

5. **Missing verifier rubric detail**: The `corrupt_json_handling` scenario is not in the verifier rubric. The builder may skip it. Add it as a rubric item at grade B (since it's not in R11/R12 but is in the task_context).

---

## Wiring Analysis

T-01, T-02, T-03 are persistence-layer changes. They do not introduce new call sites — they extend existing ones. **No wiring risk** for these tasks.

T-04 is an integration test. It does not wire anything into the runtime path. **No wiring risk.**

The component wiring concern (new class not used in active path) does not apply here: the serialization code is already in the active call path (`_to_domain`, `_to_model`, `update_latest_attempt`), and that code is exercised when tasks complete.

---

## Hardening Actions

| Task | Issue | Hardening Action |
|------|-------|-----------------|
| T-01 | `auto_verify` greps check for `Column(JSON` but ORM uses `mapped_column(JSON` | Change grep to `grep -c 'token_usage_by_model' src/orchestrator/db/orm/models.py \| grep -qE '^2$'` (checks count of 2) |
| T-02 | `alembic_upgrade` marked `must: false` | Mark as `must: true` — this is the primary contract check for T-02 |
| T-02 | `server_default` deviation (NULL vs `[]`) | Document in notes; acceptable since repo normalizes on read; no code change needed |
| T-03 | No must-pass test in auto_verify | Add `uv run pytest tests/unit/test_model_token_usage.py -x -q` as `must: true` |
| T-04 | `integration_tests_pass` is `must: false` | Change to `must: true` |
| T-04 | Corrupt JSON test requires raw SQL | Add explicit note in task_context about using `AsyncSession.execute(text(...))` |
| T-04 | Verifier rubric missing corrupt JSON scenario | Add `corrupt_json_handling` rubric item |
| T-04 | Test fixture not in conftest | Note that builder must copy fixture pattern, not import from sibling test file |
| T-04 | API path for attempt-level token data unclear | Clarify: check `RunResponse.token_usage_by_model` for run-level; `AttemptSchema.token_usage_by_model` accessible via task endpoint |

---

## Risk Summary

| Risk | Severity | Status |
|------|----------|--------|
| T-01/T-02/T-03 already done — builder may try to re-implement | Medium | Mitigate: builder must check file state before editing; idempotent edits acceptable |
| T-04 corrupt JSON test needs raw SQL access | Low | Mitigate: explicit instruction in task_context |
| Auto-verify checks for T-01 would fail on existing correct code | High | Fix greps as noted above |
| `alembic_upgrade` marked non-mandatory | Medium | Change to must: true |
| Missing corrupt JSON in verifier rubric | Low | Add rubric item |

---

## Pre-conditions Satisfied

- ✅ Step 01 complete: `ModelTokenUsage` in `state/models.py`, `token_usage_by_model` on `Attempt` and `Run` domain models
- ✅ Alembic migration infrastructure exists at `src/orchestrator/db/migrations/`
- ✅ Import `from orchestrator.state.models import ModelTokenUsage` works
- ✅ `o1a2b3c4d5e6` (down_revision) exists in migration chain
