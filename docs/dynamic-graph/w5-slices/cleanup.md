# W5 Slice Brief - Cleanup Events

## Scope

Event family: cleanup.

Events:
- `cleanup_requested`
- `cleanup_applied`

Inventory source: `docs/dynamic-graph/w5-event-payload-inventory.md`.

## Payload Keys

`cleanup_requested` producer-written keys:
- `cleanup_id`, `file_state_record_id`, `snapshot_id`, `paths`, `authority`,
  `reason`, `execution_id`, `producer_node_id`

`cleanup_requested` reducer-read keys:
- Same fields used to build the cleanup-request projection, plus event
  `position`.

`cleanup_applied` producer-written keys:
- `cleanup_id`, `file_state_record_id`, `superseding_record_id`,
  `old_snapshot_id`, `new_snapshot_id`, `paths`, `authority`, `reason`,
  `execution_id`, `deleted_snapshot_ref`

`cleanup_applied` reducer-read keys:
- `cleanup_id`, `file_state_record_id`, `superseding_record_id`,
  `deleted_snapshot_ref`

Nested/free-form notes:
- `paths` is a list of path strings.
- `authority` may be flexible policy metadata. If it is not already typed by an
  existing model, keep it under one `extra: dict[str, Any]` field or preserve
  existing behavior with legacy normalization.

## Files To Touch

Expected:
- `src/orchestrator/graph/models.py` or a new event-payload module if the slice
  establishes that pattern for W5. Decide once in this slice and keep it
  consistent for later slices.
- `src/orchestrator/graph/_commands.py`
- `src/orchestrator/graph/projections.py`
- Focused unit tests, likely in `tests/unit/test_graph_projections.py` or a new
  dedicated cleanup payload test.
- `docs/dynamic-graph/w5-progress-ledger.md`

Avoid:
- Command payload typing.
- Patch `ops` / `macro_invocations`.
- Provider-specific `command_definition`.
- Edge `metadata` / policy fields.
- `TypedRecordBase.payload` / `provenance`.

## Acceptance Criteria

- `cleanup_requested` and `cleanup_applied` parse through typed Pydantic event
  payload models before reducer consumption.
- Legacy event-log shapes still replay without raising.
- Producer emission validates through the same typed models.
- Reducer consumption uses typed attributes for this family rather than raw
  `payload.get(...)` access.
- The Phase 0 corpus replay parity test remains green.
- Targeted tests name the cleanup legacy/tolerance behavior.

## Verification

Minimum commands:
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
- Cleanup-focused unit tests added by the slice.
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py -q`
- `uv run ruff check src/orchestrator/graph tests/unit`
- `uv run pyright src/orchestrator/graph tests/unit`
