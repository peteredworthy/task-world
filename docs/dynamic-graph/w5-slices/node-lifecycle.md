# Node lifecycle payload slice

## Scope

Type the remaining node-lifecycle event envelopes: `node_state_changed`,
`node_retired`, `node_ready`, `node_deferred`, `node_authority_changed`, and
the replay-only suspect aliases (`plan_region_marked_suspect`,
`node_marked_suspect`, `plan_region_suspect_resolved`, `node_suspect_resolved`,
`plan_region_suspect_cleared`, `node_suspect_cleared`). `node_created` is
already typed and is explicitly out of this slice.

## Compatibility contract

- Preserve reducer keys: state/node id/attempt number, including the legacy
  `membership.attempt_number` fallback; deferral reason; authority claims,
  actions and preconditions, including nested `authority` fallback; and all
  suspect node/region id aliases plus reason.
- Use fixed typed fields and one inherited `extra` dictionary only. Normalize
  malformed or unknown historic top-level values into `extra` rather than
  rejecting durable event history.
- Keep current producer payloads model-validated and JSON-dumped. Parse every
  covered reducer event (including replay aliases) through its typed model.

## Files and acceptance

Touch `models.py`, `__init__.py`, `_commands.py`, `projections.py`, and the
new focused test. Do not type `command_definition`, diagnostics/read-set data,
record payload/provenance, edge policy/metadata, or decision scope/decider.
No projection schema bump is expected because state shape is unchanged.

The focused test covers normalization, membership and authority fallbacks,
suspect aliases, reducer use, and producer validation. It must first fail with
the expected missing payload-model export, then pass along with corpus parity,
allowlist/projection tests, graph tests, Ruff, and Pyright.

## RED evidence

`uv run pytest tests/unit/test_node_lifecycle_event_payloads.py -q` failed
during collection as expected: `ImportError: cannot import name
'NodeAuthorityChangedPayload' from 'orchestrator.graph'`.

Verifier follow-up RED: the focused suite failed with Pydantic validation on
`NodeStateChangedPayload.model_validate({"retry_not_before": 3})`; malformed
`retry_not_before` and `prompt_summary` values now normalize under `extra`.
