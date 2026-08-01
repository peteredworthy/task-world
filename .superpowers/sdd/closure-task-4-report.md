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

- Historical initial extraction evidence: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` — 86 passed.
- `uv run python scripts/check_graph_projection_boundaries.py` — exited 0 with
  no output.
- `uv run ruff check scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py` — passed.
- `uv run ruff format --check scripts/graph_projection_boundary_provenance.py scripts/check_graph_projection_boundaries.py tests/unit/test_graph_projection_boundaries.py` — passed.

## Review and concerns

Implementation self-review found no scope expansion, migration dependency, or
weakened permanent boundary check. The controller owns independent review and
progress-ledger completion; this implementation commit intentionally does not
modify `.superpowers/sdd/progress.md`.

## Review-fix evidence

- Added RED regressions for exact public origins, dotted imports, class-method
  traversal, binder isolation, branch kills/possible aliases, and colliding
  expression facts. The initial focused run failed all four new regressions.
- The AST collector now retains facts by source location **and expression**;
  the boundary visitor matches the actual consumed AST expression rather than
  accepting any fact sharing its start offset.
- Imports and annotations now admit only the finite public graph origin tables;
  non-approved graph submodule imports remain independently rejected by the
  permanent import boundary check.
- Class methods are traversed with their own scope and class field facts;
  function variadics, lambdas, loop targets, and match captures clear inherited
  aliases before their bodies are classified.
- Branch merging now includes aliases killed in every branch, so pre-branch
  aliases cannot leak through a complete overwrite.
- GREEN: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` —
  90 passed; `uv run python scripts/check_graph_projection_boundaries.py` —
  exited 0 without output.

## Follow-up review-fix evidence

- Added RED coverage for executable class-body accesses and mutations, then
  restored the forbidden-submodule regression to require both the permanent
  import violation and all storage-access/mutation diagnostics.
- Class bodies now visit assignments and expressions in a class-local scope;
  methods retain isolated function scope with the owning class fields available
  through `self`.
- Current authoritative verification: `uv run pytest
  tests/unit/test_graph_projection_boundaries.py -q` — 91 passed; `uv run
  python scripts/check_graph_projection_boundaries.py` — exited 0 with no
  output.

## Control-flow and pattern-semantics closure

### Root cause and constrained implementation

- `Match` previously merged only case-body scopes, which dropped the incoming
  no-match path for non-exhaustive statements. It only cleared `MatchAs`
  captures and never visited guards, so `MatchStar` and mapping-rest captures
  could expose an outer projection alias in guards or bodies.
- `Try` previously discarded the successful try-body state, ran `else` and
  `finally` from the pre-try scope, and merged them as unrelated branches.
- The collector now recursively collects `MatchAs`, `MatchStar`, and
  `MatchMapping.rest` names from every nested pattern (including sequence,
  class, mapping, and OR patterns), clears them before guard/body traversal,
  and includes the incoming match scope unless an unguarded top-level wildcard
  or capture is unconditional.
- Direct capture coverage verifies that an unshadowed literal-case guard is
  reported while MatchAs, star, mapping-rest, nested sequence, class, mapping,
  and OR captures shadow outer aliases in their guards and bodies.
- Try flow now preserves the successful state, applies `else` only to that
  state, seeds handlers from a conservative join of incoming and partial try
  state, and applies `finally` to every normal outgoing path before merging.
- No origin resolution, named-expression/augmented-assignment/delete behavior,
  variadic annotations, typed-field assignment behavior, class handling, or
  diagnostics changed. `.superpowers/sdd/progress.md` remains untouched.

### TDD evidence

- RED (match family): `uv run pytest
  tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_match_includes_no_match_and_exhaustive_paths
  tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_match_captures_shadow_guards_and_bodies
  -q` — 2 failed: the no-match projection fact was absent and star/rest
  captures retained the outer alias.
- GREEN (match family): the same command — 2 passed.
- RED (try family): `uv run pytest
  tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_try_keeps_successful_projection_with_handlers
  tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_try_applies_else_then_finally_to_each_path
  tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_try_finally_propagates_every_outgoing_path
  -q` — 3 failed: successful state was dropped, `else` leaked into `finally`,
  and `finally` dropped outgoing possible provenance.
- GREEN (try family): the same command — 3 passed.

### Authoritative verification

- `uv run ruff check scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — passed.
- `uv run ruff format --check scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — passed.
- `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` — 96
  passed.
- `uv run python scripts/check_graph_projection_boundaries.py` — exited 0
  with no output.

### Concerns

- Handler inputs deliberately use a conservative incoming/partial-state join:
  where Python exception timing cannot be resolved statically, provenance may
  be reported as `possible` rather than omitted. This favors the permanent
  boundary guard's false-negative avoidance requirement.
