# Task 3e2c1a Report

## Status

Staged for the controller migration gate. This split task provides source
reanchoring and immutable CST composition ownership only.

## Implementation

- `_reanchor_operation_stream_sites` is the sole occurrence/diagnostic proof
  boundary used by both stream compilation and composition. It independently
  verifies snapshot digest, occurrence cardinality/ordinal, diagnostic
  signature/scope, and complete stored anchor evidence.
- Frozen composition groups retain a stable synthetic outer-action ID, optional
  site owner (only when the anchor is itself the outer action), outer anchor,
  original expression, canonical consumed IDs, and actual ancestry pairs.
  Siblings therefore have a synthetic owner and no invented nested relation.
- Composition follows full LibCST parent chains through bridge nodes to an
  explicit statement/action boundary, then builds interval-overlap connected
  components. Incomparable/residual overlap and unsupported boundaries refuse
  closed. Models reject malformed spans, paths, expressions, ownership,
  relation, exactness, and interval-overlap violations.
- A live repository contract produced the corrected machine evidence: 187
  groups consuming all 201 reviewed query-transform IDs.

## Deferred

Task 3e2c1a contains no query-recipe models, field-to-query registry, query
imports, argument/default semantics, or replacement-expression compiler.
Those concerns remain explicitly deferred to the follow-on recipe task.
`task-3e2c1-report.md` remains historical blocked evidence for the rejected
combined scope.

## Checks

- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py -q` — 50 passed.
- `uv run ruff check scripts/codemods/migrate_graph_projection_queries.py tests/unit/test_migrate_graph_projection_queries.py` — passed.
- `uv run pyright scripts/codemods/migrate_graph_projection_queries.py` — 0 errors.
- `uv run pytest --run-slow -m graph_projection_migration -n 0 --timeout=300 tests/unit/test_graph_projection_migration.py::test_live_query_composition_plan_closes_reviewed_query_transform_sites -q` — 1 passed in 145.18s.

## Controller Migration Gate

Passed with 187 groups consuming all 201 reviewed transform IDs.
