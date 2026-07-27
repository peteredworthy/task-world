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
