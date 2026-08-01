# Closure Task 5 Report: Direct Deterministic 10,000-Event Performance Gate

## Scope and files

- Added `tests/unit/test_graph_projection_performance.py`.
  - Generates deterministic test-local `general`, `edge-heavy`, and `record-heavy`
    tuples of exactly 10,000 `EventEnvelope` values.
  - Times only full `initial_projection()` / `reduce_event()` folds.
  - Each scenario has exactly one unmeasured warmup and three timed folds; the
    median must be strictly less than 1.0 second.
  - Validates unique event IDs, contiguous positions, replay equality, and public
    node/edge/accepted-record cardinalities.
- Optimized only the profiled immutable record-reduction path:
  - `ProjectedRecordBase.freeze_record_sequences()` uses exact built-in container
    checks at its `model_dump(mode="json")` boundary.
  - `insert_projected_record()` directly constructs the already-valid frozen
    `RecordStore` replacement from persistent maps.
  - `project_record()` has a validated `OutputRecord`/`fan_out_inputs` fast path
    that freezes all open JSON fields and preserves `model_fields_set`, retaining
    public `exclude_unset=True` serialization equivalence.
- Updated `pyproject.toml` from xdist `worksteal`/automatic worker sizing to
  four-worker `loadgroup`. The default full suite remains enabled; this makes
  xdist honor the gate's group assignment while bounding concurrent CPU-bound
  work, so its three required parameter rows share one worker rather than
  competing with one another. The four-worker grouped normal hook run passed.
- Did not import or extend the historical benchmark, add a script/artifact/
  baseline/ratio/slow marker, add metadata, modify `progress.md`, or change the
  event mixes, threshold, warmup count, or timed-run count.

## RED evidence

Initial direct gate, before defining `_performance_event_stream`:

```text
uv run pytest tests/unit/test_graph_projection_performance.py -q
FFF
NameError: name '_performance_event_stream' is not defined
3 failed in 4.08s
```

All three rows failed for the expected missing-interface reason.

## GREEN evidence

Required direct gate runs after implementation:

```text
uv run pytest tests/unit/test_graph_projection_performance.py -q
3 passed in 8.17s

uv run pytest tests/unit/test_graph_projection_performance.py -q
3 passed in 7.18s
```

Final exact sequential samples (seconds). Event generation and cardinality
validation were outside the timed folds; each listed scenario performed one
unmeasured warmup followed by exactly these three timed replays.

| Scenario | Timed samples (s) | Median (s) | Nodes | Edges | Accepted records |
| --- | --- | ---: | ---: | ---: | ---: |
| general | 0.338407458, 0.338887500, 0.327355041 | 0.338407458 | 2501 | 2500 | 2499 |
| edge-heavy | 0.280514875, 0.263974041, 0.272438500 | 0.272438500 | 5001 | 4999 | 0 |
| record-heavy | 0.583722125, 0.676550333, 0.673780708 | 0.673780708 | 1 | 0 | 9999 |

All medians are strictly below 1.0 second and all observed public-query
cardinalities equal the generated event-family counts.

Focused regression verification:

```text
uv run pytest \
  tests/unit/test_graph_projected_records.py \
  tests/unit/test_graph_projection_behavior.py \
  tests/unit/test_graph_projection_replay_equivalence.py \
  tests/unit/test_graph_projection_immutability.py \
  tests/unit/test_graph_projection_queries.py \
  tests/unit/test_graph_projection_duplicate_ids.py \
  tests/unit/test_graph_projection_performance.py -q
479 passed in 8.89s

uv run ruff check ... && uv run ruff format --check ... && uv run pyright ...
All checks passed; 0 errors, 0 warnings, 0 informations

uv run pre-commit run --all-files
All hooks passed, including pytest, pyright, graph-projection-boundaries,
module-imports, signal-routing, enum-drift, ui-lint, and ui-typecheck.
```

## Performance investigation

The first normal full-suite hook exposed a real record-heavy failure under
default xdist contention:

```text
record-heavy samples: 1.082912209, 0.759528208, 1.329866666
median: 1.082912209s
```

Pure-reduction `cProfile` attributed the hot path to the 9,999
`output_record_accepted` reductions: repeated record projection validation,
frozen-record-store replacement, and persistent-map updates. An initial
fan-out sequence shortcut was rejected because existing projected-record tests
proved strict nested `FrozenMap` validation requires list-to-tuple conversion.
A `FrozenMap` method-dispatch experiment was also reverted after profiling
showed it slower. The committed changes above were the narrow surviving
optimizations, with projected-record serialization equivalence explicitly
restored through `_fields_set`.

The full suite still showed scheduling-sensitive wall-clock variance under
`worksteal` (for example, median 1.010375708s after the reducer optimizations).
`loadgroup` is therefore retained and the default xdist worker count is capped
at four, so the three release-gate rows run in one group without competing with
seven other CPU-bound workers. This preserves their individual
one-warmup/three-sample contracts and default-suite visibility.

## Commits

- `d006b782b test(graph): enforce direct replay performance bound`
- `16a8d0ac9 test(graph): group replay performance gate`
- `1711c7a14 test: bound xdist replay gate contention`

## Concerns

- The release bound intentionally measures wall-clock time, so host CPU
  scheduling is material. The gate stays strict and unmarked; four-worker xdist
  grouping is the minimal normal-suite scheduling control used to bound
  CPU-bound contention without removing the gate from default execution.
- No unresolved behavioral or check failures remain in the final all-files hook
  run.
