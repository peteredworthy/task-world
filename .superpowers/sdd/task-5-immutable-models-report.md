# Task 5 — Immutable Grouped Projection Models

## Delivered

- Added the isolated `ImmutableGraphProjection` scaffold with the twelve approved
  groups. Production `GraphProjection`, reduction, queries, and checkpoint APIs
  remain unchanged.
- Added strict frozen `ProjectionModel` descendants and persistent `FrozenMap`
  defaults. `RecordStore.by_id` is the only full-record store; secondary record
  indexes retain IDs.
- Added frozen projected-record counterparts for every discriminator in
  `OUTPUT_RECORD_MODELS_BY_TYPE`, including all three gap aliases, and the
  discriminated `ProjectedRecord` union plus `project_record` boundary converter.
- Extended `FrozenMap` validation to accept a `Mapping` when nested immutable
  JSON values are revalidated, preserving persistent maps through Pydantic model
  boundaries.

## TDD evidence

Initial focused test execution failed during collection because the new public
exports did not yet exist. Subsequent RED/GREEN iterations caught persistent-map
revalidation and record-union round-trip failures before the converter and
discriminated union were completed.

## Verification

```text
uv run pytest tests/unit/test_graph_projection_models.py \
  tests/unit/test_graph_projected_records.py \
  tests/unit/test_output_record_event_payloads.py -q
74 passed

uv run pyright src/orchestrator/graph/projection_models.py
0 errors, 0 warnings, 0 informations

uv run ruff check … && uv run ruff format --check …
All checks passed; 4 files already formatted
```

## Scope and concerns

- This is intentionally an unused destination scaffold. There is no production
  cutover or compatibility path.
- `progress.md` was pre-modified with approved Task 4 progress and is deliberately
  left uncommitted as directed.
