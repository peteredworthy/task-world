# W5 Planner / Session Payload Slice

## Scope

Event family: planner/session.

Typed events:
- `session_state_changed`

Planner-chain fields carried by `node_created` are intentionally out of scope for
this slice because `node_created` belongs to the larger node lifecycle family.

## Payload Keys

`session_state_changed` current producer keys:
- `session_id`: string identifier.
- `state`: string lifecycle state.
- `node_id`: string planner node identifier.
- `lease_generation`: optional integer generation. Reducers do not currently
  read it, but store/detail allowlists preserve it.
- `carryover_record_id`: optional string record identifier. Reducers read it for
  session carryover projection, and it is not currently in the store allowlists.

Legacy compatibility:
- Unknown top-level keys must be preserved under `extra`.
- Non-string `session_id`, `state`, `node_id`, and `carryover_record_id` values
  should not fail old event replay; move invalid values under `extra`.
- Non-integer `lease_generation` should be moved under `extra`.

## Files To Touch

- `src/orchestrator/graph/models.py`
- `src/orchestrator/graph/__init__.py`
- `src/orchestrator/graph/_commands.py`
- `src/orchestrator/graph/projections.py`
- `tests/unit/test_planner_session_event_payloads.py`
- `docs/dynamic-graph/w5-progress-ledger.md`

## Acceptance Criteria

- Add a Pydantic payload model for `session_state_changed` following the cleanup
  payload house style.
- Route the current producer through the typed payload model.
- Route reducer consumption through typed parsing instead of raw payload dict
  reads for `session_state_changed`.
- Preserve legacy replay by normalizing invalid/unknown top-level fields into
  `extra`.
- Keep `node_created` planner-chain payloads untouched.
- Verify with a focused unit test, corpus replay parity, graph projection tests,
  graph suite, `ruff check .`, and targeted pyright.
