# Task 11 Canonical Event Payloads Design

## Scope

Type the final two canonical graph events missing from the payload registry:
`agent_dispatch_requested` and `command_recorded`. Historical sparse shapes are
not supported, and `lease_suspended` remains modeled external ingress.

## Contracts

`AgentDispatchRequestedPayload` is a strict event payload with required
`lease_granted_event_id`, `lease_id`, `node_id`, `generation`, `execution_id`,
`base_snapshot_id`, and `resource_claims` fields. Scalar values use strict
types. Resource claims reuse the existing strict nested
`ResourceClaimProjection` contract.

`CommandRecordedPayload` is a strict event payload with required
`command_type: str` and `command_payload: dict[str, Any]`. The command body is
the only dynamic boundary; flattened command fields and compatibility aliases
are rejected.

Both models are exported through `orchestrator.graph`, registered in
`EVENT_PAYLOAD_MODELS`, and receive explicit projection, light, summary, and
node-detail retention sets. Canonical event names and payload model keys must
be exactly equal, including the already modeled external `lease_suspended`.

## Producer Flow

The command event serializer becomes a public graph API while retaining its
single policy table and validation guard. The graph runtime controller and
scenario harness call that API before constructing an `EventEnvelope`, so
their persisted payloads are validated and JSON-safe under the same policy as
command-factory events.

The scenario harness records commands as:

```json
{"command_type": "schedule_tick", "command_payload": {"base_snapshot_id": "S0"}}
```

Scenario expectations and fixture corpus entries are updated to this canonical
shape. No consumer alias or fallback reads the former flattened shape.

## Verification

Tests first establish registry coverage failure, then cover strict unknown and
wrong-type rejection, canonical producer JSON, and compact/full payload parity
for both events where they enter persisted reads. Focused registry, payload,
scenario, controller, corpus, allowlist, and read tests run before the full
suite, Ruff, Pyright, and repository hooks.
