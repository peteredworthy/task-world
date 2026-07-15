# W5 Final Event Payload Inventory

**Status:** Final catalog inventory; Task 14 independently verified

This inventory supersedes the pre-cutover survey of `_commands.py`, raw
`make_event(...)` calls, legacy aliases, and four payload-field allowlists. The
authoritative live surface is now the immutable catalog composed by
`build_graph_catalog()` from domain-owned `EVENT_SPECIFICATIONS` tuples. The
generated Task 14 measurement reports exactly **44 event specifications** and
**23 command specifications**, with zero unclassified dynamic event/command
sites.

Every event payload is a frozen, strict, `extra="forbid"` Pydantic model.
Producers create `HydratedEvent` values through the owning specification;
storage serializes a generation-2 `StoredEventEnvelope`; reads resolve and
hydrate through the injected catalog exactly once; reducers receive the
concrete payload model. No current event is routed through a central event-name
conditional or a raw dictionary reducer.

## Events By Owner

| Domain module | Live event specifications |
|---|---|
| `graph/events/lifecycle.py` | `run_lifecycle_changed`, `command_rejected`, `callback_accepted`, `callback_rejected_stale`, `callback_rejected_conflict`, `callback_duplicate_returned`, `runtime_retry_scheduled`, `heartbeat_recorded`, `agent_died`, `agent_dispatch_requested` |
| `graph/events/records.py` | `output_record_accepted`, `verification_passed`, `verification_failed` |
| `graph/events/topology.py` | `node_created`, `node_state_changed`, `node_retired`, `node_ready`, `node_deferred`, `node_authority_changed`, `plan_region_marked_suspect`, `edge_created`, `input_bound`, `session_state_changed`, `dead_input_detected`, `revision_created` |
| `graph/events/leases.py` | `lease_granted`, `lease_renewed`, `lease_released`, `lease_revoked`, `lease_expired` |
| `graph/events/patches.py` | `graph_patch_accepted`, `graph_patch_rejected` |
| `graph/events/decisions.py` | `appeal_opened`, `approval_decision_recorded`, `authority_decision_recorded`, `oversight_decision_recorded` |
| `graph/events/requirements.py` | `requirement_revision_recorded`, `support_evidence_recorded` |
| `graph/events/file_state.py` | `file_state_accepted`, `file_state_rejected`, `gatekeeper_verdict_recorded`, `gatekeeper_cost_recorded`, `cleanup_requested`, `cleanup_applied` |

## Projection Participation

The following 12 events are explicitly `ProjectionParticipation.NEUTRAL`:

`command_rejected`, `callback_rejected_stale`,
`callback_rejected_conflict`, `callback_duplicate_returned`,
`heartbeat_recorded`, `agent_died`, `agent_dispatch_requested`,
`output_record_accepted`, `dead_input_detected`, `revision_created`,
`file_state_rejected`, and `gatekeeper_cost_recorded`.

Neutral means the specification's graph reducer does not mutate
`GraphProjection`; it does not bypass typed architecture. These events use the
same specification creation, generation-2 storage, one-time hydration, catalog
coverage, and corruption checks as projection-mutating events. Some also feed
separate typed records or audit/read-model paths.

The other 32 specifications are explicitly projection-mutating. Their reducers
are owned beside their payload specifications and consume concrete model
instances.

## Commands By Owner

| Domain module | Live command specifications |
|---|---|
| `graph/commands/lifecycle.py` | `accept_run`, `start`, `pause`, `resume`, `cancel`, `complete`, `fail`, `record_heartbeat`, `agent_died` |
| `graph/commands/callbacks.py` | `acknowledge_start`, `submit_callback`, `raise_appeal`, `record_decision`, `record_requirement_revision`, `record_support_evidence` |
| `graph/events/topology.py` | `seed_compiled_events` |
| `graph/commands/schedule.py` | `schedule_tick`, `reconcile` |
| `graph/commands/patches.py` | `submit_patch` |
| `graph/commands/records.py` | `evaluate_join`, `evaluate_final_gate` |
| `graph/commands/file_state.py` | `record_gatekeeper_verdicts`, `record_cleanup_applied` |

## Deleted Compatibility Surface

Deferred Compatibility Cleanup Register rows D1-D6 were deleted by Task 13 at
`e63fb41ec`. Retired names such as `lease_suspended`,
`graph_patch_proposed`, `requirement_revision_proposed`,
`authority_resolution_recorded`, `environment_failure_accepted`, and
`check_result_classified` are neither live specifications nor current reducer
branches. `reduce_legacy_event` and the hidden generation-1 adapters are also
deleted. The exact register grep exited 1 with no output.

Source repairs `b63146d9b` and `0289de70c` subsequently removed the legacy graph
effects adapter and enforced typed production consumers without a payload JSON
adapter. The final catalog remains 44/23 and all measured compatibility metrics
remain zero.

The former store/read allowlists
`GRAPH_PROJECTION_PAYLOAD_FIELDS`, `LIGHT_GRAPH_PAYLOAD_FIELDS`,
`SUMMARY_REBUILD_PAYLOAD_FIELDS`, and `NODE_DETAIL_PAYLOAD_FIELDS` are deleted.
Full, light, summary-rebuild, projection/checkpoint, and node-detail reads carry
complete hydrated payloads instead of reconstructing subsets.

## Maintenance Rule

- Add or change a payload field in its domain model and behavior tests.
- Add an event beside its payload model, reducer, and domain specification tuple.
- Add a command beside its payload model, handler, and domain specification tuple.
- Never add a central event/command conditional or a storage/read field list.

Catalog composition, serialization, hydration, schema generation, and generic
contract coverage follow from the specification.
