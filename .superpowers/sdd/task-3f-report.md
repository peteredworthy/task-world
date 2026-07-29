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
