# Task 3f Report: Close Diagnostics, Freeze Inventory, and Install Boundary Guard

## Implementation summary

- Added report-linkage validation to `graph_projection_inventory.py`. It reads the canonical JSON report, refuses malformed/stale/missing closure evidence, requires every historical collector identity to have exactly one sorted finite report disposition, and preserves raw current diagnostics as provenance while reporting zero unresolved flows.
- Added deterministic `--write-baseline` and `--check` modes. The committed transformed-source `access_inventory.json` records the sorted current inventory, source digests, and the closure linkage proof.
- Added the exact five-file `ALLOWED_STORAGE_READERS` boundary guard. It rejects typed legacy literal/dynamic projection subscripts, mutable projection operations, grouped-storage access outside the exact allowlist, and external graph-submodule imports.
- Updated the small remaining production external graph imports to the public `orchestrator.graph` API without changing diagnostic-artifact source line positions.

## TDD evidence

RED:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py::test_report_linkage_resolves_every_historical_diagnostic_without_erasing_raw_evidence -q
ImportError: cannot import name 'validate_report_linkage'
```

```text
uv run pytest tests/unit/test_graph_projection_boundaries.py -q
ModuleNotFoundError: No module named 'scripts.check_graph_projection_boundaries'
```

GREEN:

```text
uv run pytest tests/unit/test_graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py -q
111 passed in 7.89s
```

## Generated counts and command evidence

```text
uv run python scripts/graph_projection_inventory.py --diagnose
Raw collector diagnostics: 749
Unresolved GraphProjection flows: 0

uv run python scripts/graph_projection_inventory.py --write-baseline
exit 0

uv run python scripts/graph_projection_inventory.py --check
exit 0

uv run python scripts/check_graph_projection_boundaries.py
exit 0
```

```text
uv run pytest tests/unit/test_graph_projection_inventory.py tests/unit/test_migrate_graph_projection_queries.py tests/unit/test_graph_projection_boundaries.py tests/unit/test_graph_projection_queries.py tests/unit/test_callbacks.py tests/unit/test_patch_validator.py -q
312 passed in 9.46s

uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/integration/test_graph_fr17_acceptance.py -q
137 passed in 5.87s

uv run ruff check . && uv run ruff format --check .
All checks passed; 751 files already formatted

uv run pyright
0 errors, 0 warnings, 0 informations

make test-graph-projection-migration
11 passed, 3802 deselected in 239.22s

make test
5103 passed, 3 skipped, 3 warnings in 93.72s
```

## Files changed

- `scripts/graph_projection_inventory.py`
- `scripts/check_graph_projection_boundaries.py`
- `tests/fixtures/graph_projection_migration/access_inventory.json`
- `tests/unit/test_graph_projection_inventory.py`
- `tests/unit/test_graph_projection_boundaries.py`
- `src/orchestrator/graph/__init__.py`
- `src/orchestrator/graph_runtime/controller.py`
- `src/orchestrator/graph_runtime/prompts.py`
- `src/orchestrator/graph_runtime/seeding.py`
- `src/orchestrator/workflow/graph_driver.py`

## Self-review and concerns

- Verified the historical diagnostic artifact remains unmodified and the explicit migration gate proves it still matches fresh collection byte-for-byte.
- The baseline manifest remains `49e3f3bb03502530e52abb7304c5a31ecc5d4340`, matching the canonical report.
- No concerns. The three full-suite warnings are the pre-existing Python 3.12 `aiosqlite` datetime-adapter deprecations.

## Boundary-guard provenance review (uncommitted)

### RED/GREEN

```text
RED
uv run pytest tests/unit/test_graph_projection_boundaries.py::test_boundary_guard_uses_source_order_and_lexical_provenance -q
FAILED: the module-global AST expression fixed point reported the pre-binding and lexically isolated aliases.

RED
uv run pytest tests/unit/test_graph_projection_boundaries.py::test_boundary_guard_rejects_nested_storage_mutations_and_mutating_dunders -q
FAILED: __setitem__ was not recognized as a mutating dunder.

GREEN
uv run pytest tests/unit/test_graph_projection_boundaries.py tests/unit/test_graph_projection_inventory.py -q
120 passed in 5.68s
```

### Architecture

- Replaced the failed module-global AST expression fixed point with `projection_provenance()` in `graph_projection_inventory.py`.
- The API reuses the collector's LibCST scope, ordered bindings, approved-origin, annotated-return, bounded-alias, and typed attribute tracking. It emits separate position-keyed provenance facts and does not alter `AccessOccurrence` identities.
- The boundary guard continues to use AST for storage-shaped syntax and import shapes, but asks the shared LibCST provenance API whether the exact source expression is definite or possible GraphProjection provenance.

### Commands and results

```text
uv run ruff format --check scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
3 files already formatted

uv run ruff check scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
All checks passed

uv run pyright scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
0 errors, 0 warnings, 0 informations
```

### Changed files

- `scripts/graph_projection_inventory.py`
- `scripts/check_graph_projection_boundaries.py`
- `tests/unit/test_graph_projection_boundaries.py`
- `.superpowers/sdd/task-3f-report.md`

### Blocking concern

`uv run python scripts/check_graph_projection_boundaries.py` now scans all tracked Python files as required and correctly reports pre-existing external graph-submodule imports across 20+ test modules plus existing legacy fixture accesses in `test_graph_projections.py`, `test_lifecycle_event_payloads.py`, and `test_graph_outbox_crash_points.py`. Clearing them requires migrating those broad consumers/fixtures through public graph/fixture APIs and likely extending `orchestrator.graph` exports. That conflicts with this bounded subtask's instruction to commit only boundary/provenance/test/report files and not manually edit broad consumers. No current-report identity binding or suppression was added.

## Boundary-guard cycle-time optimization (uncommitted)

### Profiling and root cause

The reproducible baseline used the exact full command, with `/usr/bin/time -p`:

```text
uv run python scripts/check_graph_projection_boundaries.py
real 149.33
```

An instrumented run (diagnostics only; normal guard output is unchanged) found:

```text
tracked_files: 764
AST parse: 0.910s
storage-shaped files / provenance-analyzed files: 634 / 634
LibCST provenance: 143.933s
AST visitor: 0.747s
violations: 48
violation SHA-256: 3d037a6466ca18f0672fdb79669e049a39cf3c7d88dd051dea155acbc5ad68b9
```

The root cause was confirmed: the old storage-shape predicate treated ubiquitous ordinary mapping/list operations (`[]`, `.append`, `.update`, `.pop`, etc.) as reasons to run the complete LibCST metadata collector.  It therefore analyzed 634 of 764 files even when no collector-supported GraphProjection provenance could originate in the file.

### RED / GREEN

```text
RED
uv run pytest tests/unit/test_graph_projection_boundaries.py::test_boundary_provenance_candidate_selection_uses_only_collector_seed_origins -q
ImportError: cannot import name 'has_projection_provenance_seed'

GREEN
uv run pytest tests/unit/test_graph_projection_boundaries.py tests/unit/test_graph_projection_inventory.py -q
121 passed in 5.34s
```

The deterministic regression test proves a source containing only generic mapping mutation is not a provenance candidate. It also proves candidates remain enabled for every finite collector seed family: `GraphProjection` annotation (including aliases), all approved producers (including aliases), producer holders (`GraphController` and `GraphEventStore`), and both typed holder origins (`GraphDispatchContext` and `GraphProjectionCheckpoint`).

### Implementation and measured result

- `projection_provenance_seed_tokens()` derives terminal candidate tokens from the collector's own finite approved type, producer, producer-holder, and typed-holder origin tables. It is not based on variable naming or policy exemptions.
- The guard still AST-parses and visits every tracked Python file, including malformed-source failure and graph-submodule-import checks. It invokes LibCST provenance only for storage-shaped files containing a collector-derived seed token. Tokenization errors fail conservatively by retaining provenance analysis.
- The remaining independent provenance runs are dispatched through at most eight process workers. `executor.map` preserves input order, and results are reattached by relative path before the existing sequential AST visitor, so output ordering and provenance facts remain deterministic.

The exact full command after the change, on the unchanged measured worktree, completed in:

```text
uv run python scripts/check_graph_projection_boundaries.py
real 13.75
```

Post-change instrumentation:

```text
tracked_files: 764
AST parse: 1.843s
storage-shaped files / provenance-analyzed files: 634 / 112
LibCST provenance wall time (8 workers): 10.021s
AST visitor: 0.757s
violations: 48
violation SHA-256: 3d037a6466ca18f0672fdb79669e049a39cf3c7d88dd051dea155acbc5ad68b9
```

This is a 149.33s → 13.75s exact-command improvement (about 10.9×), below the requested 30-second practical edit-loop target. The violation count and canonical rendered violation hash are identical to baseline; no violations were suppressed or exempted.

### Focused verification and concerns

```text
uv run ruff check scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
All checks passed

uv run ruff format --check scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
3 files already formatted

uv run pyright scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
0 errors, 0 warnings, 0 informations
```

Concern: the parallel portion deliberately uses process workers because the LibCST metadata work is CPU-bound; this increases peak process/memory use for large scans. It is limited to eight workers, skipped for fewer than four candidates, and worker failure propagates rather than silently weakening the guard. Existing reported violations remain intentionally unresolved under this task's scope.

## Final migration completion

- The mechanical public-import migration reduced the boundary guard from **48 to 0** violations. The canonical current closure is **750** sites with exact sorted identity/digest evidence in `query_migration_report.json`.
- RED/GREEN: focused migration tests initially exposed the removed full-report recipe variables; restoring full-mode composition/replacement/fixture compilation made **245** inventory/migration/boundary tests pass. The full migration gate then exposed incomplete public exports; the facade now exports each mechanically migrated symbol.
- Fast `--assert-clean` intentionally loads no historical tree and compiles no transformation plans. Its fresh inventory and per-source anchoring use bounded process workers while preserving the full stream exactly. Isolated timing: **21.98s** (previously 105.43s). Boundary guard timing: **13.62s**, zero violations.
- Regenerated the report with `--apply`; `--assert-clean`, inventory diagnose/write-baseline/check, and the boundary guard passed. The historical diagnostic artifact remains unchanged and migration coverage now checks it against the manifest baseline bytes rather than the intentionally transformed current inventory.
- Final files include the codemod fast closure path, parallel inventory collection, public graph facade exports, transformed consumers, canonical migration report/inventory, and migration coverage. No concerns beyond the bounded process-worker peak memory noted above.

## Independent-review correctness fixes (uncommitted)

### Root cause and RED/GREEN

Review found three independent gaps in the initial provenance boundary:

1. `_known_projection_value()` understood `cst.Await`, but no `visit_Await()` recorded the outer expression position that the AST boundary visitor receives.
2. Possible aliases were recorded only at exact `Name` positions; their Attribute/Subscript/Await wrappers consequently did not have source-position facts for nested stores or mutation receivers.
3. The explicit mutator table missed mapping `popitem`, set `difference_update`, and several required attribute/in-place dunders.

```text
RED
uv run pytest tests/unit/test_graph_projection_boundaries.py::test_boundary_guard_tracks_direct_awaited_producer_access tests/unit/test_graph_projection_boundaries.py::test_boundary_guard_tracks_possible_alias_nested_and_grouped_mutations tests/unit/test_graph_projection_boundaries.py::test_boundary_guard_rejects_complete_explicit_mutator_policy -q
9 failed, 19 passed

GREEN
same focused command
28 passed
```

The awaited test is an end-to-end direct `(await controller.read_projection())["run_state"]` access. The control-flow test assigns either a typed projection or unrelated object, then checks both nested assignment and grouped descendant mutation. The parameterized real-source mutator test covers the complete reviewed mapping, sequence, set, and dunder method union.

### Implementation

- Added `visit_Await()` provenance recording. The fact uses the real LibCST `Await` position rather than a name/string heuristic.
- Added `_possible_projection_derived()` for the same bounded `Await`, `Attribute`, and `Subscript` wrapper chain supported by definite provenance. This preserves the collector's existing lexical bindings and source-order semantics while providing independent boundary facts at each outer receiver/store expression.
- Made `_projection_derived()` include `Await` wrappers for symmetric definite handling.
- Split the finite mutator policy into explicit mapping, sequence, set, and in-place-dunder tables and unioned them. The policy now includes `popitem`, `difference_update`, `__setattr__`, `__delattr__`, `__imul__`, `__iand__`, and `__ixor__` alongside the previously covered methods.

### Verification and remeasurement

```text
uv run pytest tests/unit/test_graph_projection_boundaries.py tests/unit/test_graph_projection_inventory.py -q
149 passed in 6.05s

uv run ruff check scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
All checks passed

uv run ruff format --check scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
3 files already formatted

uv run pyright scripts/check_graph_projection_boundaries.py scripts/graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py
0 errors, 0 warnings, 0 informations

/usr/bin/time -p uv run python scripts/check_graph_projection_boundaries.py
real 14.99
```

Candidate instrumentation remained stable: all 764 tracked Python files AST-parse, 634 are storage-shaped, and only 112 enter LibCST provenance. The full guard count was **48 before review fixes and 48 after**. No newly discovered repository violation was emitted because the repaired awaiting/possible-alias/method shapes occur in focused adversarial tests rather than in tracked broad-scan sources; existing violation output was otherwise unchanged. The 14.99-second full command remains below the 30-second target.

### Concerns

Possible provenance remains deliberately bounded to the collector's existing control-flow alias facts and its finite wrapper forms; it does not infer arbitrary transformations. The unchanged process-worker cap, deterministic `map` order, all-file AST/import scan, exact storage allowlist, and malformed-source fail-closed behavior remain in effect. The known 48 broad-scan violations are still outside this task's migration scope.

## Final Task 3f completion

### Facade collision fix

- The public facade continues to expose the Pydantic `ResourceClaim` unchanged and now exports the scheduler dataclass as `SchedulerResourceClaim`.
- The LibCST import rewrite keys its public-name rename on the original submodule origin. A scheduler `ResourceClaim` therefore becomes `SchedulerResourceClaim`; when no local alias was supplied, the codemod preserves the consumer's local binding with `as ResourceClaim`.
- RED/GREEN coverage exercises simultaneous model/scheduler `ResourceClaim` imports with aliases and comments, proves their distinct facade symbols, and checks the unaliased scheduler local-binding case. The scheduler test consumer was restored to its original scheduler import and regenerated with the codemod, yielding `SchedulerResourceClaim as ResourceClaim` rather than a manual broad consumer edit.

### Migration-test cleanup

- Removed generated site-total, disposition-distribution, and rule-family-count snapshots from the migration gate. The historical ledger is now checked as a finite, unique reviewed catalog; current closure uses an empty historical ledger and structural compilation, matching the production current-closure path.
- The live invariants now prove: exact disjoint consumed/deferred/pending partitioning of known current IDs; unique consumed operation IDs; no pending, deferred, generated-fixture, or query-transform work at closure; approved-core rows satisfy the exact finite core predicate; projection-neutral rows have structural reasons and finite rules; all stored summary Counters equal independently recomputed Counters; and independently constructed current closure evidence has the same identity as both the live closure and canonical report.
- This permits legitimate generated-site drift after artifact regeneration while still failing missing, duplicate, unclassified, or policy/rule drift.

### Final focused evidence before lint/type/full-suite gate

```text
uv run pytest tests/unit/test_migrate_graph_projection_queries.py tests/unit/test_scheduler.py tests/unit/test_graph_models.py tests/unit/test_graph_projection_inventory.py tests/unit/test_graph_projection_boundaries.py -q
407 passed in 7.51s

make test-graph-projection-migration
11 passed, 3845 deselected in 205.01s

/usr/bin/time -p uv run python -m scripts.codemods.migrate_graph_projection_queries --assert-clean
query migration assert-clean passed: 750 sites
real 22.96s

inventory --diagnose / --write-baseline / --check
Raw collector diagnostics: 745; unresolved flows: 0
real 35.81s / 36.41s / 34.70s

/usr/bin/time -p uv run python scripts/check_graph_projection_boundaries.py
exit 0 (zero violations), real 13.75s

uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/integration/test_graph_fr17_acceptance.py -q
137 passed in 5.15s

uv run ruff format . && uv run ruff check . && uv run pyright
1 file reformatted; all checks passed; 0 errors, 0 warnings, 0 informations

make test
5146 passed, 3 skipped, 3 aiosqlite datetime-adapter deprecation warnings in 98.98s
```
