# W5 Slice Brief - Decision Events

## Scope

Event family: appeals and decisions.

Events:
- `appeal_opened`
- `approval_decision_recorded`
- `authority_decision_recorded`
- `oversight_decision_recorded`

Producers are `_apply_raise_appeal` and `_apply_record_decision` in
`src/orchestrator/graph/_commands.py`. Reducer consumption is in `reduce_event`
and its appeal/latest-decision/gate/authority helpers in
`src/orchestrator/graph/projections.py`.

## Payload Contract and Compatibility

`AppealOpenedPayload` preserves optional run/node/appeal/candidate/task/lease
identifiers plus `appeal_type` and `membership`. The three decision payloads
preserve the shared decision identifiers, aliases (`decision`, `outcome`,
`verdict`, `approved`), task/gate/appeal/candidate metadata, expiry/reason,
record identifier, `membership`, and deliberately opaque `decider` and
`scope` values.

Legacy `membership.task_region_id` and `membership.candidate_id` supply absent
top-level identifiers. Legacy decision aliases normalize to the compatible
canonical decision for each projection. Unknown top-level keys are retained in
one `extra` mapping. A legacy oversight event may omit `node_id`; it remains
replayable for appeal/block resolution even though it cannot populate the
latest-decision map. `decider` and `scope` remain intentionally flexible.

## Acceptance Tests

- `test_appeal_opened_payload_normalizes_membership_and_patch_extras`
- `test_decision_payloads_normalize_legacy_outcome_verdict_and_approved`
- `test_decision_payloads_preserve_opaque_decider_scope_and_unknown_extra`
- `test_decision_reducers_preserve_legacy_appeal_and_invalid_test_behavior`
- `test_decision_producers_emit_typed_payloads`
- `test_sparse_oversight_decision_without_node_id_remains_replayable`

## Boundaries

This slice does not alter decision-command validation, decision projection
schemas, event history, or opaque decision metadata. It only establishes typed
event models, producer validation/JSON dumps, and typed reducer parsing while
preserving current replay behavior.
