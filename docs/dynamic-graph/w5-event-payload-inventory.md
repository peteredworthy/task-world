# W5 Event Payload Inventory

Status: **closed 2026-07-16**; final-review contract corrections are recorded
without reopening W5.

This inventory is generated conceptually from the authoritative registries in
`event_registry.py` and `payload_registry.py`, not from an open-ended scan of
historical reducer aliases. The three key sets are exact and immutable:

- `CANONICAL_EVENT_TYPES`: 46 names.
- `EVENT_PAYLOAD_MODELS`: 46 names.
- `EVENT_PAYLOAD_SPECS`: 46 names.
- Internal ownership: 45 names across the command factory, runtime controller,
  and scenario harness. `lease_suspended` is the sole external-ingress name.

All canonical envelopes reject unknown top-level fields. The two flat
`RootModel` envelopes, `FileStateAcceptedPayload` and
`OutputRecordAcceptedPayload`, delegate strictness to their canonical record
roots. Runtime-only `agent_dispatch_requested` and `command_recorded` are
validated and JSON-dumped at their producer boundaries like every other
canonical event.

Accepted output records dispatch through the current 22-entry
`OUTPUT_RECORD_MODELS_BY_TYPE` map; no generic or legacy fallback remains.

`G/L/R/D` reports the per-event field count retained for graph projection,
light graph, summary rebuild, and node detail. The generated global allowlists
contain 105, 144, 160, and 92 sorted unique fields respectively.

| Event | Owner | Model | G/L/R/D |
|---|---|---|---:|
| `agent_died` | `graph_command_factory` | `AgentDiedPayload` | 5/5/5/5 |
| `agent_dispatch_requested` | `graph_runtime_controller` | `AgentDispatchRequestedPayload` | 7/7/7/7 |
| `appeal_opened` | `graph_command_factory` | `AppealOpenedPayload` | 9/9/10/9 |
| `approval_decision_recorded` | `graph_command_factory` | `ApprovalDecisionRecordedPayload` | 12/14/15/10 |
| `authority_decision_recorded` | `graph_command_factory` | `AuthorityDecisionRecordedPayload` | 12/14/15/10 |
| `callback_accepted` | `graph_command_factory` | `CallbackAcceptedPayload` | 4/5/7/5 |
| `callback_duplicate_returned` | `graph_command_factory` | `CallbackDuplicateReturnedPayload` | 4/5/7/5 |
| `callback_rejected_conflict` | `graph_command_factory` | `CallbackRejectedPayload` | 4/5/7/5 |
| `callback_rejected_stale` | `graph_command_factory` | `CallbackRejectedPayload` | 4/5/7/5 |
| `cleanup_applied` | `graph_command_factory` | `CleanupAppliedPayload` | 4/7/7/3 |
| `cleanup_requested` | `graph_command_factory` | `CleanupRequestedPayload` | 6/6/7/4 |
| `command_recorded` | `graph_scenario_harness` | `CommandRecordedPayload` | 2/2/2/2 |
| `command_rejected` | `graph_command_factory` | `CommandRejectedPayload` | 1/3/7/1 |
| `dead_input_detected` | `graph_command_factory` | `DeadInputDetectedPayload` | 4/4/4/4 |
| `edge_created` | `graph_command_factory` | `EdgeProjection` | 14/14/14/9 |
| `file_state_accepted` | `graph_command_factory` | `FileStateAcceptedPayload` | 12/12/16/12 |
| `file_state_rejected` | `graph_command_factory` | `FileStateRejectedPayload` | 13/13/17/13 |
| `gatekeeper_cost_recorded` | `graph_command_factory` | `GatekeeperCostRecordedPayload` | 2/11/11/1 |
| `gatekeeper_verdict_recorded` | `graph_command_factory` | `GatekeeperVerdictRecordedPayload` | 5/5/5/2 |
| `graph_patch_accepted` | `graph_command_factory` | `GraphPatchAcceptedPayload` | 2/4/5/1 |
| `graph_patch_rejected` | `graph_command_factory` | `GraphPatchRejectedPayload` | 1/3/5/1 |
| `heartbeat_recorded` | `graph_command_factory` | `HeartbeatRecordedPayload` | 5/5/5/5 |
| `input_bound` | `graph_command_factory` | `InputBoundPayload` | 9/9/9/7 |
| `lease_expired` | `graph_command_factory` | `LeaseExpiredPayload` | 6/6/6/6 |
| `lease_granted` | `graph_command_factory` | `LeaseGrantedPayload` | 10/10/10/10 |
| `lease_released` | `graph_command_factory` | `LeaseReleasedPayload` | 3/3/3/3 |
| `lease_renewed` | `graph_command_factory` | `LeaseRenewedPayload` | 5/5/5/5 |
| `lease_revoked` | `graph_command_factory` | `LeaseRevokedPayload` | 6/6/6/6 |
| `lease_suspended` | external ingress | `LeaseSuspendedPayload` | 5/5/5/5 |
| `node_authority_changed` | `graph_command_factory` | `NodeAuthorityChangedPayload` | 5/5/5/5 |
| `node_created` | `graph_command_factory` | `NodeCreatedPayload` | 49/49/50/48 |
| `node_deferred` | `graph_command_factory` | `NodeDeferredPayload` | 2/2/2/2 |
| `node_ready` | `graph_command_factory` | `NodeReadyPayload` | 1/1/1/1 |
| `node_retired` | `graph_command_factory` | `NodeRetiredPayload` | 2/2/2/2 |
| `node_state_changed` | `graph_command_factory` | `NodeStateChangedPayload` | 7/7/12/8 |
| `output_record_accepted` | `graph_command_factory` | `OutputRecordAcceptedPayload` | 19/21/27/18 |
| `oversight_decision_recorded` | `graph_command_factory` | `OversightDecisionRecordedPayload` | 12/14/15/10 |
| `plan_region_marked_suspect` | `graph_command_factory` | `NodeSuspectPayload` | 2/3/3/2 |
| `requirement_revision_recorded` | `graph_command_factory` | `RequirementRevisionPayload` | 5/22/23/4 |
| `revision_created` | `graph_command_factory` | `RevisionCreatedPayload` | 0/2/3/0 |
| `run_lifecycle_changed` | `graph_command_factory` | `RunLifecycleChangedPayload` | 9/10/10/9 |
| `runtime_retry_scheduled` | `graph_command_factory` | `RuntimeRetryScheduledPayload` | 6/6/6/6 |
| `session_state_changed` | `graph_command_factory` | `PlannerSessionStateChangedPayload` | 4/4/4/4 |
| `support_evidence_recorded` | `graph_command_factory` | `SupportEvidencePayload` | 3/9/10/2 |
| `verification_failed` | `graph_command_factory` | `VerificationFailedPayload` | 8/5/8/5 |
| `verification_passed` | `graph_command_factory` | `VerificationPassedPayload` | 8/5/8/5 |

## Removed Compatibility Surface

The canonical registry, producers, reducers, fixtures, and retention specs no
longer use replay aliases such as `environment_failure_accepted`,
`check_result_classified`, proposal lifecycle aliases, `requirement_amended`,
`support_edge_recorded`, or suspect resolved/cleared aliases. Their remaining
test occurrences are negative registry data. The fixture occurrence of
`environment_failure_accepted` is a diagnostic `trigger` value inside canonical
`node_state_changed`, not an event type.

Deleted compatibility models/helpers include `GraphEventPayloadBase.extra`,
`LeaseEventPayloadBase`, `LifecycleEventPayloadBase`, `LegacyOutputRecord`,
`GraphPatchStatusPayload`, `RequirementAuthorityResolutionPayload`,
`_DictCompatibleProjection`, `_legacy_output_record_payload`,
`_generic_output_record_payload`, `_legacy_requirement_evidence_blockers`,
`_LEGACY_SELECTOR_KIND_MAP`, `_normalize_legacy_selector`, and
`normalize_legacy_membership`. There are no graph `mode="before"` validators.

## Final Review Contract Correction

- Every modeled producer persists the validated model's JSON dump. No raw-input
  return path remains; `exclude_none` and `exclude_unset` are explicit wire
  policies only.
- Stable lifecycle, command rejection, callback, retry, heartbeat, death,
  dead-input, appeal, decision, and node lifecycle identities are required.
  Genuine callback variants use narrow producer-specific fields rather than an
  all-optional shared envelope.
- Semantic booleans such as `EdgeProjection.required` are strict. Compact
  retention carries required lifecycle and decision identities used by reducers.
- Command validation errors expose only bounded static `payload` context, safe
  error type, and fixed message without rejected field names or submitted input
  values. Shared command identity types reject empty and whitespace-containing
  IDs.
- `StoredArtifactRef.storage_uri` and `content_hash` must contain the same digest;
  durable artifact I/O and truncation recovery remain W5.5 scope.

## W5.5 Boundary

This closes strict W5 event typing only. `StoredArtifactRef` remains an
identity-only model. Durable stdout/stderr artifact storage, reference-field
cutover, bounded hydration, garbage collection, and replacement of current
20,000-character truncation are still pending under W5.5. Complete nested
`value` retention remains in place until that atomic cutover.
