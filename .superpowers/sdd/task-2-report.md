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

### Task 2a review follow-up

#### RED evidence

Strengthened the deterministic fixture test with the exact 25-event type
sequence and a SHA-256 signature of the complete JSON-normalized event stream.
Before supplying the expected signature, the focused test failed as intended:

```text
AssertionError: '90297431aed70b324d374bb89f99b573844c633b270466bbc0d4e278c62680af' == ''
```

#### GREEN implementation

- Physically removed the dormant FR-17 routine, run setup, seed, event,
  decision-request, and event-builder helpers from the acceptance module,
  along with their imports.
- Changed shared-fixture imports to the public `orchestrator.config` and
  `orchestrator.state` APIs.
- Locked stream event ordering and complete normalized event content with the
  deterministic signature assertion.

#### Verification evidence

```console
uv run pytest tests/unit/test_graph_fr17_fixture.py \
  tests/integration/test_graph_fr17_acceptance.py -v
uv run ruff check tests/graph_fr17_fixture.py \
  tests/unit/test_graph_fr17_fixture.py \
  tests/integration/test_graph_fr17_acceptance.py
uv run pyright tests/graph_fr17_fixture.py \
  tests/unit/test_graph_fr17_fixture.py \
  tests/integration/test_graph_fr17_acceptance.py
```

Result: focused tests `2 passed in 3.70s`; Ruff passed; Pyright reported
`0 errors, 0 warnings, 0 informations`.

```console
uv run pytest
```

Result: `4952 passed, 3 skipped, 3 warnings in 118.29s`; warnings remain the
existing Python 3.12 `aiosqlite` datetime-adapter deprecations.

## Task 2b — Complete FR17 public goldens and canonical check

### RED evidence

1. Added canonical JSON check coverage before its implementation and ran:

   ```console
   uv run pytest tests/unit/test_graph_projection_goldens.py -q
   ```

   The focused test failed at collection because `canonical_json` was not yet
   exported by the generator.

2. Replaced the integration parity assertion with an independent HTTP read of
   all FR-17 public surfaces through an in-memory SQLite app and reran:

   ```console
   uv run pytest tests/integration/test_graph_projection_public_parity.py -q
   ```

   It failed with the expected `KeyError: 'fr17_complete'` because the prior
   public golden only contained the selected invariant corpus presenter views.

### GREEN implementation

- The public golden generator now creates one explicit
  `fr17-public-golden` graph run, seeds the reviewed shared FR-17 fixture via
  its real SQLite `GraphEventStore` helper, and reads the complete public
  contract through actual FastAPI router requests.
- `public_view_goldens.json` now includes run detail, graph projection, full
  events, topology, scheduler, decisions, patches, regions, final blockers,
  recovery-node detail, and review-node detail. Replay goldens were not
  regenerated or changed.
- The integration test independently creates and seeds the same real SQLite
  state and independently issues every public request; it imports only the
  shared fixture, never generator selection or presentation helpers.
- Normalization occurs only after router response construction and is limited
  to the documented volatile run transport fields: `created_at`, `updated_at`,
  generated step ID, and generated task ID.
- `canonical_json()` is the sole golden serializer (sorted two-space JSON plus
  a terminal newline). `--check` now performs exact byte-text comparison,
  reports every mismatched path with a bounded unified diff, and does not
  write. Focused tests cover success plus key-order, indentation, and missing
  terminal-newline drift.
- Updating generator line positions required regenerating the existing
  line-sensitive graph-projection inventory diagnostic fixture; its unresolved
  diagnostic count and contents are otherwise unchanged.

### Verification evidence

```console
uv run python scripts/generate_graph_projection_goldens.py --write
uv run python scripts/generate_graph_projection_goldens.py --check
uv run pytest tests/unit/test_graph_projection_goldens.py \
  tests/unit/test_fixture_corpus.py \
  tests/integration/test_graph_projection_public_parity.py \
  tests/integration/test_graph_fr17_acceptance.py -q
uv run ruff check scripts/generate_graph_projection_goldens.py \
  tests/unit/test_graph_projection_goldens.py \
  tests/integration/test_graph_projection_public_parity.py
uv run pyright scripts/generate_graph_projection_goldens.py \
  tests/unit/test_graph_projection_goldens.py \
  tests/integration/test_graph_projection_public_parity.py
uv run pytest
```

Results: focused tests `14 passed in 4.06s`; Ruff passed; Pyright reported
`0 errors, 0 warnings, 0 informations`; full suite passed with `4955 passed,
3 skipped, 3 warnings in 116.64s`. The three warnings are the existing Python
3.12 SQLite datetime-adapter deprecations from `aiosqlite`.
