# Task 1c Report — Repository Data-Flow And Escape Closure

## RED

The repository aggregate interfaces were absent. The new focused data-flow,
attribute/context, escape, exclusion, sorting, and detached-attribute tests
first failed at collection with:

```text
ImportError: cannot import name 'AccessInventory'
```

During the required real-repository diagnosis, a valid chained attribute caused
the collector to attempt `ast.parse()` on a detached `.join` fragment. A focused
regression test was added before replacing that fragment rendering with a
structural dotted-attribute key.

## GREEN

- Added strict frozen `AccessInventory`, `inventory_paths()`, and
  `inventory_repository()`; aggregates retain Task 1b occurrence identity and
  deterministic ordering.
- Added bounded local return-flow seeds for `initial_projection`,
  `build_projection`, `reduce_event`, and explicitly `GraphProjection`-typed
  pass-through functions.
- Added local assignment and `GraphDispatchContext.graph_projection` attribute
  flow; the collector tracks only structurally named attributes assigned from a
  known projection value.
- Added fail-closed diagnostics and remediation text for `Any` bindings,
  unknown callbacks, and imported aliases. Repository scanning only includes
  `src`, `tests`, and `scripts`, excluding worktrees, virtual environments,
  vendor trees, and cache directories.
- Added `--diagnose`; it prints the sorted remediation report, exits nonzero
  when unresolved sites exist, and does not write `access_inventory.json`.

## Verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
63 passed in 4.44s

uv run python scripts/graph_projection_inventory.py --diagnose
exit 1; printed 2,188 sorted unresolved remediation sites

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4915 passed, 3 skipped, 3 existing aiosqlite datetime-adapter warnings in 98.28s
```

## Remaining remediation inventory

The checked-in baseline was not created. `--diagnose` is the exact sorted
site-level list; its 2,188 explicit unresolved sites are:

| Code | Sites | Required remediation |
| --- | ---: | --- |
| `unsupported_binding` | 1,777 | Replace dynamic or untyped binding with a typed `GraphProjection` flow. |
| `unsupported_call` | 341 | Replace dynamic callback/call flow with a bounded typed operation. |
| `unsupported_comparison` | 70 | Rewrite comparison through an explicit typed projection field/query. |

No broad production consumer remediation was made in this task: the remaining
sites are deliberately reported rather than silently classified or fabricated
as resolved.

## Provenance-first review remediation

The original aggregate used imported-name and process-global attribute heuristics.
Those caused ordinary generic subscriptions to be reported and could leak an
attribute origin across functions. This revision removes imported-subscript
diagnosis, records diagnostic qualified functions, bounds attribute provenance
to the active lexical scope, and seeds it only from exact local
`GraphProjection` field annotations or constructor keyword flow. Producer names
now require an exact `GraphProjection` return annotation (plus the explicit
projection constructors), rather than inferred return bodies.

`inventory_repository()` now accepts an injected tracked-path provider for
tests and otherwise obtains only `git ls-files -- '*.py'`; duplicate paths are
removed before collection. `--diagnose` prints qualified function, diagnostic
message, and tailored remediation text. The real tracked-repository result is
**411** unresolved diagnostics: **341 `unsupported_call`** and **70
`unsupported_comparison`**. The checked diagnostic artifact is the sorted
command output captured during verification; representative first categories
are calls on projection-derived values and unsupported projection comparisons,
not fabricated binding counts.

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
65 passed in 3.90s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4917 passed, 3 skipped, 3 existing aiosqlite warnings in 98.82s
```

## Remaining-gap closure (2026-07-27)

### RED/GREEN

- Added focused failing tests for unrecognized tracked callable arguments,
  exact `GraphController.read_projection` and
  `GraphEventStore.load_projection_with_tail` provenance (including untyped
  shadowing), `GraphProjectionCheckpoint.projection`, `getattr`/`setattr`/
  `vars`/`__dict__`, `Any` and `Callable` annotation escapes, and a sorted
  report with category counts. The initial RED failed because
  `diagnostic_report` did not exist.
- Replaced the former generic `UNTYPED_ESCAPE` occurrence for a tracked call
  argument with an `unsupported_call` diagnostic. Every tracked argument sent
  to a callable outside the bounded recognized call handling now has tailored
  remediation; it cannot be hidden by an ordinary occurrence record.
- Added exact receiver-type/method and type/field tables. Only a receiver
  annotated as `GraphController` or `GraphEventStore` seeds its corresponding
  awaited producer; only `GraphDispatchContext.graph_projection` and
  `GraphProjectionCheckpoint.projection` seed the explicit field flow.
  Same-spelling values annotated as `object` are intentionally not tracked.
- Added deterministic `diagnostic_report()` and the checked representative
  fixture `docs/graph-projection-inventory-diagnostics.md`. A real-production
  inventory test injects tracked `recovery.py` and `store.py` paths, asserts the
  production recovery flow is present, and verifies every unresolved result has
  a report line and remediation. Injecting paths keeps that unit test below its
  30-second timeout; the full tracked-repository scan remains the CLI check.

### Final diagnose result

```text
uv run python scripts/graph_projection_inventory.py --diagnose
exit 1 (expected while unresolved sites remain)

Unresolved GraphProjection flows: 891
unsupported_call: 820
unsupported_comparison: 71
```

The inventory is deliberately **not zero**. The remaining diagnostics are
explicitly reported bounded call and comparison flows; this task does not claim
they have been migrated.

### Verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
71 passed

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations
```

## Historical provenance report (2026-07-27)

### Superseded partial provenance-first pass

- Attribute provenance is admitted only for a declared `GraphProjection` field
  on an explicitly resolved receiver type. Attribute overwrite and root-name
  rebinding discard that provenance; unsupported projection attribute writes
  diagnose rather than becoming tracked implicitly.
- This was an intermediate implementation claim. It did not yet enforce exact
  fully-qualified origins, lexical shadow invalidation, Python argument
  binding, or all collection boundaries, so it is not authoritative for the
  final Task 1c result.
- The collector diagnoses unbounded `Any`/`Callable`/`object` annotations,
  assignment into an already unbounded binding, unresolved projection returns,
  and collection-constructor escapes. It deliberately does not generalize into
  inter-procedural inference.
- `inventory_paths(paths, manifest)` now derives a common path root when the
  caller omits one. `diagnostic_report()` renders each stored remediation (not
  a recomputed fallback) and deterministically sorts totals and sites.
- The default real Git tracked-path provider is covered for representative
  prompts, dispatch, recovery, and store flows; its test verifies that
  worktree/vendor paths are excluded. The checked diagnostics artifact now
  contains every current sorted diagnostic, rather than representative samples.

### Historical diagnostic inventory (superseded)

The then-current diagnostic count is historical only; the authoritative count
is the generated artifact and final closure report below.

| Code | Count |
| --- | ---: |
| `unsupported_binding` | 7 |
| `unsupported_call` | 564 |
| `unsupported_comparison` | 71 |

The complete deterministic site list is checked in at
`docs/graph-projection-inventory-diagnostics.md` (657 lines including its
header and fenced report). These are outstanding migration sites, not silently
accepted accesses. No general inter-procedural inference was added.

### Historical verification evidence

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
74 passed in 50.12s

uv run python scripts/graph_projection_inventory.py --diagnose
exit 1 expected; 642 sorted diagnostics

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4926 passed, 3 skipped, 3 existing aiosqlite datetime-adapter warnings in 108.12s
```

## Final provenance closure (2026-07-27)

- The authoritative module table now recognizes only explicit approved
  fully-qualified graph symbols and `typing.cast`; foreign same-tail imports
  are never trusted. Parameter, assignment, definition, producer, constructor,
  and imported-cast shadows invalidate those symbols in their lexical scope.
- Local callable signatures record positional and keyword parameter names and
  exact `GraphProjection` slots. Calls use conservative Python binding and
  diagnose tracked values bound to any other parameter or an ambiguous/variadic
  shape.
- Lists, tuples, sets, and dictionary values recurse at assignment (annotated
  or plain), return, and call boundaries. Each escape emits one outer
  diagnostic; nested child reports are suppressed.
- `diagnostic_artifact()` is the exact output of `--diagnose`, and its unit
  test compares the full tracked repository generation byte-for-byte to
  `docs/graph-projection-inventory-diagnostics.md`.

The regenerated authoritative artifact reports **646** unresolved flows:
`unsupported_binding: 9`, `unsupported_call: 566`, and
`unsupported_comparison: 71`. They are deliberate fail-closed migration
diagnostics, not inferred safe flows.

## Final approval-blocker closure (2026-07-27)

### Scope and origin invariants

- The approved-origin table now admits only explicit fully-qualified imports
  for graph symbols and projection producers. Repository collection no longer
  treats an unbound `GraphProjection` spelling as approved; isolated
  `collect_source()` fixtures retain their explicit compatibility seed.
- Local producer calls are accepted only when the module declaration has an
  exact resolved `GraphProjection` return annotation. Parameter, assignment,
  local-import, and nested-definition bindings shadow that declaration and
  prevent its return provenance from being used.
- Qualified roots are resolved before attributes: `typing as t` permits
  `t.cast` only until `t` is rebound. The same lexical invalidation applies to
  imported constructors and producer aliases.
- Annotation normalization recognizes outer generic and union forms while
  retaining `Any`, `Callable`, and `object` as delayed binding types. This
  preserves the fail-closed diagnostic when a known projection is assigned
  later.
- Local annotations now seed receiver provenance for
  `GraphDispatchContext` and `GraphProjectionCheckpoint`; assigning a new
  root value clears that receiver type before a later attribute access.

### Adversarial coverage and generated artifact

Focused regressions cover local producer shadowing, approved producer origins,
unbound repository names and top-level rebinding, a shadowed `typing` module
alias, union/generic delayed bindings, and receiver-type population/clearing.
The checked artifact was regenerated from `--diagnose` and is byte-for-byte
asserted against a fresh full tracked-repository inventory.

The authoritative generated diagnostic inventory is **363** unresolved flows:
`unsupported_binding: 9`, `unsupported_call: 288`, and
`unsupported_comparison: 66`.

### Focused evidence

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
80 passed in 50.46s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

uv run python scripts/graph_projection_inventory.py --diagnose
exit 1 expected; 363 unresolved flows

make test
4932 passed, 3 skipped, 3 aiosqlite datetime-adapter warnings in 125.97s
```

## Historical Task 1c closure (2026-07-27)

- Provenance now admits only exact `GraphProjection` annotations: generic and
  union wrappers are boundaries, never seeds, and emit a fail-closed diagnostic
  when a known projection crosses them.
- Local callable signature binding checks lexical shadowing before lookup.
  Projection-shaped imported aliases, unsupported module-level flow, and
  shadowed producer/constructor/module aliases diagnose instead of inheriting
  provenance.
- `import orchestrator.graph as graph` resolves approved symbols; resolved
  typed constructors and every resolved `typed_fields` receiver support
  initialization, overwrite, and root-rebind invalidation.
- Removed the obsolete parallel return/typed-field/import-call provenance
  scanners. `_ModuleSymbols` is the sole resolver. The byte-exact artifact was
  regenerated from the tracked repository.

Authoritative outstanding inventory: **409** fail-closed diagnostics —
**42** `unsupported_binding`, **302** `unsupported_call`, and **65**
`unsupported_comparison`. These are migration work items, not accepted flows.

Focused verification: `81 passed`; Ruff and Pyright passed. `--diagnose`
intentionally exits 1 while the above diagnostics remain.

## Historical blocker verification (2026-07-27)

- Ordered AST declaration facts now preserve function, class, and variable
  annotation provenance at the declaration position. The CST pass consumes
  those facts rather than a final module binding table, so an approved alias
  remains valid before a later rebind and is not inferred before an import.
- Function-local foreign imports that bind the reserved `GraphProjection`
  spelling are resolved per lexical scope. Nested declarations emit the
  explicit unresolved-import binding diagnostic at their qualified declaration.
- `docs/graph-projection-inventory-diagnostics.md` is the authoritative,
  byte-exact generated `--diagnose` artifact. Its intentional nonzero command
  result reports **409** unresolved flows: **42** `unsupported_binding`,
  **302** `unsupported_call`, and **65** `unsupported_comparison`.

Final-head verification:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
88 passed in 50.38s

uv run python scripts/graph_projection_inventory.py --diagnose
exit 1 expected; checked artifact is byte-exact; 409 unresolved flows

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

uv run pytest
4940 passed, 3 skipped, 3 aiosqlite datetime-adapter warnings in 124.02s
```

## Authoritative final report (2026-07-27)

The checked `docs/graph-projection-inventory-diagnostics.md` fixture is the
authoritative, byte-exact output of a fresh full tracked-repository
`--diagnose` run. It reports **402** unresolved flows:
**35** `unsupported_binding`, **302** `unsupported_call`, and **65**
`unsupported_comparison`.

The prior closure counts above are retained as dated historical evidence only;
they are not final inventory claims. The current artifact summary is the sole
authoritative count.

## Task 1c blocking fix (2026-07-27)

### Diagnosis and RED

The collector already records declaration annotations in source order, but
`visit_AnnAssign` recomputed `Any`/`Callable` through the final module symbol
table. A later module-level alias rebind therefore erased the escape type and
allowed initialized `initial_projection()` values through. Separately,
`leave_AnnAssign` checked only `_tracked`, so it missed known producer values
that had not first been assigned to a tracked alias.

The new focused regressions failed before the fix:

```text
test_inventory_paths_uses_ordered_escape_annotations_before_later_alias_rebind
AssertionError: assert [] == ['unsupported_binding', 'unsupported_binding']

test_inventory_paths_diagnoses_known_producer_lost_by_annotated_assignment
AssertionError: assert [] == ['unsupported_binding']
```

### GREEN

- `visit_AnnAssign` now checks the already position-correct resolved
  annotation for unbounded `Any`/`Callable` escapes, including initialized
  known producer values.
- `leave_AnnAssign` now uses `_known_projection_value` when diagnosing a
  projection assigned to a non-projection annotation.
- Added regressions covering later `Any` and `Callable` alias rebinds and the
  initialized known-producer assignment boundary.

### Verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
96 passed

uv run python scripts/graph_projection_inventory.py --diagnose
exit 1 (expected); 395 unresolved flows
unsupported_binding: 65
unsupported_call: 280
unsupported_comparison: 50
```

The fresh diagnose output is byte-identical to
`docs/graph-projection-inventory-diagnostics.md`; no artifact content change
was required.

```text
uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run pyright scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

uv run pytest
4948 passed, 3 skipped, 3 aiosqlite datetime-adapter warnings in 127.87s
```
