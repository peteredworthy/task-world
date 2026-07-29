# Task 3e Report: Atomic Graph Projection Migration Codemod

## Status

Complete. The codemod deterministically compiles the historical baseline and
current-tree closure in memory, reports every anchored historical site exactly
once, and writes only the validated canonical report during `--apply`.

## Generated evidence

- Baseline revision: `49e3f3bb03502530e52abb7304c5a31ecc5d4340`.
- Historical report: 542 sites — 354 `transformed` and 188
  `projection_neutral`; there are no unaccounted or rejected sites.
- Current closure: 754 sites (5 physical occurrences in approved core files,
  749 diagnostics), with 136 `approved_core` and 618
  `projection_neutral` dispositions. No generated query recipe, mutation
  handoff, fixture mutation, pending ID, or deferred ID remains.
- The canonical generated artifact is
  `tests/fixtures/graph_projection_migration/query_migration_report.json`.
  `access_inventory.json` was neither written nor frozen.

## TDD and recovery evidence

- RED: `test_query_migration_report_links_nested_physical_diagnostic_to_outer_recipe`
  failed because a typed physical diagnostic nested in its enclosing CST recipe
  could not be linked to that recipe.
- GREEN: the report now links a physical diagnostic only through matching typed
  physical provenance and a unique enclosing recipe span; the focused test and
  all 84 codemod tests pass.
- RED: `test_query_migration_report_transforms_physical_mapping_update_diagnostic`
  failed because a direct physical mapping read in an `update` diagnostic was
  incorrectly left neutral and had no generated recipe.
- GREEN: the existing typed literal-read query rule now permits diagnostic
  `update` shapes, producing `node_states_view(projection)` mechanically; the
  focused test and all 84 codemod tests pass.
- The explicit migration gate initially exposed the expected-count impact of
  the existing structural `projection_cast` rule (nine sites); its exact
  structural-count assertion was updated and the gate passed.

## Verification

- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py -q` —
  84 passed.
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py tests/unit/test_graph_projection_inventory.py tests/unit/test_graph_projection_queries.py tests/unit/test_graph_public_exports.py -q` — 218 passed.
- `uv run python -m scripts.codemods.migrate_graph_projection_queries --apply` — passed: 542 sites.
- `uv run python -m scripts.codemods.migrate_graph_projection_queries --assert-clean` — passed: 754 sites.
- `uv run python -m scripts.codemods.migrate_graph_projection_queries --check` — passed: 542 sites; `git status --porcelain` was byte-for-byte unchanged before and after.
- `make test-graph-projection-migration` — 11 passed.
- `uv run ruff check .` — passed; `uv run ruff format --check .` — 749 files already formatted.
- `uv run pyright` — 0 errors, 0 warnings, 0 informations.
- `make test` — 5,092 passed, 3 skipped (three pre-existing Python 3.12 SQLite deprecation warnings).

## Files changed

- `scripts/codemods/migrate_graph_projection_queries.py`
- `scripts/graph_projection_inventory.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `tests/unit/test_graph_projection_migration.py`
- `tests/fixtures/graph_projection_migration/query_migration_report.json`
- `.superpowers/sdd/task-3e-report.md`

## Self-review and concerns

- Reviewed staged and unstaged recovery changes together, preserved the
  structural-rule architecture, and removed only the unintended staged scratch
  plan/spec index residue.
- No consumer call sites were manually edited. The report linkage fails closed
  on absent or ambiguous enclosing recipes, and current closure proves a
  byte-identical second run.
- No blocking concerns.

## Review-fix wave (post-`cebde009814a46f70134dcbeba130bbf44b26f56`)

### Independent finding evaluation

- **`--apply` source writes:** kept. `compile_current_source_apply_plans`,
  `apply_source_updates_in_memory`, and `write_repository_migration_apply`
  compile non-overlapping query/fixture changes in memory, validate every
  original source and report byte before replacement, then atomically write the
  source set and canonical report. The mode test proves `--check` does not
  write and `--apply` writes the transformed source as well as the report.
- **Representable `rejected` dispositions:** kept. The report row schema now
  represents a mechanically rejected site, while the planner still raises on
  unknown or ambiguous structural shapes; the unit test constructs the valid
  rejected row and the existing refusal tests remain green.
- **Imported-only `typing.cast` provenance:** kept. Inventory accepts only a
  single `QualifiedNameProvider` import-origin fact for `typing.cast`; a local
  shadow remains unclassified and aborts, as covered by the shadowed-cast test.
- **Statement-context `after_form`:** corrected. The earlier implementation
  tried to parse a site fragment and substitute a recipe's outer expression at
  the fragment anchor. This duplicated generator bodies and failed for compound
  outer expressions. `MigrationSite.report_context` now captures the enclosing
  simple statement or structural compound header; query recipes replace their
  normalized outer expression within that context. Fixture recipes are
  statement replacements and are rendered directly rather than parsed as
  expressions.

### Generator-fragment RED/GREEN and root cause

- Reproduction: `uv run python -m scripts.codemods.migrate_graph_projection_queries --apply`
  failed with `report site has an unparseable normalized context` for historical
  site `d9009aed…`. The site is the generator fragment
  `state in {...} for state in projection["node_states"].values()`, whereas
  assignments, returns, and compound-header occurrences provide parseable
  statement context.
- RED: the generator statement-context assertion failed with a nested
  `any(... for state in any(...))`; the compound outer-expression assertion
  failed because the direct subscript fragment did not contain the replacement
  recipe's boolean outer expression; the fixture report assertion failed when
  a statement replacement was parsed as an expression.
- Root cause: report rows mixed three CST granularities (physical anchor,
  outer query action, and fixture statement) but used the physical site's
  normalized text as if it were always the outer expression's enclosing
  statement.
- GREEN: source-derived structural statement/header context plus recipe outer
  identity produces `return any(...node_states_view...)` and full transformed
  compound headers; fixture statements render directly. No context-specific
  string fallback was added.

### Final commands and output

- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py -q` —
  **93 passed**.
- `uv run python -m scripts.codemods.migrate_graph_projection_queries --apply`
  — **passed: 542 sites**.
- `uv run python -m scripts.codemods.migrate_graph_projection_queries --assert-clean`
  — **passed: 754 sites**.
- `make test-graph-projection-migration` — **11 passed, 3,800 deselected**.
- `uv run ruff check ...` and `uv run ruff format --check ...` — passed.
- `uv run pyright scripts/codemods/migrate_graph_projection_queries.py scripts/graph_projection_inventory.py tests/unit/test_migrate_graph_projection_queries.py`
  — **0 errors, 0 warnings, 0 informations**.

### Changed files and concerns

- `scripts/codemods/migrate_graph_projection_queries.py`
- `scripts/graph_projection_inventory.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `tests/fixtures/graph_projection_migration/query_migration_report.json`
- `.superpowers/sdd/task-3e-report.md`

No blocking concerns. The report artifact was regenerated by `--apply`; no
consumer call sites were manually edited.
