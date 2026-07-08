# W5 Slice Brief - Lease Events

## Scope

Event family: leases.

Events:
- `lease_granted`
- `lease_renewed`
- `lease_released`
- `lease_revoked`
- `lease_expired`
- `lease_suspended` replay compatibility only; no current producer found.

Related audit/runtime events that are out of reducer scope for this slice:
- `heartbeat_recorded`
- `agent_died`
- `runtime_retry_scheduled`

Inventory source: `docs/dynamic-graph/w5-event-payload-inventory.md`.

## Payload Keys

`lease_granted` producer-written keys:
- `lease_id`, `node_id`, `generation`, `execution_id`,
  `base_snapshot_id`, `expires_at`, `resource_claims`, optional
  `session_id`.
- Reducer derives fallback `task_region_id` and `kind` from existing node
  projection state when omitted.

`lease_renewed` producer-written keys:
- `lease_id`, `node_id`, `observed_at`, `expires_at`, optional
  `generation`, `execution_id`.

Terminal lease events:
- `lease_released`: `node_id`, `lease_id`, optional `generation`.
- `lease_revoked`: `lease_id`, `node_id`, optional `generation`,
  `execution_id`, `trigger`, `reason`.
- `lease_expired`: `lease_id`, `node_id`, `generation`, `execution_id`,
  `expires_at`, `reason`.
- `lease_suspended`: reducer compatibility event; type and consume as a
  terminal lease state if present in old logs.

Reducer-read keys:
- `lease_id` for all lease events.
- `lease_granted`: all typed lease projection fields plus fallback node-derived
  `task_region_id` and `kind`.
- `lease_renewed`: `node_id`, `generation`, `execution_id`, `expires_at`.
- Terminal events: currently only `lease_id` changes state, but typed models
  should preserve known metadata for compatibility and future allowlist
  derivation.

Nested/free-form notes:
- `resource_claims` is a nested list and already has typed projection models.
- Keep legacy unknown top-level keys under one `extra: dict[str, Any]` if
  accepted by event-log replay.
- `observed_at` is audit metadata and is not projection-read today.

## Files To Touch

Expected:
- `src/orchestrator/graph/models.py` for lease event payload models, unless a
  dedicated event-payload module is introduced consistently.
- `src/orchestrator/graph/_commands.py` for producer validation/dump.
- `src/orchestrator/graph/projections.py` for typed reducer consumption.
- `src/orchestrator/graph/__init__.py` if tests import payload models publicly.
- Focused unit tests, preferably `tests/unit/test_lease_event_payloads.py`.
- `docs/dynamic-graph/w5-progress-ledger.md`.

Avoid:
- Typing heartbeat, runtime retry, or agent death audit payloads in this slice.
- Changing lease scheduling semantics.
- Rewriting event history or changing durable event type names.

## Acceptance Criteria

- Lease reducer branches parse through typed Pydantic payload models before
  consumption.
- Current lease producers validate through the same typed models.
- Legacy malformed/partial lease events replay with the same skip/default
  behavior as today.
- Existing corpus replay parity remains green.
- Focused tests cover legacy unknown-key normalization, resource-claim
  tolerance, and terminal event state updates.

## Verification

Minimum commands:
- `uv run pytest tests/unit/test_lease_event_payloads.py -q`
- `uv run pytest tests/unit/test_fixture_corpus.py::test_fixture_corpus_replay_matches_checkpoint_and_compact_projection -q`
- `uv run pytest tests/unit/test_graph_projections.py tests/unit/test_fixture_corpus.py tests/unit/test_graph_payload_field_allowlists.py tests/unit/test_lease_event_payloads.py -q`
- `uv run ruff check src/orchestrator/graph tests/unit`
- `uv run pyright src/orchestrator/graph tests/unit`
