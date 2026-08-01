# Task 7 Performance Benchmark Report

## Delivered tooling

- `scripts/benchmark_graph_projection.py` builds deterministic general,
  edge-heavy, and record-heavy corpora from real `EventEnvelope` instances and
  measures the current reducer, checkpoints, public views, memory, append-tail
  index updates, and persistent-primitive scaffold operations.
- `tests/fixtures/graph_projection_performance/scenarios.json` is canonical,
  checked scenario metadata. The corpus SHA-256 is emitted from canonical event
  JSON for every requested size set.
- The CLI implements `--sizes`, `--warmups`, `--runs`, `--baseline`,
  `--write-baseline`, and `--check-gates`. Its output includes host/OS/Python/
  dependency metadata, API maximum-count status, units, medians, and sources.
- Gate diagnostics are deterministic and metric-specific. Production gate runs
  (`--runs >= 2`) enforce replay 1.15, normalized per-event scale 2.5,
  memory 1.15, checkpoint 1.0 (including record-heavy strict-smaller),
  codec/view 1.25, and cold rebuild 1.15.

## 100-event smoke measurement

Command:

```text
uv run python scripts/benchmark_graph_projection.py --sizes 100 --warmups 1 --runs 1
```

Runtime: **0.908 seconds** wall clock on macOS 26.5.1 / arm64 / Python 3.12.12.
The local API was unavailable, reported explicitly as
`{"count": null, "source": "api", "status": "unavailable"}`; no network or
production payload was required.

Representative measured checkpoint sizes were general 7,015 bytes,
edge-heavy 16,955 bytes, and record-heavy 2,157 bytes. These are smoke values,
not a committed production baseline.

## Verification

```text
uv run pytest tests/unit/test_benchmark_graph_projection.py -q
7 passed in 8.16s

uv run ruff check scripts/benchmark_graph_projection.py tests/unit/test_benchmark_graph_projection.py
All checks passed!

uv run ruff format --check scripts/benchmark_graph_projection.py tests/unit/test_benchmark_graph_projection.py
2 files already formatted

uv run pyright scripts/benchmark_graph_projection.py tests/unit/test_benchmark_graph_projection.py
0 errors, 0 warnings, 0 informations
```

## Deferred production baseline

Per task instruction, this implementation did **not** run the expensive
`100, 1000, 10000` / `2 warmups` / `7 runs` baseline. Therefore
`tests/fixtures/graph_projection_performance/baseline.json` is intentionally
not committed here. The controller should generate the immutable pre-cutover
baseline after review with:

```text
uv run python scripts/benchmark_graph_projection.py --sizes 100 1000 10000 --warmups 2 --runs 7 --write-baseline
```

The single-run subprocess smoke path deliberately rejects zero/synthetic
thresholds while not treating ordinary timing noise as a performance
regression; full production gate ratios apply at two or more measured runs.
