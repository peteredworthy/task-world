# Task 5b: Projected records and FrozenMap boundary

## Implemented boundary changes

- Replaced the generic projected-record `data` envelope with concrete frozen
  projected record classes and a public discriminated `ProjectedRecord` union.
- Preserved record envelope metadata, converted source mutable sequences at the
  projection boundary, and cached the public union adapter.
- Added the explicit candidate value contract and immutable `FrozenJsonValue`
  handling for flexible record payload fields.
- Consolidated the three gap tags into `ProjectedGapClassificationRecord`, with
  the canonical port pairing invariant (including the accepted classified-gap
  compatibility pairing).
- Narrowed `FrozenMap` external validation to exact `dict` input or existing
  `FrozenMap` revalidation; `UserDict` and mapping proxies are rejected.
- Exported the projected record interfaces through `orchestrator.graph`.

## Verification

Focused suite:

```text
uv run pytest tests/unit/test_graph_projection_collections.py \
  tests/unit/test_graph_projected_records.py \
  tests/unit/test_graph_projection_models.py \
  tests/unit/test_output_record_event_payloads.py \
  tests/unit/test_graph_public_exports.py -q
133 passed in 7.44s
```

Focused static checks:

```text
uv run ruff check …
All checks passed
uv run ruff format --check …
5 files already formatted
uv run pyright src/orchestrator/graph/projection_collections.py \
  src/orchestrator/graph/projection_models.py src/orchestrator/graph/__init__.py
0 errors, 0 warnings, 0 informations
```

## Scope note

The worktree's pre-existing `.superpowers/sdd/progress.md` remains deliberately
unstaged and uncommitted.
