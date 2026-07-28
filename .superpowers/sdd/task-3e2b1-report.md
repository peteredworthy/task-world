# Task 3e2b1 Report

## Status

Completed the reviewed-ledger planning boundary without any source transformation.

## TDD

- RED: plan metadata tests failed because the prior operation model exposed
  incomplete template/replacement fields rather than the reviewed ledger
  contract.
- GREEN: frozen plan operations now retain disposition, reason, and explicit
  consumed IDs; live planning deterministically reports the reviewed
  disposition and structural group counts.
- RED: duplicate anchored operation identities were silently collapsed by the
  join map.
- GREEN: planning rejects duplicate operation-stream IDs before reconciliation.

## Machine-derived live counts

- reviewed dispositions: 354
- query transforms: 201
- approved core: 80
- projection neutral: 73
- deferred test fixtures: 349

## Verification

```text
$ uv run pytest tests/unit/test_migrate_graph_projection_queries.py -q
13 passed in 96.50s

$ uv run ruff check scripts/codemods/migrate_graph_projection_queries.py tests/unit/test_migrate_graph_projection_queries.py
All checks passed!

$ uv run ruff format --check scripts/codemods/migrate_graph_projection_queries.py tests/unit/test_migrate_graph_projection_queries.py
2 files already formatted

$ uv run pyright
0 errors, 0 warnings, 0 informations

$ uv run pytest
4997 passed, 3 skipped, 3 warnings in 238.76s (0:03:58)
```

The warnings are the existing Python 3.12 `aiosqlite` default datetime-adapter
deprecations in `tests/unit/test_projectors.py`. The first full run exposed that
the live compiler test can exceed its local 120-second limit under xdist load;
raising only that test's explicit timeout to 300 seconds allowed the unchanged
test body to complete in the passing foreground full-suite run.

## Scope review

No LibCST templates, source rewrites, import changes, consumer changes, or
ledger/inventory identity changes were introduced. The prior incomplete
template/replacement stubs were replaced by plan-only reviewed-ledger data.

## Files changed

- `scripts/codemods/migrate_graph_projection_queries.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `.superpowers/sdd/task-3e2b1-report.md`

## Concerns

The plan's shape-group counts describe only the reviewed set, deliberately;
the unclassified fixture set is deferred untouched for later work.

## Self-review

- Every `PlannedOperation` and `DispositionPlan` model is frozen and rejects
  extra fields.
- The planner rejects duplicate stream identities before map construction,
  stale reviewed IDs, overlapping consumed IDs, non-fixture deferred records,
  reviewed/deferred overlap, and any deferred count other than 349.
- Ordering is deterministic by canonical ledger ID; counts are derived from
  the reconciled operation stream rather than source/path/function policy.
- No query-template, LibCST rewrite, import, consumer, inventory, or ledger
  identity behavior is present in this subtask.
