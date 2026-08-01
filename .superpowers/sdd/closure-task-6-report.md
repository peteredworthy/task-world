# Task 6 Closure Report: Retire Migration-Only Assets

## Retirement inventory (RED)

The required tracked-file retirement inventory was run before any deletion. It
returned exit status 1 and listed the following tracked migration-only assets:

- `scripts/graph_projection_inventory.py`
- `scripts/generate_graph_projection_goldens.py`
- `scripts/codemods/migrate_graph_projection_queries.py`
- `scripts/codemods/graph_projection_manifest.yaml`
- `scripts/codemods/graph_projection_query_migration.yaml`
- `scripts/benchmark_graph_projection.py`
- `tests/unit/test_graph_projection_inventory.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `tests/unit/test_graph_projection_migration.py`
- `tests/unit/test_graph_projection_goldens.py`
- `tests/unit/test_graph_projection_test_speed.py`
- `tests/unit/test_benchmark_graph_projection.py`
- `tests/integration/test_graph_projection_public_parity.py`
- `tests/fixtures/graph_projection_migration/access_inventory.json`
- `tests/fixtures/graph_projection_migration/query_migration_report.json`
- `tests/fixtures/graph_projection_migration/public_view_goldens.json`
- `tests/fixtures/graph_projection_migration/replay_goldens.json`
- `tests/fixtures/graph_projection_performance/baseline.json`
- `tests/fixtures/graph_projection_performance/scenarios.json`
- `docs/graph-projection-inventory-diagnostics.md`

All listed paths were deleted. The retained query tests had their migration
imports, constants, and migration-disposition tests removed. The retained model
tests no longer read the manifest; their remaining current structural coverage
asserts direct `GraphProjection` and `NodeProjection` group contracts. The
readback profiler retains its local SQLite/API measurements but no longer
imports or measures the removed benchmark corpus.

## Active-reference retirement proof

The required active-surface search was run against `AGENTS.md`, `Makefile`,
`pyproject.toml`, `scripts`, `src`, `tests`, `docs/ARCHITECTURE.md`, and
`docs/dynamic-graph/graph-projection-map-inventory.md`:

```text
graph_projection_inventory|migrate_graph_projection_queries|
generate_graph_projection_goldens|benchmark_graph_projection|
graph_projection_migration|test-graph-projection-migration
```

It exited 1 with no matches after retirement. The post-deletion `git ls-files`
inventory also exited 0 with no retired paths. Historical documents under
`docs/superpowers/**` and `docs/dynamic-graph/complete/**` were neither changed
nor included in this active-surface proof.

## Documentation and commands

- Removed the migration Make target and pytest marker only; retained `slow`,
  `e2e`, LibCST, PyYAML, Hypothesis, pytest-testmon, and `uv.lock` unchanged.
- Updated active guidance to name canonical behavior, flexible JSON,
  every-split replay, direct performance, and the permanent boundary command.
- Updated architecture, map inventory, and graph fixture coverage references to
  point to executable schema-13 closure contracts.
- Kept the permanent boundary script and hook unchanged. The boundary check was
  run after staging the deletions because it intentionally scans `git ls-files`.

## Verification

| Command | Result |
|---|---|
| Focused closure suite (10 specified files) | `1063 passed in 12.55s` |
| Affected model and direct-performance tests | `30 passed in 10.53s` |
| Full `uv run pytest` | `5968 passed, 3 skipped, 3 warnings in 259.50s` |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | `758 files already formatted` |
| `uv run pyright` | `0 errors, 0 warnings, 0 informations` |
| `uv run python scripts/check_graph_projection_boundaries.py` (staged state) | Passed |
| `uv run pre-commit run --all-files` | All hooks passed |
| Cached diff whitespace check | Passed |

## Commit

This report is included with the Task 6 retirement commit:

```text
chore(graph): retire projection migration tooling
```

## Concerns

The first full-suite attempt exposed the deleted manifest as a dependency of
three retained model tests and saw one transient direct-performance sample
median over the strict limit under concurrent suite load. The model tests were
converted to direct current-model assertions, and the isolated direct
performance suite plus the subsequent full suite both passed. No remaining
concerns were observed.
