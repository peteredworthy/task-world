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

## Final origin-resolution and binding-state fix

### Root cause and constrained implementation

- Call and annotation provenance accepted a textual `ast.unparse()` spelling of
  approved public paths. That let unimported dotted text seed provenance, while
  the exact unaliased `import orchestrator.graph_runtime.controller` form was
  not bound as an approved module root.
- Scope field state also represented both a declaration and a current projected
  value, so assigning foreign data to a typed field could leave stale
  provenance. Named expressions did not update state, and augmented assignment
  or deletion did not invalidate rebound aliases.
- Provenance now comes only from finite, resolved import origins. Exact public
  imports cover the graph module, its aliases, the controller module and its
  aliases, and exact from-imports; root/module rebinding clears the associated
  origin. No unimported or foreign dotted annotation/call is a seed.
- `*args` and `**kwargs` use the same exact annotation resolution as ordinary
  parameters. Named expressions evaluate their value then bind their target.
  Augmented assignment and deletion clear name and typed-field provenance; a
  subscript mutation intentionally retains the base projection provenance so
  the permanent guard continues reporting every immutable-operation diagnostic.
- Typed-field declarations are tracked separately from their current projection
  value. Projection assignments retain/re-establish field provenance and
  non-projection assignments or deletion clear it.

### TDD and verification evidence

- RED: `uv run pytest tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_resolves_only_exact_imported_dotted_origins tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_seeds_exactly_typed_variadics tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_applies_walrus_augassign_and_delete_bindings tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_clears_and_restores_typed_field_provenance -q` — 4 failed, respectively exposing textual/unbound dotted resolution, unseeded typed variadics, missing walrus/kill state, and stale typed fields.
- GREEN: the same focused command — 4 passed after the constrained collector changes.
- Broader boundary verification first exposed that clearing a base name after a
  subscript mutation hid later immutable-operation diagnostics. The collector
  now keeps the base provenance for subscript targets because that mutation does
  not rebind the base value.
- Final focused suite: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` — 100 passed.
- Final standalone guard: `uv run python scripts/check_graph_projection_boundaries.py` — exited 0 with no output.
- Static checks: `uv run ruff check scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py`, `uv run ruff format --check scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py`, and `uv run pyright scripts/graph_projection_boundary_provenance.py tests/unit/test_graph_projection_boundaries.py` — passed (Pyright: 0 errors).

### Concerns

- The collector remains deliberately conservative at unresolved control-flow
  joins. This change does not expand the finite approved-origin tables or relax
  the boundary visitor's diagnostics. `.superpowers/sdd/progress.md` remains
  untouched.
