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
- Public `project_record()` retains JSON-mode normalization and full destination
  validation; `freeze_record_sequences()` retains `isinstance` subclass
  normalization. Only the reducer helper may use the guarded
  exact-native fan-out construct path after payload validation.
- Both pytest defaults and the pre-commit pytest hook use two-worker
  `loadgroup`; the default full suite and all three grouped gate rows remain
  enabled.
- `project_validated_record_for_reducer()` is an internal sibling import used
  only by `projections.py`; it is not exported from `orchestrator.graph`.
- Its native-JSON guard mirrors `freeze_json` depth rejection (>100), so deep
  structures fall back to public normalization and validation.
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

## Semantic review follow-up

### RED

`tests/unit/test_graph_projected_records.py` added six failures against the
Task 5 public fast path:

- JSON-mode normalization for `date`, `datetime`, `UUID`, and enum values in
  fan-out value/payload/provenance raised before normalization.
- `OutputRecord.model_construct()` sources with `schema_version=0`, a mismatched
  `producer_port`, or a non-string `record_id` bypassed destination validation.
- An `OutputRecord` subclass with an extra field bypassed destination
  `extra="forbid"` validation.
- List and dict subclasses no longer normalized through the shared projected
  record validator.

### GREEN and fallback rationale

- Public `project_record()` is restored to its historical `model_dump(mode="json",
  by_alias=True, exclude_unset=True, exclude_none=True)` plus destination
  `model_validate()` path for every source, preserving normalization and all
  public validation semantics.
- `freeze_record_sequences()` again uses `isinstance` for list/dict subclasses.
- The reducer alone calls the non-exported internal
  `project_validated_record_for_reducer()`. Its trusted
  construct path requires the exact `OutputRecord` type, every destination
  scalar invariant (including schema version, port consistency, strict IDs, and
  list element types), and recursively native finite JSON with no cycles.
  Dates, datetimes, UUIDs, enums, subclasses, non-native container subclasses,
  and malformed constructed records fall back to public conversion.
- The private path is available only after reducer payload validation; the
  public API cannot reach it.

Verification after the review fixes:

```text
uv run pytest tests/unit/test_graph_projected_records.py \
  tests/unit/test_graph_projection_codec.py \
  tests/unit/test_graph_projection_duplicate_ids.py -q
137 passed in 3.40s

uv run pytest tests/unit/test_graph_projection_performance.py -q
3 passed in 8.98s

uv run pytest tests/unit/test_graph_projection_performance.py -q
3 passed in 8.91s

uv run pre-commit run pytest --all-files
Passed
```

The full hook initially overrode project pytest settings with eight-worker
`worksteal`; its entry now matches the grouped two-worker contract. Four workers
still produced record-heavy scheduling failures after private reduction
optimization, while two grouped workers passed the full default-suite hook.
