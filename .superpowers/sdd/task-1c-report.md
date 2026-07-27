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
