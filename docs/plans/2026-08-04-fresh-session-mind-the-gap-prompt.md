# Fresh-session completion prompt

Continue the Graph Run Remediation in `/Users/peter/code/task-world` using the
`mind-the-gap` skill from the first action. Read `AGENTS.md` and the complete
skill instructions before editing. Treat
`docs/plans/2026-08-04-graph-run-remediation-ledger.md` as the durable
requirements ledger; refresh it only from independent validation evidence.

## Scope and constraints

Complete the approved remediation, not merely a test subset. Do not touch
`orchestrator.db` or `worktrees/r359`, do not run git operations in the main
checkout, and use `uv run` for Python tooling. Use `apply_patch` for edits.
Never create a no-op Alembic migration: a new revision is allowed only for a
real schema or durable-data transformation. Do not restore or use Superpowers;
the active integration has been removed. Keep public module imports at module
top-level boundaries, avoid mocks/global state, and retain Pydantic boundary
validation.

Use mind-the-gap cycles: refresh the ledger, establish a concrete test
baseline, make the broadest coherent pass, and use a fresh independent
validator with product-real API/runtime proof before marking a requirement
validated. Keep the visible plan synchronized at each validated requirement.

## Independently validated requirements

- R1: `/graph/health` candidate identities are byte-bounded/hashed.
- R3: graph driver pause/resume has owned task generations and quiescence.
- R4: graph completion requires durable finalization and retry-safe receipt.
- R5: merge disposition is explicit (`merged`, `ready`, `no_changes`,
  `dirty`, `unfinalized`, `blocked`) in API/UI and merge is gated.
- R6: JSONL archive collision-safe rotation/recovery.
- R7: active Superpowers integration removed.

R8 (final independent gap audit and full gates) is not started.

## Actual current state (verified 2026-08-04)

R2 remains the only functional requirement not closed: every graph read and
payload must be bounded or paginated, with truthful unavailable/partial
behavior instead of request-time full replay.

Already implemented and previously independently validated within R2:

- Pydantic collection contracts; numeric event windows/continuation metadata.
- Missing/stale compact owners return retryable 503 rather than rebuilding in
  `/graph`, summary events, scheduler, decisions, and node detail.
- Artifact authorization uses durable `(run_id, content_hash)` references;
  range reads use a durable file identity checkpoint. Migration is genuine.
- Full event, full node-detail, file-state, patches, runtime-tail, and
  evidence-digest paths have UTF-8 SQL byte guards before raw JSON decoding.
  Over-cap evidence is returned as partial.
- Normal graph runtime paths use bounded checkpoint/tail reads; stale patch and
  resume unavailability are translated to truthful retryable/paused outcomes.
- All-run recovery now requires explicit bounded maintenance pagination.

The workspace also contains newer, not-yet-independently-validated R2
structural work:

- `zi1j2k3l4m5n_add_graph_archival_view_read_models.py` is the **single**
  Alembic head (`uv run alembic -c alembic.ini heads`). It adds independent
  archival checkpoint/topology/final-blocker/region read-model tables.
- Public topology, final-blockers, and regions routes use those archival rows
  with cursors. Final-blockers has an opaque `outbox:<id>` keyset continuation
  segment.
- `GraphEventStore.rebuild_read_models()` was changed to fixed-size keyset
  batches; inspect it carefully for correctness and resumability.

Do not assume that structural work is correct. The latest actual focused gate
was:

```bash
uv run pytest tests/integration/test_graph_api.py \
  tests/integration/test_graph_read_contract_matrix.py \
  tests/integration/test_migrations.py -q -n 0 --run-slow
```

It had **64 passed, 1 failed**:
`test_compact_rows_are_bounded_before_persistence_and_rebuild_identically`.
The live and rebuilt graph snapshot bytes differ after archival-view changes.
Diagnose and fix the underlying durable/rebuild parity issue; do not weaken the
test unless the public contract genuinely changed and an independent validator
agrees.

Known R2 risks/gaps to audit before closure:

1. `_sync_archival_projection_views()` upserts/trims deterministic rows but
   currently walks complete projection views per append. Establish whether this
   violates the required bounded incremental maintenance; make it truly
   incremental or explicitly maintain bounded batches.
2. `rebuild_node_detail_summaries()` still calls `read_run_node_detail(run_id)`
   without a batch limit and materializes its result. Convert maintenance
   rebuilding to resumable/keyset batches, preserving exact parity.
3. Prove archival-view consistency, keyset cursor correctness, byte budgets,
   and totals for 101+ topology/region/blocker entries through real HTTP.
4. Re-run a fresh whole-R2 gap audit. Check every public graph endpoint,
   artifact GC/resolution, runtime/dispatch/controller/service/recovery, and
   explicit maintenance APIs for raw unbounded payload decode, full-history
   replay, offset pagination, or unbounded collection materialization.
5. Only after R2 is independently approved, perform R8: final gap finder,
   full backend/UI suites, Ruff, format, Pyright, graph-boundary check,
   signal-routing check, Alembic single-head/upgrade proof, active-Superpowers
   search, and final change review.

## Useful evidence and commands

The ledger contains exact prior proofs. Recent passing focused checks included
the graph API/read-contract/migration suite before the current one parity
failure, full Pyright, and `uv run alembic -c alembic.ini heads` showing one
head `zi1j2k3l4m5n`. Do not treat these as final gates—rerun after fixes.

Start with the ledger, reproduce the 64/65 failure, write a bounded rebuild
parity/product test before broadening scope, then validate with a fresh
read-only role. Do not claim R2/R8 complete without that independent evidence.
