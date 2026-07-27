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
