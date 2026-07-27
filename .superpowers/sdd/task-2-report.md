# Task 2 — Capture Replay and Public-View Oracles

## Scope

Captured deterministic, checked-in behavior oracles before the query-boundary
codemod. The generator consumes the checked-in YAML graph scenario corpus and
persists representative public-view scenarios through real in-memory SQLite
before serializing the public presenter contracts.

## RED evidence

1. Added `tests/unit/test_graph_projection_goldens.py` before the generator or
   JSON fixtures existed.
2. Ran:

   ```console
   uv run pytest tests/unit/test_graph_projection_goldens.py -v
   ```

3. Observed the expected missing-generator collection failure:

   ```text
   ModuleNotFoundError: No module named 'scripts.generate_graph_projection_goldens'
   ```

4. After adding the generator but before generating the checked-in fixtures,
   reran the test and observed the expected missing-golden failures:

   ```text
   FileNotFoundError: .../replay_goldens.json
   FileNotFoundError: .../public_view_goldens.json
   ```

## GREEN implementation

- `scripts/generate_graph_projection_goldens.py` exposes the required
  `build_replay_goldens()` and `build_public_view_goldens()` functions plus
  `--write` and `--check` CLI modes.
- Replay goldens cover sorted YAML scenarios and capture full and incremental
  replay, checkpoint round trip, topology, scheduler, node metadata, planner,
  verification, governance, recovery, records, and public presenter outputs.
- Public-view goldens use a real SQLite `GraphEventStore` before calling the
  public graph presenter builders. The integration test independently repeats
  that SQLite persistence/readback path and compares its presenter bodies to
  the checked-in oracle.
- JSON is canonical (`sort_keys=True`, indented, terminal newline), scenario
  keys are sorted, and all exposed graph imports use `orchestrator.graph`.
- Added the migration oracle entry to `tests/fixtures/graph/COVERAGE.md`.

## Verification evidence

```console
uv run python scripts/generate_graph_projection_goldens.py --write
uv run python scripts/generate_graph_projection_goldens.py --check
uv run pytest tests/unit/test_graph_projection_goldens.py -v
```

Result: `2 passed in 2.80s` after the fixtures were generated.

```console
uv run ruff check scripts/generate_graph_projection_goldens.py \
  tests/unit/test_graph_projection_goldens.py \
  tests/integration/test_graph_projection_public_parity.py \
  src/orchestrator/api/__init__.py
```

Result: `All checks passed!`

```console
uv run pytest tests/unit/test_graph_projection_goldens.py \
  tests/unit/test_fixture_corpus.py \
  tests/integration/test_graph_projection_public_parity.py \
  tests/integration/test_graph_fr17_acceptance.py -q
```

Result: `11 passed in 4.54s`.

```console
uv run pytest
```

Result: `4951 passed, 3 skipped, 3 warnings in 117.79s`.

The three warnings are existing Python 3.12 SQLite datetime-adapter
deprecations from `aiosqlite`; no test failed.

## Task 2a — Deterministic FR-17 fixture extraction

### RED evidence

Added `tests/unit/test_graph_fr17_fixture.py` before the shared support module
existed, then ran:

```console
uv run pytest tests/unit/test_graph_fr17_fixture.py -v
```

The test failed at collection with the expected missing-module error:

```text
ModuleNotFoundError: No module named 'tests.graph_fr17_fixture'
```

### GREEN implementation

- Added `tests/graph_fr17_fixture.py`, a test-support module containing the
  FR-17 routine, graph-run creation and seeding helpers, event builder,
  decision-request value helper, and complete less-used event stream.
- Event IDs are now stable (`fr17-event-<position>`), timestamps are fixed at
  `2026-01-01T00:00:00+00:00`, and every envelope receives the explicit
  caller-provided run ID.
- The FR-17 acceptance test now creates and seeds its run through the shared
  module while retaining its API assertions and real SQLite setup.
- Added a focused deterministic fixture test that compares independently built
  streams, event-ID order, timestamps, and run-ID propagation.

### Verification evidence

```console
uv run pytest tests/unit/test_graph_fr17_fixture.py \
  tests/integration/test_graph_fr17_acceptance.py -v
```

Result: `2 passed in 3.92s`.

```console
uv run ruff check tests/graph_fr17_fixture.py \
  tests/unit/test_graph_fr17_fixture.py \
  tests/integration/test_graph_fr17_acceptance.py
uv run pyright tests/graph_fr17_fixture.py \
  tests/unit/test_graph_fr17_fixture.py \
  tests/integration/test_graph_fr17_acceptance.py
```

Result: Ruff reported `All checks passed!`; Pyright reported `0 errors, 0
warnings, 0 informations`.

```console
uv run pytest
```

Result: `4952 passed, 3 skipped, 3 warnings in 120.46s`. The warnings are the
existing Python 3.12 `aiosqlite` datetime-adapter deprecations.
