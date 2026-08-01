# Closure Task 4 implementation report

## Status

Implemented the permanent GraphProjection boundary-provenance extractor as an
AST-only module independent of the one-time migration inventory.

## Changes

- Added `scripts/graph_projection_boundary_provenance.py` with the focused
  immutable provenance fact model, finite public origin tables, source-order
  fact collector, lexical scopes, shadowing, assignment/await propagation,
  typed producer/field support, and possible branch-alias joins.
- Switched package and direct-script imports in
  `scripts/check_graph_projection_boundaries.py` to the new module.
- Added explicit tests that prevent the permanent guard from importing the
  migration inventory and prevent migration bookkeeping vocabulary from
  entering the new module.

## TDD evidence

- RED: `uv run pytest tests/unit/test_graph_projection_boundaries.py::test_permanent_boundary_guard_does_not_import_migration_inventory -q`
  failed as expected because the guard imported `graph_projection_inventory`.
- GREEN: the focused boundary suite and standalone guard pass after the
  extraction.

## Verification

- `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` — 86 passed.
- `uv run python scripts/check_graph_projection_boundaries.py` — exited 0 with
  no output.
- `uv run ruff check scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py` — passed.
- `uv run ruff format --check scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py` — passed.

## Review and concerns

Implementation self-review found no scope expansion, migration dependency, or
weakened permanent boundary check. The controller owns independent review and
progress-ledger completion; this implementation commit intentionally does not
modify `.superpowers/sdd/progress.md`.
