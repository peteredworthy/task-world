# W5 Typed Payloads Progress Ledger

Seed branch: `main`
Seed SHA: `bd41b5b24756fec7441cbfd0ee150739b9afede7`
Work branch: `codex/w5-typed-payloads`

## Phase 0 - Corpus Replay Parity Safety Net

Status: complete in working tree, pending commit.

Changes:
- Added a corpus-level replay parity test over the graph YAML fixtures.
- Fixed compact summary rebuild payload extraction so checkpoint replay matches
  full event replay for the current fixture corpus.

Verification:
- `uv run pytest tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py -q`
  - Result: passed, 11 tests.
- `uv run pytest tests/integration/test_graph_read_models.py tests/integration/test_graph_event_store.py -q`
  - Result: passed, 26 tests.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_graph_payload_field_allowlists.py -q`
  - Result: passed, 131 tests.
- `uv run ruff check tests/unit/test_fixture_corpus.py src/orchestrator/graph_runtime/store.py`
  - Result: passed.
- `uv run pyright tests/unit/test_fixture_corpus.py src/orchestrator/graph_runtime/store.py`
  - Result: passed, 0 errors.

Notes:
- No typed payload migration work has started.
- The safety net must remain green before any event-family slice begins.

## Phase 1 - Event Payload Inventory

Status: complete in working tree, pending commit.

Artifact:
- `docs/dynamic-graph/w5-event-payload-inventory.md`

Notes:
- Surveyed `_commands.py` producer `make_event(...)` sites, confirmed
  `compiler.py` has no `make_event(` sites, and grouped reducer-consumed event
  payloads into implementation families.
- No production code or test changes were made for the inventory.

## Cleanup Event Payload Slice

Status: complete in working tree, pending commit.

Scope:
- Added typed event payload models for `cleanup_requested` and
  `cleanup_applied` in `src/orchestrator/graph/models.py`.
- Routed gatekeeper `cleanup_requested` producer emission and
  `record_cleanup_applied` producer emission through those payload models.
- Routed cleanup projection reducer consumption through typed payload models
  instead of raw `event.payload.get(...)` access.

Legacy normalization:
- `authority` remains a typed string field for current producer behavior.
- Legacy non-string `authority` values are moved under `extra["authority"]`.
- Legacy unknown top-level cleanup payload keys are moved under `extra`.
- `paths` is normalized to string entries only.

Dropped write-only keys:
- None. Legacy free-form top-level keys are preserved under `extra`.

RED:
- `uv run pytest tests/unit/test_cleanup_event_payloads.py -q`
  - Result: failed during collection with
    `ImportError: cannot import name 'CleanupAppliedPayload' from 'orchestrator.graph'`.

GREEN:
- `uv run pytest tests/unit/test_cleanup_event_payloads.py -q`
  - Result: passed, 4 tests.
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
  - Result: passed, 1 test.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_cleanup_event_payloads.py -q`
  - Result: passed, 142 tests.
- `uv run ruff check src/orchestrator/graph tests/unit`
  - Result: passed.
- `uv run pyright src/orchestrator/graph tests/unit`
  - Result: passed, 0 errors.
- `uv run pytest tests/ -k graph -q`
  - Result: passed, 837 tests.
- `uv run ruff check .`
  - Result: passed.
