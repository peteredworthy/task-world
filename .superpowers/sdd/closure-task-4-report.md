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

## Architecture reset: bounded forward-flow provenance

### Root cause and correction

- Repeated review gaps came from the collector's mutable statement walk: only
  aliases participated in branch joins, child traversal was generic rather
  than evaluation-ordered, and exact root imports could be extended into
  unrelated siblings.
- The collector now uses `_FlowState` as the single finite runtime state for
  exact import bindings, projection aliases, receiver candidates, declared and
  runtime field state, and function bindings. `_Outcomes` names normal,
  raised, returned, broken, and continued control paths for the bounded
  interpreter boundary. Static class declarations remain distinct from runtime
  field provenance.
- Expression handling records named expressions after their bind effect and
  joins non-constant short-circuit alternatives. Field joins preserve possible
  provenance without accepting foreign/broad origins. Attribute and subscript
  mutation retain the receiver, while a typed field mutation kills only that
  field until a trusted assignment restores it.
- Import resolution now retains the exact authorized imported subtree beneath
  a root, clears local root rebinding, and rejects a graph-only root used to
  reach the runtime-controller sibling. No migration dependency or prohibited
  migration vocabulary was introduced.

### RED/GREEN evidence

- RED: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` — 3
  new contract failures demonstrated unjoined typed-field state, eager
  short-circuit binding, and graph-root sibling authorization (102 passed,
  3 failed).
- Added focused contracts for direct/killing/short-circuit named expressions
  with boundary diagnostics; intermediate try-handler/finally paths;
  receiver/field set-kill joins; exact graph/runtime import subtrees and root
  rebinding; and receiver-preserving attribute/subscript mutation with
  typed-field-only invalidation.
- GREEN: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` —
  105 passed.
- GREEN: `uv run python scripts/check_graph_projection_boundaries.py` —
  exited 0 with no violations; Ruff check and format checks passed; Pyright
  reported 0 errors, warnings, and information messages.

### Remaining conservative boundary

- At unresolved control-flow joins, approved provenance may remain `possible`
  after an exact approved seed. The collector never broadens that result to an
  unimported or foreign origin. `.superpowers/sdd/progress.md` was not
  modified.

## Outcome-transfer completion

### Root cause and correction

- The prior architecture-reset claim overstated the implementation: `_Outcomes`
  was declared, but block transfer still returned one mutable state and generic
  expression traversal could process nested syntax outside Python evaluation
  order. In particular, raised states between a projection assignment and a
  later kill were not delivered to handlers.
- The active collector now evaluates expressions and statements through
  `_Outcomes`. A block feeds only normal states into its next statement;
  returned, raised, break, and continue outcomes bypass fallthrough.
  Expression children are enumerated in Python order and every evaluated
  operation retains a conservative post-operation raised state.
- `try` sends every intermediate raised body state to handlers, sends only
  normal body completion to `else`, and independently runs `finally` for
  normal, raised, returned, broken, and continued paths. A terminating finally
  replaces the incoming outcome; otherwise its normal completion preserves the
  incoming kind. Loop joins include zero iteration, completed iteration,
  break, and continue paths.

### RED/GREEN evidence

- RED: five new end-to-end guard contracts failed before the replacement:
  pre-kill alias handler/finally provenance, the corresponding typed-field
  provenance, dead statements after return/raise, finally set/kill propagation,
  and zero/continue/break loop joins.
- GREEN: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` —
  110 passed.
- GREEN: `uv run python scripts/check_graph_projection_boundaries.py` — exited
  0 with no output.
- GREEN: Ruff check and format checks passed; Pyright reported 0 errors, 0
  warnings, and 0 information messages.

### Conservative boundary and scope

- The interpreter remains intentionally bounded: it joins unresolved runtime
  branches and operation exceptions as `possible`, which may report an
  additional boundary diagnostic but prevents a projection access from being
  hidden. Exact approved origins, finite state/fact semantics, and the public
  provenance API are unchanged. `.superpowers/sdd/progress.md` was not
  modified.

## Legacy traversal cleanup

### Scope and proof

- Removed only the unreachable `_visit_expr`, `_assign`, `_visit_block`, and
  `_nested_blocks` methods, which were superseded by the `_Outcomes` transfer
  engine and had no callers from `projection_provenance()` or the tests.
- Removed the transitional `_Scope` alias and expressed the unchanged active
  helper signatures directly with `_FlowState`.
- Kept the public provenance API, finite origin tables, fact model, active
  `_evaluate_*` transfer methods, and active state helpers such as `_merge`,
  `_function`, `_class`, and `_typed_producer` intact.
- Added a focused AST structure test preventing the obsolete traversal entry
  points or `_Scope` alias from being reintroduced.

### TDD and verification evidence

- RED: the new structural test failed because the four legacy methods were
  still present.
- GREEN: `uv run pytest
  tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_has_no_legacy_traversal_entry_points -q`
  — 1 passed.
- Full boundary suite: `uv run pytest
  tests/unit/test_graph_projection_boundaries.py -q` — 111 passed.
- Standalone guard: `uv run python scripts/check_graph_projection_boundaries.py`
  — exited 0 with no output.
- Static checks: `uv run ruff check
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py`, `uv run ruff format --check
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py`, and `uv run pyright
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — passed; Pyright reported
  0 errors, 0 warnings, and 0 information messages.
- `.superpowers/sdd/progress.md` was not modified.

## Final bounded-transfer review fixes

### Corrections

- Added ordered expression transfer for list, set, dict, and generator
  comprehensions. Each generator evaluates its iterable before binding its
  target, evaluates filters before the produced element/key/value, and keeps
  comprehension captures scoped so they shadow rather than leak an outer
  projection alias.
- Added ordered `with` and `async with` transfer. Context expressions are
  evaluated left-to-right, optional targets bind from their corresponding
  context expression, body outcomes are retained, and entry/body exception
  paths remain conservative.
- Destructuring assignment now recognizes the exact
  `GraphEventStore.load_projection_with_tail()` shape (including `await`) and
  gives only tuple element zero projection provenance.
- Loop transfer now sends zero-iteration, normal-exhaustion, and continue
  paths into `else`; `break` paths bypass `else` and become normal exits.
  Returned and raised outcomes remain separate.
- Executable non-method class statements now run as one outcome sequence, so
  statements after a terminal class-body raise are unreachable. Methods remain
  isolated function transfers.
- Full-state joins retain the finite union of exact origins, receiver types,
  and function bindings, and union declared/runtime field candidates while
  marking projection values possible where appropriate. No new origin is
  manufactured and sibling-module resolution remains exact.
- Attribute/subscript augmented assignment and deletion preserve an ordinary
  projection receiver alias. Only a direct assignment/deletion of a declared
  typed projection field invalidates that field's runtime provenance.
- `try` now retains every body-raised outcome alongside handler outcomes;
  unresolved exception types can be handled or unmatched, and both paths pass
  through `finally`.
- Chained assignment evaluates the RHS once, evaluates each assignment target
  once in Python order, and binds each target once. This also preserves
  stateful target/walrus effects without the prior nested all-target loop.

### RED/GREEN evidence

- RED: the nine new bounded-transfer regressions were run together before the
  implementation. Six failed for the intended missing behavior: all four
  comprehension forms, `with`/`async with` target binding, first tuple-item
  producer binding, break-bypasses-else, terminal class-body reachability, and
  joined ordinary receiver/origin state. The remaining three captured
  pre-existing behavior while protecting the refined mutation, unmatched
  exception, and chained-assignment contracts.
- GREEN: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` —
  **120 passed**.
- Standalone guard: `uv run python scripts/check_graph_projection_boundaries.py`
  — exited 0 with no output.
- Static checks: `uv run ruff check
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py`, `uv run ruff format --check
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py`, and `uv run pyright
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — passed; Pyright reported
  0 errors, 0 warnings, and 0 information messages.

### Concerns

- The collector deliberately remains a bounded conservative interpreter:
  unresolved branches and exception matching can retain an approved projection
  as `possible`, but exact finite import origins are never widened. No public
  API changed, and `.superpowers/sdd/progress.md` was not modified.

## Review-blocker closure: scope, finite joins, and ordered transfers

### Corrections

- Comprehension generator targets now bind only in the temporary comprehension
  state. The temporary bindings are restored to the enclosing state after the
  produced expression, while effects from iterable evaluation and non-target
  named expressions remain available conservatively.
- Exact imports, receiver types, and local function return bindings now use
  finite `frozenset` candidates rather than pipe-delimited strings. A call is
  definite only when every candidate is an approved projection producer;
  approved/unknown mixtures are possible, and exact-import subtree checks
  still reject sibling paths.
- Assignment transfer evaluates the RHS once, then evaluates and assigns every
  target left-to-right, carrying each completed target state into the next.
  Dictionary-comprehension key evaluation likewise feeds its resulting state
  into value evaluation.
- `with` and `async with` preserve body-raised outcomes and also retain a
  downgraded possible-normal continuation because unresolved `__exit__` and
  `__aexit__` methods may suppress the exception.

### RED/GREEN evidence

- RED: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` — 4
  failures (122 passed): comprehension target leakage removed the later outer
  access; heterogeneous approved factory/function joins were lost; and both
  synchronous and asynchronous `with` body raises had no normal continuation.
  The chained-target and dictionary-key/value contracts were added before the
  implementation and protected sequencing that happened to be represented by
  the prior mutable-state flow; the transfer code was still made explicitly
  ordered so later outcome splitting cannot regress it.
- GREEN: `uv run pytest tests/unit/test_graph_projection_boundaries.py -q` —
  126 passed.
- GREEN: `uv run python scripts/check_graph_projection_boundaries.py` — exited
  0 with no output.
- GREEN: `uv run ruff check scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — passed; `uv run ruff
  format --check scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — passed; `uv run pyright
  scripts/graph_projection_boundary_provenance.py
  tests/unit/test_graph_projection_boundaries.py` — 0 errors, 0 warnings, 0
  information messages.

### Conservative boundary

- The interpreter does not resolve runtime iteration cardinality, dynamic
  receiver methods, or context-manager exit return values. It retains approved
  provenance as `possible` whenever a feasible candidate/path remains, but it
  never turns an unimported sibling path into an approved origin.
  `.superpowers/sdd/progress.md` was not modified.
