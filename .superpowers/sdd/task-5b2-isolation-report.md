# Task 5b2: FrozenMap And Projected-Record Isolation

## Scope completed

- Restricted direct `FrozenMap` construction to no input, an exact `dict`, or an
  exact existing `FrozenMap`. Persistent updates use a module-private backend
  construction path and continue to preserve old/new generations without
  exposing backend or transient mutation APIs.
- Kept Pydantic validation at the dictionary boundary for both dictionaries and
  existing maps, including generic key/value validation, model-child
  reconstruction, mutable-input isolation, and ordinary JSON serialization.
- Enabled projection-model instance revalidation so map-held projection models,
  nested models, and untrusted subclasses are reconstructed and invalid
  preconstructed children are rejected. Existing frozen envelope maps pass
  through the field pre-validator and are then revalidated by their declared
  generic schema.
- Expanded every explicit projected-record semantic matrix row with mutable
  source children. Each row now checks JSON/public-adapter parity, recursively
  rejects mutable containers and source models, exercises public model/map/tuple
  mutation failures, mutates the accepted source model's child containers after
  projection, and confirms projected type, value, and JSON remain unchanged.
- Added the Task 4 review minor proving separate `thaw_json` calls return fresh
  mutable trees isolated from each other and from the frozen source.

## TDD evidence

- Constructor boundary tests first failed in three cases: `UserDict` and
  `MappingProxyType` did not raise the required `TypeError`, and construction
  from an existing `FrozenMap` failed.
- Projection child tests first failed because an untrusted `NodeProjection`
  subclass was retained and an invalid preconstructed nested child was accepted.
- The enriched 22-row record matrix then exposed revalidation of already-frozen
  envelope maps through `freeze_json`; the safe existing-map pre-validation path
  fixed this while leaving the declared `FrozenMap` schema responsible for full
  child validation and reconstruction.

## Focused verification

- `uv run pytest tests/unit/test_graph_projection_collections.py tests/unit/test_graph_projected_records.py tests/unit/test_graph_projection_models.py tests/unit/test_output_record_event_payloads.py tests/unit/test_graph_public_exports.py -q`
  — 170 passed in 5.98s.
- `uv run ruff check` on the two production and three focused test files — passed.
- `uv run ruff format --check` on the same files — passed.
- `uv run pyright` on the same files — 0 errors, warnings, or informations.

## Concerns

None. Projection instance revalidation deliberately reconstructs trusted exact
instances as well as subclasses at validation boundaries; reducers still share
already-validated frozen projection instances between generations rather than
revalidating during cloning.
