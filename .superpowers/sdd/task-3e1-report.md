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

## Independent-review fix wave

### RED / GREEN

**RED:** the new source-independent diagnostic snapshot tests initially failed
with `TypeError: query_migration_skeleton() missing 1 required positional
argument: 'root'`; the live exact-fixture assertion also exposed that the raw,
complete current skeleton contains 449 `test_fixture` IDs, not the historical
349 stated in the review.

**GREEN:**

```text
$ uv run pytest tests/unit/test_migrate_graph_projection_queries.py \
    tests/unit/test_graph_projection_inventory.py -q
108 passed in 116.78s

$ uv run ruff check scripts/graph_projection_inventory.py \
    scripts/codemods/migrate_graph_projection_queries.py \
    tests/unit/test_migrate_graph_projection_queries.py
All checks passed!

$ uv run ruff format --check scripts/graph_projection_inventory.py \
    scripts/codemods/migrate_graph_projection_queries.py \
    tests/unit/test_migrate_graph_projection_queries.py
3 files already formatted

$ uv run pyright
0 errors, 0 warnings, 0 informations

$ uv run pytest
4992 passed, 3 skipped, 3 warnings in 209.54s
```

### Fixes

- Occurrence anchors now narrow candidates structurally, recompute canonical
  IDs from scoped normalized expressions and recomputed candidate ordinals, and
  require the corresponding generated-skeleton identity. The recorded locator
  is no longer an identity selector.
- Diagnostics now retain source pattern, same-pattern ordinal, CST node type,
  and normalized CST expression at collection time. Skeleton keys and
  generation consume this captured evidence and do not reread repository files.
  Diagnostic re-anchoring is scoped, checks cardinality and CST evidence, and
  has no module fallback.
- `source_digest()` now hashes Python token type/content pairs while ignoring
  only layout-only `NL` tokens. Multiline string token contents remain intact;
  compile-time digest verification is mandatory and no public bypass remains.
- The live test derives fixture IDs from the generated skeleton and requires
  every derived ID exactly once in the compiled stream. The current complete
  generated set is 449 IDs; the requested historical count of 349 does not
  match this branch's authoritative collector output.
- Parent and operation classification is finite and raises
  `AnchorRefusedError` for unrecognized structures rather than silently using
  generic shapes. Current encountered contexts include condition, iterable,
  comparison/membership, nested/attribute receiver, typed parameter,
  collection element, assignment, call, return, annotation, deletion, and
  yield/await.
- The source-parity test now compares the snapshot collector directly against
  the filesystem adapter for equivalent text; diagnostic snapshot tests use a
  deliberately nonexistent repository path.

### Changed files

- `scripts/graph_projection_inventory.py`
- `scripts/codemods/migrate_graph_projection_queries.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `.superpowers/sdd/task-3e1-report.md`

### Fix-wave self-review / concern

No consumer or test-fixture source was edited. The `349` review count is not
reproducible from the authoritative live skeleton on this branch: its derived
`test_fixture` identity set contains 449 IDs (240 in
`test_graph_projection_queries.py`, 101 in `test_graph_projections.py`, and
108 elsewhere). The exact-once assertion deliberately uses the mechanically
derived set rather than silently dropping 100 sites.

## Final authoritative reconciliation (second review fix wave)

The final counts are intentionally distinct:

```text
raw fresh skeleton test_fixture IDs:       449
checked-in ledger still-unclassified IDs: 349
compiled raw-stream coverage:             449 / 449 exactly once
compiled deferred-ledger coverage:        349 / 349 exactly once
```

The 349 set is loaded from the existing
`scripts/codemods/graph_projection_query_migration.yaml` unclassified ledger,
then mechanically reconciled as a subset of the fresh raw skeleton before its
exact-once stream assertion. It is not a historical or unreproducible count.

Diagnostic anchors now retain both `normalized_source_pattern` (the
site-key identity pattern) and `normalized_cst_expression` plus node type (the
selected-node proof). Placeholder evidence is rejected during anchoring.
Operation classification separates `map_get` and `nested_get`, recognizes
current method shapes including update/append/extend/items/values/keys/pop and
setdefault, and derives diagnostics from their anchored CST operation rather
than a diagnostic-code-only fallback.

Verification:

```text
$ uv run pytest tests/unit/test_migrate_graph_projection_queries.py \
    tests/unit/test_graph_projection_inventory.py -q
109 passed in 104.20s

$ uv run ruff format scripts/graph_projection_inventory.py \
    scripts/codemods/migrate_graph_projection_queries.py \
    tests/unit/test_migrate_graph_projection_queries.py
1 file reformatted, 2 files left unchanged

$ uv run ruff check scripts/graph_projection_inventory.py \
    scripts/codemods/migrate_graph_projection_queries.py \
    tests/unit/test_migrate_graph_projection_queries.py
All checks passed!

$ uv run pyright
0 errors, 0 warnings, 0 informations

$ uv run pytest
4993 passed, 3 skipped, 3 warnings in 213.91s
```

Second-wave self-review: the raw and deferred sets are separately derived and
asserted; no source consumer or fixture was edited; unknown diagnostic
operations and parent structures continue to fail closed; frozen diagnostic
evidence provides both source identity and CST proof fields.
