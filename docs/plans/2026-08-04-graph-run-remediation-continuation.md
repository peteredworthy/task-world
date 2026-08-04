# Graph Run Remediation: Continuation Handoff

Resume the approved Graph Run Remediation in this repository. Read `AGENTS.md`,
the complete `mind-the-gap` skill, and
`docs/plans/2026-08-04-graph-run-remediation-ledger.md` before editing. The
ledger is the durable requirements record; update it only after independent
validation. Do not modify `orchestrator.db` or `worktrees/r359`; use `uv run`
for Python tooling and `apply_patch` for edits.

## Checkpoint state

- This checkpoint is on branch `codex/graph-remediation-handoff`.
- Alembic has one head: `zi1j2k3l4m5n`.
- R1 and R3-R7 remain independently validated.
- R2 is **partial**; R8 has not started.
- The previous compact snapshot parity failure is fixed. Live append now
  reduces the same retained projection-event shape that the bounded rebuild
  reads, including writer-assigned accepted-record `graph_position` and
  `run_id` fields. This preserves topology bound-record positions.
- Final-blocker failed-outbox pagination no longer skips the page-boundary row:
  the continuation represents the last consumed `outbox_id`, while the next
  query remains strictly keyset `>`.

Recent validated commands:

```bash
uv run pytest tests/integration/test_graph_api.py \
  tests/integration/test_graph_read_contract_matrix.py \
  tests/integration/test_migrations.py -q -n 0 --run-slow
# 66 passed

uv run pytest \
  tests/integration/test_graph_api.py::test_graph_final_blocker_outbox_cursor_keeps_the_boundary_row \
  tests/integration/test_graph_api.py::test_archival_graph_views_page_over_cap_through_http \
  tests/integration/test_graph_read_contract_matrix.py::test_compact_rows_are_bounded_before_persistence_and_rebuild_identically \
  -q -n 0 --run-slow
# 3 passed

uv run ruff check src/orchestrator/api/routers/graph.py \
  src/orchestrator/graph_runtime/store.py tests/integration/test_graph_api.py
# clean
```

## Current functional gaps (R2)

An independent read-only validation found these remaining issues. Do not mark
R2 complete until all are implemented and independently proved.

### 1. Archival maintenance is not bounded incremental

`GraphEventStore.persist_projection_snapshot()` calls
`_sync_archival_projection_views()` for every append. That method projects and
upserts the entire topology, final-blocker set, and region set on each append.
This is O(full view) write work and full collection materialization per event,
not bounded maintenance.

Required result: use event-targeted incremental rows, or an explicit durable,
resumable batch-maintenance protocol. A public route must either read a current
complete durable owner or return the existing truthful retryable unavailable
response; it must never repair by replaying history during GET.

### 2. Node-detail standalone rebuild materializes all history

`GraphEventStore.rebuild_node_detail_summaries()` calls
`read_run_node_detail(run_id)` without a limit, then holds the entire run in a
list before producing compact rows. The first attempted naive batch loop was
reverted because once a bounded node collection is trimmed, simply reusing its
persisted 50-item prefix loses exact `total_known`, byte, and SHA metadata.

Required result: a resumable/keyset design that preserves live/rebuild parity
for all compact node-detail fields without retaining an unbounded event list.
If an additional durable normalized owner or streaming metadata is required,
make the migration real and prove upgrade/downgrade behavior.

### 3. Archival responses are count-capped but not byte-capped

`read_current_archival_view_page()` materializes raw persisted row payloads and
the topology, final-blocker, and region routes construct response models
directly. A page with 100 oversized entries can exceed the 262,144-byte public
contract. Nested fields are also unconstrained:

- topology `record_ids` and `bound_records`;
- final-blocker `support_ids`;
- region `blockers`.

Required result: enforce a typed byte budget before response serialization,
with truthful partial/truncation/continuation metadata or a smaller page. Do
not silently drop content without metadata. Ensure the database reader does
not decode over-cap raw JSON before the guard.

### 4. Missing product-real archival parity proof

The current 101-entry HTTP test proves keyset traversal for short live rows.
It does **not** delete and rebuild archival rows before comparing every page,
and it does not cover oversized individual/nested payloads. Add real ASGI HTTP
proofs for topology, final blockers, and regions over cap, including totals,
cursor stability, byte caps, partial metadata, and live/rebuild equivalence.

## Completion loop

Use mind-the-gap cycles. Start by adding tests that expose the remaining gaps,
then implement the broadest coherent durable design. Fresh independent
validation for R2 must inspect every graph API route, artifact resolution/GC,
runtime/dispatch/controller/service/recovery, and explicit maintenance APIs
for raw unbounded decode, offset pagination, request-time replay, or unbounded
collection materialization.

Only after R2 is independently validated should R8 begin: full backend and UI
suites, Ruff/format/Pyright, graph-boundary and signal-routing checks, Alembic
head/upgrade proof, removed-Superpowers search, and a final change review.
