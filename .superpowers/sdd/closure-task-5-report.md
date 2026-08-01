# Closure Task 5 Report: Direct Deterministic 10,000-Event Performance Gate

## Scope

Task 5 closes the direct, deterministic 10,000-event graph-projection replay
gate and the associated projected-record conversion evidence.

- `tests/unit/test_graph_projection_performance.py` defines exactly three
  deterministic event mixes (`general`, `edge-heavy`, and `record-heavy`), each
  containing exactly 10,000 `EventEnvelope` values. Each row performs one
  unmeasured warmup and three timed full `initial_projection()` /
  `reduce_event()` folds; its median must be strictly below one second.
- The normal pytest configuration and the pytest pre-commit hook both use the
  same **two-worker `loadgroup`** contract. The three gate rows remain in the
  default test suite and execute as one xdist group.
- `tests/unit/test_graph_projected_records.py` now exercises fan-out replay
  only through public `orchestrator.graph` APIs: `reduce_event()`,
  `initial_projection()`, `output_record_payload()`,
  `projection_to_checkpoint()`, and `project_record()`. It neither imports nor
  exposes the internal reducer conversion helper.
- No production API and no `progress.md` content changed.

## Public and internal conversion contract

`project_record()` is the public conversion boundary. It always JSON-mode
serializes the source with aliases, excludes unset and `None` fields, and
validates the resulting data with the concrete projected destination model.
It therefore owns the public normalization and destination-validation
semantics.

The reducer first validates canonical `output_record_accepted` payload data.
Only after that validation, its private, non-exported helper may construct the
exact native `OutputRecord` fan-out shape directly. The helper preserves the
public destination field-presence behavior. It rejects non-native values,
subclasses, cycles, non-finite numbers, and JSON nesting deeper than 100, then
falls back to public `project_record()` conversion and destination validation.
The public API cannot invoke the private helper.

The checkpoint codec intentionally stores the Python field spelling `schema_`;
public record serialization uses the `schema` alias. This is an encoding-key
difference only: the reducer regression asserts the same public record field
presence and values, then asserts the canonical checkpoint equivalent.

## Reducer regression evidence

The new fan-out regressions are characterization tests added before any
test-support adjustment. The initial RED run exposed two assertion assumptions,
not a production mismatch: checkpoint records use canonical `schema_`, and the
depth guard applies to envelope JSON (`payload`/`provenance`), rather than the
unrestricted fan-out `value` destination. The tests were adjusted to those
existing public contracts; no production code changed.

1. Explicit `null` optionals together with explicit empty `value`, `payload`,
   `provenance`, and `file_state_record_ids` produce the same public
   serialization as `project_record()`. The public replay query and checkpoint
   preserve the empty fields while omitting the explicit-null optionals.
2. A native JSON `payload` nested beyond 100 levels makes `reduce_event()`
   fail with the same destination `ValidationError` type, location, and message
   as public `project_record()`, proving the private path falls back.
3. An `output_record_accepted` fan-out payload missing required `record_id`
   raises `ValidationError` during canonical event-payload model validation,
   before projection state changes.

```text
Initial new-test run (RED):
2 failed, 63 passed in 2.74s

Final reducer regression run:
65 passed in 2.58s

Focused projected-record / codec / duplicate / performance suite:
143 passed in 9.67s
```

## Current direct gate evidence

These runs used the exact committed reducer-test code in
`395856ed3 test(graph): add reducer conversion regressions` and the normal
two-worker `loadgroup` test configuration.

```text
uv run pytest tests/unit/test_graph_projection_performance.py -q
3 passed in 9.87s

uv run pytest tests/unit/test_graph_projection_performance.py -q
3 passed in 10.40s
```

The gate deliberately captures sample values for the strict median assertion
without emitting them on successful pytest runs. The following current samples
were recorded by executing that exact event-stream and replay contract (one
warmup plus three timed folds per scenario) against the same committed code:

| Scenario | Timed samples (s) | Median (s) |
| --- | --- | ---: |
| general | 0.332321375, 0.325648125, 0.322326167 | 0.325648125 |
| edge-heavy | 0.241088750, 0.246094500, 0.241276959 | 0.241276959 |
| record-heavy | 0.651302083, 0.657011916, 0.655356166 | 0.655356166 |

Every current median is strictly below one second.

## Historical samples and investigation

All earlier samples in prior versions of this report are **historical**, not
current evidence. They documented the original gate introduction and a
scheduling-sensitive record-heavy failure under a larger worker pool. The
two-worker `loadgroup` configuration is retained everywhere now as the narrow
normal-suite control for that CPU-bound contention; it does not remove,
relax, mark, baseline, or ratio-gate the direct release bound.

The historical profiling investigation identified repeated accepted-record
conversion and persistent record-store replacement as the record-heavy hot
path. A fan-out shortcut was retained only after public conversion semantics,
including `_fields_set`, JSON normalization, nested freezing, and destination
validation fallback were preserved. The current public reducer regressions
cover the remaining conversion edge cases without making the internal helper
public.

## Commits

- `d006b782b` `test(graph): enforce direct replay performance bound`
- `16a8d0ac9` `test(graph): group replay performance gate`
- `1711c7a14` `test: bound xdist replay gate contention`
- `7a6052017` `docs: record replay performance gate closure`
- `9de7facbb` `fix(graph): preserve projected record validation`
- `537d0ce27` `fix(graph): align reducer record field sets`
- `d3a724d68` `fix(graph): keep reducer fast path internal`
- `395856ed3` `test(graph): add reducer conversion regressions`

## Verification and concerns

The `395856ed3` commit ran normal hooks successfully: ruff, ruff format,
hardcoded-secret detection, pyright, graph-projection boundaries, the full
pytest hook, module-imports, signal-routing, enum drift, UI lint, and UI type
checking. This report update will run the same normal hooks before commit.

The remaining operational concern is expected wall-clock sensitivity to host
CPU contention. The direct assertion remains strict and unmarked, and both
current direct two-worker `loadgroup` runs passed. There are no unresolved
behavioral, validation, or hook failures.
