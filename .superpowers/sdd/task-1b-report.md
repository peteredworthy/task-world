# Task 1b: LibCST Inventory Collector Report

## Delivered

- Added frozen, extra-forbidding inventory models and the `AccessKind` enum.
- Implemented `collect_source()` using LibCST parsing plus position and parent metadata.
- Seeded only function parameters and local annotations explicitly typed `GraphProjection`, and
  tracked direct aliases only within their declaring function scope.
- Classified the requested literal-key access families, preserved position strictly as report
  metadata, and generated deterministic position-independent occurrence IDs.
- Added fail-closed diagnostics for parse errors, computed and unknown keys, reflection,
  projection unpacking, `dict(projection)`, and unsupported projection calls.
- Did not scan repository paths, emit a baseline, or edit production consumers.

## RED Evidence

1. After adding the collector tests before the collector implementation:

   ```text
   uv run pytest tests/unit/test_graph_projection_inventory.py -q
   ImportError: cannot import name 'collect_source' from 'scripts.graph_projection_inventory'
   ```

2. After the initial implementation, the rejection test was added before its implementation:

   ```text
   FAILED test_collect_source_rejects_reflection_unpacking_and_unsupported_calls
   AssertionError: assert [] == ['reflection', 'projection_unpacking', ...]
   ```

## GREEN Evidence

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
15 passed in 2.93s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4867 passed, 3 skipped, 3 warnings in 80.00s
```

The full-suite warnings are existing `aiosqlite` Python 3.12 datetime-adapter deprecation
warnings from three projector tests; the suite otherwise passed.

## Tests Added

- One real source fixture covers every supported access kind.
- Computed key, unknown literal field, and invalid-source parse diagnostics.
- Direct alias tracking, alias rebinding, and nested-scope isolation.
- Position-independent identity with deterministic repeated-expression ordinals.
- `getattr`, projection unpacking, `dict(projection)`, and unsupported-call rejection.

## Files Changed

- `scripts/graph_projection_inventory.py`
- `tests/unit/test_graph_projection_inventory.py`

## Self-review

- Confirmed occurrences sort by path, qualified function, source position, and kind.
- Confirmed IDs contain no line or column data.
- Confirmed each occurrence/diagnostic model is frozen and forbids extra values.
- Confirmed the collector uses the committed Task 1a manifest as its sole field vocabulary.
- Confirmed no `access_inventory.json` was written and no production consumer was changed.

## Concerns

- This intentionally bounded single-source collector does not perform repository traversal,
  inter-procedural return inference, import-alias closure, or baseline generation; those are
  explicitly outside Task 1b.

## Review-Fix Evidence (2026-07-26)

### RED

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
3 failed, 15 passed
```

The added tests exposed silent unsupported-binding/construction handling, missing class/scope
qualification and alias isolation, and formatting-sensitive identities. A later exact-count
assertion also correctly failed at `assert 19 == 18` before the fixture count was corrected.

### GREEN

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
18 passed in 3.36s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4870 passed, 3 skipped, 3 warnings in 87.13s
```

### Review fixes

- Added strict frozen inventory models, constrained ordering and diagnostic-code enums, and
  enum-valued occurrence classification.
- Added fail-closed diagnostics for unsupported bindings, loop and assignment-expression
  rebinding, positional and `**` construction, reflection, unpacking, unsupported calls, and
  chained comparisons.
- Used LibCST scope metadata for alias ownership; class-qualified function names now include
  enclosing classes, and nested function/lambda/comprehension scopes cannot inherit aliases.
- Canonicalized occurrence expressions through Python's AST renderer, making identities stable
  across whitespace, comments, quote style, and line shifts.
- Added `not in` classification and strengthened fixture assertions for exact occurrence count,
  scope, ordering disposition, and fail-closed one-to-one diagnostics.

## Remaining Review-Fix Evidence

### RED

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
1 failed, 18 passed
```

The new binding/call-shape fixture initially exposed silent augmented/destructured binding and
starred-call handling, plus a subscript read emitted beneath an invalid append call.

### GREEN

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
19 passed in 2.92s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4871 passed, 3 skipped, 3 warnings in 86.49s
```

The collector now rejects typed alias loss, augmented and destructured-loop rebinding, with and
exception targets, starred projection call arguments, and invalid supported-method call shapes.

## Final Completion Evidence (2026-07-26)

### RED

The preserved collector suite was expanded before production changes to cover the remaining
comparison, seed, method-call, stale-alias, and lexical-qualification cases:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
5 failed, 19 passed in 3.54s
```

The failures showed unrelated chained comparisons were diagnosed, zero-parameter and variadic
annotation seeds were absent, subscript method calls produced false reads, unsupported rebinding
left aliases live, and interleaved scopes were ordered as `Nested.outer.method`. A second
test-first refinement added a chained subscript operand and correctly failed before suppression:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
1 failed, 23 passed in 3.19s
```

The lexical identity fixture was strengthened to demonstrate the former collision between
`outer.Nested.method` and `Nested.outer.method`; the pre-fix stack ordering failed it:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py::test_collect_source_uses_lexical_qualified_function_identity -q
1 failed in 2.92s
```

### GREEN

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
24 passed in 2.91s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4876 passed, 3 skipped, 3 warnings in 80.42s
```

The three full-suite warnings are the existing `aiosqlite` Python 3.12 datetime-adapter
deprecations in `tests/unit/test_projectors.py`.

### Final fixes

- Chained comparisons are ignored unless a tracked projection (including a direct tracked
  subscript operand) participates; projection chains diagnose and suppress child read records.
- Function scope seeding consistently uses the function body scope, which supports no-parameter
  functions, local `GraphProjection` annotations, and annotated `*args` / `**kwargs`.
- Calls on `projection["field"]` permit only exact `append` and `extend` shapes. Every other
  method diagnoses as unsupported and suppresses its child subscript read.
- Augmented assignment, `with ... as`, and `except ... as` diagnostics now discard the affected
  tracked alias before later source is collected.
- A single lexical definition stack preserves actual function/class nesting order in qualified
  function identities.

## Remaining Fail-Closed Collector Review Evidence (2026-07-26)

### RED

Focused fixtures were added before collector changes for all remaining review findings. The
unmodified collector failed the new cases while the previously preserved cases continued to run:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
7 failed, 26 passed in 3.15s
```

The failures demonstrated unrelated subscript-method diagnostics, omitted deep subscript
accesses, alias removal before RHS traversal, stale historical aliases after normal rebinding,
permissive `cast` shapes and missing callable/constructor escapes, missing simple/get comparison
diagnostics, missing comprehension iteration, and definition metadata qualified with the body
name. The direct strict/frozen/enum model and complete sort-tuple fixtures passed initially,
confirming their existing contracts before the collector change.

### GREEN

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
33 passed in 3.01s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4885 passed, 3 skipped, 3 warnings in 81.56s
```

The three full-suite warnings remain the existing Python 3.12 `aiosqlite` default datetime-adapter
deprecations from `tests/unit/test_projectors.py`.

### Review fixes

- A tracked-field-chain helper now gates subscript method diagnostics on a chain rooted in a
  tracked projection alias, so unrelated `mapping["key"].update()` and `.clear()` are ignored.
- Deep tracked reads and assignments are classified at their outer expression once, with the root
  manifest field retained and every visited chain node suppressed thereafter.
- `Assign` and `AnnAssign` apply alias changes on leave, preserving the pre-assignment alias
  environment for RHS reads and escapes; ordinary rebinding removes both live and historical alias
  membership.
- Unsupported rebinding remains fail-closed while retaining its historical-alias diagnostic path;
  later loop/with/except targets after ordinary rebinding are ignored.
- `cast` requires exactly two unstarred, unkeyworded arguments with a tracked projection-field
  second operand; tracked projections invoked as callables diagnose; `GraphProjection` keyword
  construction records projection-valued arguments as untyped escapes while retaining constructor
  validation.
- Simple and chained comparisons diagnose only when direct tracked fields, aliases, or tracked
  `.get()` calls participate; their child field/call occurrences are suppressed. `CompFor` direct
  projection iteration is recorded as `direct_iteration`.
- Function and class names are pushed only while their bodies are traversed, so defaults,
  decorators, and annotations retain their enclosing metadata execution scope.
- Tests now directly assert strict/frozen enum-valued inventory models and the complete documented
  occurrence sorting tuple.

### Remaining bounded-scope concern

The collector still intentionally performs no repository traversal, inter-procedural alias or
return inference, import-alias closure, or baseline emission. Those exclusions remain explicit
Task 1b boundaries rather than completeness claims.

## Final Task 1b Fix Evidence (2026-07-27)

### RED

After adding regression fixtures for augmented projection mutations, nested deletes, one- and
two-argument `get`/`pop` calls, and methods on `get` results, the focused collector suite failed
in the expected four new tests:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
4 failed, 33 passed
```

The failures were the pre-fix child reads from augmented assignments and nested deletes, rejected
two-argument `get`/`pop` shapes, and the inner-only `get` occurrence for a `get`-result method.

### GREEN and verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
37 passed in 3.06s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4889 passed, 3 skipped, 3 warnings in 81.55s
```

The three full-suite warnings remain the existing Python 3.12 `aiosqlite` datetime-adapter
deprecations in `tests/unit/test_projectors.py`.

### Final fixes

- Added an explicit `unsupported_mutation` diagnostic for direct and deep augmented projection
  assignments, suppressing every child subscript read.
- Classified direct and nested `del` chains as `delete_pop`, suppressing child reads.
- Classified supported `append`/`extend` calls on `projection.get(...)` values and diagnosed
  unsupported result methods without emitting an inner-only `get` occurrence.
- Accepted exactly one or two positional arguments for both `projection.get(...)` and
  `projection.pop(...)`; invalid arities remain fail-closed.

### Files changed in this final fix

- `scripts/graph_projection_inventory.py`
- `tests/unit/test_graph_projection_inventory.py`
- `.superpowers/sdd/task-1b-report.md`

No progress ledger was edited. The bounded-scope concerns above remain unchanged.

## Final Localized Task 1b Fix Evidence (2026-07-27)

### RED

The exact direct/deep projection-value invocation and destructured-target fixtures were added
before the collector fix:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
2 failed, 37 passed in 4.26s
```

The failures showed child `get`/subscript reads surviving unsupported direct calls and reads being
emitted for tuple/list assignment and multi-target deletion targets.

### GREEN and verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
39 passed in 3.69s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4891 passed, 3 skipped, 3 warnings in 101.29s
```

The three full-suite warnings remain the existing Python 3.12 `aiosqlite` datetime-adapter
deprecations in `tests/unit/test_projectors.py`.

### Final localized fixes

- Direct invocation of tracked projection values, including `get` results and deep subscript
  chains, now emits `unsupported_call` and suppresses every child supported occurrence.
- Destructured assignment targets and multi-target deletion targets now emit exactly one
  deterministic fail-closed diagnostic per tracked projection target and suppress child reads.
- Destructured assignments with a tracked RHS avoid an additional generic binding diagnostic, so
  the target-level diagnostic remains one-to-one.

### Files changed in this localized fix

- `scripts/graph_projection_inventory.py`
- `tests/unit/test_graph_projection_inventory.py`
- `.superpowers/sdd/task-1b-report.md`

## Final Localized Task 1b Fix Evidence (2026-07-27, final two fixes)

### RED

Parametrized regression tests for invocation of every supported projection-method result, plus
starred projection-target and alias-rebinding tests, were added before the implementation change:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
8 failed, 41 passed
```

The failures showed supported `pop`, `setdefault`, `keys`, `values`, `items`, `append`, and
`extend` results being recorded instead of rejected, and starred targets being missed by target
diagnostics and alias clearing.

### GREEN and verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
51 passed in 4.35s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4903 passed, 3 skipped, 3 warnings in 99.46s
```

The three full-suite warnings remain the existing Python 3.12 `aiosqlite` datetime-adapter
deprecations from `tests/unit/test_projectors.py`.

### Final fixes

- All supported projection method results are treated as projection-derived when directly
  invoked; the outer call emits `unsupported_call` and suppresses the inner supported occurrence,
  including field and `.get()`-result `append`/`extend` chains.
- Projection target-subscript and target-name traversal recurses through `cst.StarredElement`, so
  starred destructuring emits the target diagnostic and clears stale projection aliases.
- Starred assignment targets are excluded from the generic projection-unpacking diagnostic; their
  fail-closed binding diagnostic is produced by assignment-target analysis instead.

## Final Task 1b Fix Evidence (2026-07-27, remaining Important findings)

### RED

Parametrized regressions for mixed/starred alias rebinding, chained supported-method results, and
invalid deep subscripts were added before the collector change:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
8 failed, 51 passed
```

The failures showed that a projection target in mixed/starred destructuring prevented the generic
rebind cleanup from clearing a live alias, method-result calls through `Attribute` and `Subscript`
chains leaked inner supported occurrences, and invalid root subscripts emitted duplicate
diagnostics while their deep expression was visited.

### GREEN and verification

```text
uv run pytest tests/unit/test_graph_projection_inventory.py -q
59 passed in 4.12s

uv run ruff check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
All checks passed!

uv run ruff format --check scripts/graph_projection_inventory.py tests/unit/test_graph_projection_inventory.py
2 files already formatted

uv run pyright scripts/graph_projection_inventory.py
0 errors, 0 warnings, 0 informations

make test
4911 passed, 3 skipped, 3 warnings in 97.13s
```

The three full-suite warnings remain the existing Python 3.12 `aiosqlite` default datetime-adapter
deprecations from `tests/unit/test_projectors.py`.

### Final fixes

- Alias cleanup now runs independently of projection-target diagnostics, clearing every rebound
  live alias name in mixed and starred destructuring while retaining one target diagnostic.
- Projection-derived detection now recurses through `Attribute` and `Subscript` chains, so calls
  on `keys()`, `setdefault()`, `pop()`, and `get()[...]` results emit one `unsupported_call` and
  suppress all inner supported occurrences.
- Diagnostics are deduplicated by localized CST node and diagnostic code, preserving the first
  occurrence and preventing duplicate computed-key or unknown-field reports for deep subscripts.

### Files changed in this final fix

- `scripts/graph_projection_inventory.py`
- `tests/unit/test_graph_projection_inventory.py`
- `.superpowers/sdd/task-1b-report.md`
