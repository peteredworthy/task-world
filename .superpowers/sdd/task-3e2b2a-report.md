# Task 3e2b2a Collector and Anchor Corrective Report

## Current architecture

The inventory collector is the sole provenance authority. Frozen context carries
exact imported callee/type origin, selected receiver or argument expression,
role, slot, star evidence, and physical field/access facts. The codemod only
reanchors and requires exact equality; it never propagates provenance.

Physical evidence is now independently re-derived from the exact CST action:
direct and nested subscripts, assignment targets, membership comparisons,
map/field methods, and `Del` anchors. The collector unwraps deletion targets to
the physical receiver. The compiler derives the root physical field, exact
normalized receiver expression, access kind, and canonical operation shape,
then compares every stored fact. It does not search arbitrary nested CST for a
matching field.

## Verification

- Ambiguous star evidence is XOR: direct expansion retains `argument_star`; a
  later unstarred argument retains `preceding_star`; both and neither are
  rejected. Anchoring requires the exact stored form.
- Physical context now retains an operation shape, permits fieldless
  `keys`/`values`/`items`, and independently verifies field, kind, and shape
  before accepting the receiver/call context.
- Compiler coverage includes direct/call/deletion positives, fieldless methods,
  field/kind/operation/expression refusal, and a nested unrelated diagnostic
  field refusal. Collector coverage asserts normalized physical receivers
  through assignment, call, and deletion action wrappers.
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_live_reviewed_ledger_compiles_once_and_defers_only_fixture_sites -q`
  — passed (`1 passed in 127.42s`).
- Focused physical regression selection — `7 passed in 4.13s`, followed by
  nested diagnostic coverage — `6 passed in 4.37s`.
- `uv run ruff check .` and `uv run ruff format --check .` — passed.
- `uv run pyright` — passed (`0 errors, 0 warnings, 0 informations`).
- `uv run python scripts/graph_projection_inventory.py --diagnose | diff -q -
  docs/graph-projection-inventory-diagnostics.md` — passed; no artifact update
  was required.
- `uv run pytest` — passed (`5018 passed, 3 skipped, 3 warnings in 512.35s`).
  The warnings are existing Python 3.12 `aiosqlite` datetime-adapter
  deprecations.

Full corrective-wave counts are recorded in `task-3e2b2-report.md`.
