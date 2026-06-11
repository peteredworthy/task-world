# Slice 0.2 — Cost & Log Records (loop mode)

Phase 0 foundation slice from the kernel-sequencing plan. This is the measurement
instrument for the whole mode experiment — it must exist before anything we want to
compare.

## Scope

1. **Cost record model**: a per-execution cost record capturing tokens in/out, cache
   read/write tokens, model name, and wall time, keyed by **execution identity**
   (run id + task id + attempt number + agent runner type). DB-backed via SQLAlchemy
   model + Alembic migration.
2. **Interaction logs as artifact records**: agent interaction logs (prompt/output
   text already flowing through the executor callbacks) stored as artifact records
   with **stable ids**, linked to the same execution identity.
3. **Carryover**: existing task-world metrics (token usage currently stored on
   attempts) are written into the new cost-record shape as well — the new table is
   populated for every agent execution without breaking existing metrics.
4. **Report script**: `scripts/cost_report.py` aggregates per-run and per-mode spend
   (group by run id and by agent runner type / mode tag), printing a table and
   emitting JSON with `--json`.

## Done when (acceptance)

- Every agent execution in a test run emits a cost record (integration test proves
  it: run a real workflow with the in-repo mock/local agent path used by existing
  integration tests — NOT unittest mocks — and assert cost records exist for each
  execution with correct identity keys).
- The report script aggregates per-run and per-mode spend; a test runs it against a
  populated temp DB and checks the aggregation arithmetic.
- Existing metrics keep working (no regressions in current token-usage tests).

## Ground truth

- `docs/graph-approach/execution-graph-prd-plus.md` — event log / records sections
- `docs/graph-approach/execution-graph-evaluation.md`
- Existing metrics plumbing: search for token usage handling in
  `src/orchestrator/workflow/` executor and `src/orchestrator/db/`.

## Standards (non-negotiable)

- NO mocks, NO monkeypatching in tests. Real sqlite DBs (in-memory or tmp file),
  real files in tmp dirs. Follow existing test conventions in `tests/`.
- Alembic migration for the new table(s) (`init_db()` uses Alembic for file-backed
  DBs, `create_all` for in-memory test DBs — both paths must work).
- Small, regular commits on this branch (`loop/0.2-cost-records`), each leaving
  tests green. Run `uv run pytest tests/unit tests/integration` before each commit
  (pre-commit hook also runs checks).
- Do NOT touch `.orchestrator/state/history.jsonl`, `orchestrator.db`, or anything
  outside this worktree. Do not run git commands against the main checkout.
- Do not merge to main — the slice ends with a frontier audit pass on this branch.
