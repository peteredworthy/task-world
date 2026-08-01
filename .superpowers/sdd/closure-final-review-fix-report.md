# Immutable Graph Projection Final-Review Fix Report

## Scope

Applied the complete final whole-branch review fix wave at clean head
`2f163c66f8a3ca492018f5193eaf6a4d4f837ea1`. `progress.md` was not modified.

## RED evidence

Added end-to-end boundary regressions for `from orchestrator import graph`,
its alias spelling, and both projection-producing public-module star imports.
Before the provenance implementation, the focused boundary run failed exactly
as intended:

```text
FAILED test_boundary_guard_tracks_package_imported_graph_module_without_sibling_broadening
  assert [] == [(6, 'forbidden_grouped_storage_access'), ...]
FAILED test_boundary_guard_fails_closed_for_public_projection_star_import
  assert [] == [(1, 'projection_public_star_import'), ...]
2 failed
```

The flexible-JSON matrix test was extended before verification to assert the
live frozen value, the encoded checkpoint value, and declared omitted-vs-null
field presence. Its existing implementation already preserved all 29 fields ×
6 probes, so its first complete run was green rather than exposing a product
defect.

## GREEN evidence

```text
uv run pytest tests/unit/test_graph_projection_boundaries.py -q
138 passed in 2.79s

uv run pytest tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_flexible_json.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_integrity.py \
  tests/unit/test_graph_projection_boundaries.py \
  tests/unit/test_graph_projection_performance.py -q
1067 passed in 10.57s

uv run python scripts/check_graph_projection_boundaries.py
exit 0 (no violations)

uv run ruff format --check <changed Python files>
8 files already formatted

uv run ruff check <changed Python files>
All checks passed!

uv run pyright <changed Python files>
0 errors, 0 warnings, 0 informations
```

## Files changed

- `scripts/graph_projection_boundary_provenance.py`
- `scripts/check_graph_projection_boundaries.py`
- `tests/unit/test_graph_projection_boundaries.py`
- `tests/unit/test_graph_projection_flexible_json.py`
- `tests/unit/test_graph_projection_queries.py`
- `src/orchestrator/graph/projection_models.py`
- `src/orchestrator/graph/projection_codec.py`
- `tests/unit/test_graph_projection_replay_equivalence.py`
- `AGENTS.md`
- `.superpowers/sdd/closure-final-review-fix-report.md`

## Commit evidence

Pending normal `git commit` hooks at the time this report was written. The
resulting non-amended commit SHA and hook result are recorded in the final
work summary.
