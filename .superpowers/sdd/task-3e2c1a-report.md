# Task 3e2c1a Report

## Status

Staged for the controller migration gate. This split task provides source
reanchoring and immutable CST composition ownership only.

## Implementation

- `compile_query_composition_plan(sources, stream, disposition_plan)` reuses
  the approved occurrence/diagnostic reanchoring evidence, parsing each
  participating source snapshot once.
- Frozen composition groups retain source path/span, deterministic owner and
  anchor, original outer expression, consumed IDs, and nested-anchor IDs.
- The plan rejects duplicate IDs and duplicate action spans, has canonical
  ordering, and proves exact reviewed-ID closure.
- A bounded live stream probe produced the current machine evidence: 190
  groups consuming all 201 reviewed query-transform IDs.

## Deferred

Task 3e2c1a contains no query-recipe models, field-to-query registry, query
imports, argument/default semantics, or replacement-expression compiler.
Those concerns remain explicitly deferred to the follow-on recipe task.
`task-3e2c1-report.md` remains historical blocked evidence for the rejected
combined scope.

## Checks

- Focused composition/reanchoring test and collector suite.
- Ruff and Pyright.
- The controller must run `make test-graph-projection-migration` once before
  any commit.

## Controller Migration Gate

`make test-graph-projection-migration` — 10 passed, 3738 deselected in
124.17s.
