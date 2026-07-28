# Task 3e1: Inventory Operation Stream And Structural Grouping — Report

## Result

Implemented the source-independent inventory boundary and replaced the abandoned
typed-parameter codemod with an inventory-driven operation-stream compiler. The
compiler performs no consumer transformation or repository write.

## RED / GREEN evidence

**RED**

```text
$ uv run pytest tests/unit/test_migrate_graph_projection_queries.py -q
ERROR ... ModuleNotFoundError: No module named
'scripts.codemods.migrate_graph_projection_queries'
```

The failing test was introduced after deleting the incompatible prototype. It
specified source snapshots, authoritative inventory adaptation, exact-once site
coverage, blank-line re-anchoring, digest/ambiguity refusal, structural-only
grouping, and live repository coverage.

**GREEN**

```text
$ uv run pytest tests/unit/test_migrate_graph_projection_queries.py -q
6 passed in 83.28s

$ uv run pytest tests/unit/test_migrate_graph_projection_queries.py \
    tests/unit/test_graph_projection_inventory.py -q
106 passed in 117.71s
```

## Implementation

- `InventorySource` and `inventory_sources(sources, manifest)` make collection
  operate on supplied source text. `inventory_paths()` and
  `inventory_repository()` remain I/O adapters over that boundary.
- `AccessInventory` now carries frozen blank-line-insensitive source digests.
- The compiler consumes only the authoritative `AccessInventory` and generated
  query-migration skeleton identities. It emits frozen source locator, anchor
  evidence, source digest, origin, original ID, access/diagnostic metadata, and
  structural shape records.
- One LibCST metadata pass per compiled source supplies position and parent
  evidence. Recorded locations disambiguate otherwise identical non-inventory
  syntax; moved blank lines re-anchor by normalized identity. Digest changes,
  missing snapshots, missing skeleton identities, and ambiguous anchors refuse
  compilation.
- `shape_summary(stream)` returns the machine-readable deterministic
  `shape-key -> count` mapping. Its key is exactly access kind, old field,
  diagnostic code, parent shape, and operation shape.

## Generated live-inventory counts

```text
occurrences:        123
diagnostics:        680
anchored sites:     803
test-path sites:    456 (includes all 349 remaining test_fixture sites)
structural groups:   86
```

The count was generated with:

```text
$ uv run python -c '<inventory_repository + SourceSnapshot +
  compile_operation_stream + shape_summary command>'
{'occurrences': 123, 'diagnostics': 680, 'sites': 803,
 'test_fixture_sites': 456, 'shape_groups': 86}
```

## Verification

```text
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
746 files already formatted

$ uv run pyright
0 errors, 0 warnings, 0 informations

$ uv run pytest
4990 passed, 3 skipped, 3 warnings in 196.98s
```

The three warnings are the existing Python 3.12 `aiosqlite` default datetime
adapter deprecations reported by `tests/unit/test_projectors.py`.

## Files changed

- `scripts/graph_projection_inventory.py`
- `scripts/codemods/migrate_graph_projection_queries.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `.superpowers/sdd/task-3e1-report.md`

## Self-review

- Confirmed the old `_TypedProjectionVisitor` and scalar rule table are absent.
- Confirmed no consumer or test-fixture source was transformed.
- Confirmed grouping does not include site ID, path, function, or source text.
- Confirmed every live inventory occurrence/diagnostic produces exactly one
  anchored site and that the live test-path total exceeds the required 349.
- Confirmed all cross-boundary Pydantic models added for this task are frozen
  and reject extra fields.

## Concerns

The source digest intentionally excludes blank lines so formatting-only
blank-line movement can re-anchor. Other whitespace-only semantic-neutral edits
are still represented in normalized CST identity checks; any changed semantic
expression, stale digest, or ambiguous anchor fails closed. The report does not
publish a repository artifact because publication is explicitly out of scope;
the summary remains a pure machine-readable compiler result.
