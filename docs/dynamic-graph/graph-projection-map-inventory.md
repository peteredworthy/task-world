# GraphProjection Map Inventory

This inventory covers map-shaped `GraphProjection` state and the nested
map-like projection models used by `src/orchestrator/graph/models.py`,
`src/orchestrator/graph/projections.py`, and `src/orchestrator/graph/_commands.py`.

Outer `dict[id, ...]` indexes remain maps because graph ids are dynamic. The
decision column describes whether the value shape is typed, restore-filtered,
public JSON, or intentionally flexible.

## GraphProjection State

| Field | Classification | Decision | Rationale |
|---|---|---|---|
| `node_states` | derived structural state | Keep map; restore-filtered | Dynamic `node_id -> state`; checkpoint restore drops non-string keys and non-`NodeState` values. |
| `task_states` | derived structural state | Keep map; restore-filtered | Dynamic `task_region_id -> state`; checkpoint restore drops values outside the task-state set. |
| `leases` | already sufficiently constrained by Pydantic | Typed | Values are `LeaseProjection`; malformed checkpoint entries are dropped. `resource_claims` is now `list[ResourceClaimProjection]`. |
| `node_kinds` | derived structural state | Keep map; restore-filtered | Dynamic `node_id -> kind`; checkpoint restore drops values outside `NodeKind`. |
| `node_roles` | derived structural state | Keep map; restore-filtered | Roles are extensible strings; checkpoint restore keeps only `str -> str`. |
| `node_creation_positions` | derived structural state | Keep map; restore-filtered | Primitive ordering index; checkpoint restore keeps only `str -> int` and excludes bools. |
| `node_task_regions` | derived structural state | Keep map; restore-filtered | Primitive `node_id -> task_region_id`; checkpoint restore keeps only `str -> str`. |
| `node_attempts` | derived structural state | Keep map; restore-filtered | Primitive `node_id -> attempt_number`; checkpoint restore keeps only real ints. |
| `node_candidates` | derived structural state | Keep map; restore-filtered | Primitive `node_id -> candidate_id`; checkpoint restore keeps only `str -> str`. |
| `node_failed_candidates` | derived structural state | Keep map; restore-filtered | Primitive `node_id -> failed_candidate_id`; checkpoint restore keeps only `str -> str`. |
| `node_resource_claims` | derived structural state | Converted to Pydantic values | Now `dict[str, list[ResourceClaimProjection]]`; malformed historical claim shapes are dropped, scheduler-invalid but structurally valid claims are preserved, and checkpoint/view output remains JSON dicts. |
| `node_allowed_actions` | derived structural state | Keep map; restore-filtered | Extensible action names; checkpoint restore keeps only `str -> list[str]`. |
| `node_preconditions` | derived structural state | Keep map; restore-filtered | Extensible scheduler preconditions; checkpoint restore keeps only `str -> list[str]`. |
| `node_command_definitions` | flexible metadata bag | Explicit raw-value alias; restore-filtered outer shape | Command definitions carry provider-specific command metadata. The projection uses `CommandDefinitionProjection = dict[str, Any]` to make the flexible value explicit; restore keeps only `str -> dict` entries. |
| `node_output_ports` | derived structural state | Keep nested map; restore-filtered | Compact `node_id -> port -> record_ids` lookup; checkpoint restore keeps only nested string lists. |
| `accepted_output_records_by_node_port` | already sufficiently constrained by TypedDict/Pydantic | Typed | Nested dynamic index whose leaf uses `AcceptedOutputRecord` with typed `OutputRecordPayload`; checkpoint restore validates payloads. |
| `accepted_record_summaries_by_id` | already sufficiently constrained by TypedDict/Pydantic | TypedDict public summary; restore-filtered | `GraphRecordSummary` stores selected scalar summary fields, preserves public JSON shape, and checkpoint restore keeps only known primitive fields. |
| `output_records_by_node_port` | already sufficiently constrained by Pydantic | Typed | Nested dynamic index whose leaf is `OutputRecordPayload`; checkpoint restore validates payloads. |
| `edges` | already sufficiently constrained by Pydantic | Typed | Values are `EdgeProjection`; selectors are normalized and malformed checkpoint entries are dropped. Edge metadata remains flexible by design. |
| `input_bindings` | already sufficiently constrained by Pydantic | Typed | Nested dynamic index whose leaf is `InputBindingProjection`; malformed checkpoint entries are dropped. |
| `node_pending_appeals` | derived structural state | Keep map; restore-filtered | Sparse `node_id -> bool` flag. |
| `node_gate_decisions` | derived structural state | Keep map; restore-filtered | Sparse `node_id -> bool` gate result. |
| `task_candidates` | already sufficiently constrained by Pydantic | Typed | Values are `list[CandidateProjection]`; malformed checkpoint entries are dropped. |
| `verifier_verdicts` | already sufficiently constrained by Pydantic | Typed | Values are `VerifierVerdictProjection`; malformed checkpoint entries are dropped. |
| `passed_verification_results_by_record_id` | already sufficiently constrained by Pydantic | Typed | Values are `VerificationResultProjection`; malformed checkpoint entries are dropped. |
| `failed_verification_results_by_record_id` | already sufficiently constrained by Pydantic | Typed | Values are `VerificationResultProjection`; malformed checkpoint entries are dropped. |
| `failed_verification_candidate_ids` | derived structural state | Keep map; restore-filtered | JSON-friendly set-as-map. Checkpoint restore keeps only `str -> bool`; no richer value shape. |
| `recovery_nodes_by_record_id` | derived structural state | Converted to strict Pydantic values | Values are now `list[RecoveryNodeIndexEntry]`; malformed historical entries are dropped, unknown checkpoint keys are ignored, required strings must be non-empty, and checkpoint output remains dict-shaped. |
| `check_results` | already sufficiently constrained by Pydantic | Typed | Values are `CheckResultProjection`; malformed checkpoint entries are dropped. |
| `invalid_test_blocks` | already sufficiently constrained by Pydantic | Typed | Values are `InvalidTestBlockProjection`; malformed checkpoint entries are dropped. |
| `configured_gates` | derived structural state | Keep nested map; restore-filtered | Dynamic `task_region_id -> gate_id -> bool` matrix. |
| `gate_decisions` | derived structural state | Keep nested map; restore-filtered | Dynamic `task_region_id -> gate_id -> bool` matrix. |
| `environment_failures` | already sufficiently constrained by Pydantic | Typed | Values are `EnvironmentFailureProjection`; malformed checkpoint entries are dropped. |
| `file_state_records` | already sufficiently constrained by Pydantic | Typed | Values are `FileStateRecord`; malformed checkpoint entries are dropped. |
| `planner_successors` | derived structural state | Keep map; restore-filtered | Primitive planner successor lookup. |
| `accepted_graph_patches_by_node` | derived structural state | Keep map; restore-filtered | Primitive patch id history by planner node. |
| `accepted_no_successor_patches_by_node` | derived structural state | Keep map; restore-filtered | Primitive no-successor patch id history. |
| `accepted_no_successor_patch_ids_by_node` | derived structural state | Keep map; restore-filtered | Primitive latest no-successor patch id. Consolidation would be a separate cleanup. |
| `latest_routine_snapshot_record` | derived structural state | Converted to strict Pydantic value | Now `LatestRoutineSnapshotRecord | None`; malformed checkpoint entries are dropped, unknown checkpoint keys are ignored, required strings must be non-empty, and JSON output remains dict-shaped. |
| `planner_generations` | derived structural state | Keep map; restore-filtered | Primitive generation counter map. |
| `planner_sessions` | derived structural state | Keep map; restore-filtered | Primitive planner-node to session id map. |
| `planner_session_states` | derived structural state | Keep map; restore-filtered | Session states remain extensible strings; checkpoint restore keeps only `str -> str`. |
| `planner_session_current_nodes` | derived structural state | Keep map; restore-filtered | Primitive session to current planner node map. |
| `planner_session_carryovers` | derived structural state | Keep map; restore-filtered | Primitive session to optional carryover record id map. |
| `planner_region_labels` | derived structural state | Keep map; restore-filtered | Primitive planner-node to display label map. |
| `requirement_revisions` | already sufficiently constrained by Pydantic | Typed | Values are `RequirementRevisionProjection`; malformed checkpoint entries are dropped. |
| `active_requirement_versions` | derived structural state | Keep map; restore-filtered | Primitive requirement id to active version id map. |
| `support_evidence` | already sufficiently constrained by Pydantic | Typed | Values are `SupportEvidenceProjection`; malformed checkpoint entries are dropped. |
| `last_deferred_reasons` | derived structural state | Keep map; restore-filtered | Primitive scheduler annotation map. |
| `retry_not_before_by_node` | derived structural state | Keep map; restore-filtered | Primitive node to nullable timestamp string map. |
| `node_creation_payloads` | already sufficiently constrained by Pydantic | Typed | Values are `NodeCreationProjection`; `resource_claims` is now `list[ResourceClaimProjection]`. |
| `output_record_payloads` | already sufficiently constrained by Pydantic | Typed | Values are `OutputRecordPayload`; malformed checkpoint entries are dropped. |
| `approval_decisions` | already sufficiently constrained by Pydantic | Typed | Values are `ApprovalDecisionProjection`; malformed checkpoint entries are dropped. |
| `authority_decisions` | already sufficiently constrained by Pydantic | Typed | Values are `AuthorityDecisionProjection`; malformed checkpoint entries are dropped. |
| `oversight_decisions` | already sufficiently constrained by Pydantic | Typed | Values are `OversightDecisionProjection`; malformed checkpoint entries are dropped. `scope` remains a flexible decision metadata bag. |
| `decision_request_details` | already sufficiently constrained by Pydantic | Typed | Values are `PendingGateDecisionProjection`; malformed checkpoint entries are dropped. |
| `callback_idempotency_events` | already sufficiently constrained by Pydantic | Typed | Values are `CallbackIdempotencyEvent`; malformed checkpoint entries are dropped. |
| `open_proposal_blockers` | already sufficiently constrained by TypedDict/Pydantic | Keep TypedDict map; restore-filtered | Values use `FinalInvariantBlocker`, a public final-invariant view shape with heterogeneous blocker kinds. Checkpoint restore keeps known primitive fields, filters `support_ids` to strings, and drops entries missing `kind` or `reason`. |
| `suspect_node_reasons` | derived structural state | Keep map; restore-filtered | Primitive node to reason map. |
| `authority_revision_blockers` | already sufficiently constrained by TypedDict/Pydantic | Keep TypedDict map; restore-filtered | Same `FinalInvariantBlocker` public view shape as proposal blockers. Checkpoint restore keeps known primitive fields, filters `support_ids` to strings, and drops entries missing `kind` or `reason`. |
| `cleanup_requested_events` | already sufficiently constrained by Pydantic | Typed | Values are `CleanupRequestedProjection`; malformed checkpoint entries are dropped. |
| `cleanup_applied_ids` | derived structural state | Keep map; restore-filtered | JSON-friendly set-as-map. |

## Nested Models And Public Views

| Location | Classification | Decision | Rationale |
|---|---|---|---|
| `TypedRecordBase.payload`, `TypedRecordBase.provenance` | direct copied record metadata | Intentionally raw | Heterogeneous record metadata remains JSON, while each accepted record envelope is selected by its required canonical discriminator and validated by its strict model. |
| `EventEnvelope.payload` | heterogeneous transport envelope | Raw only at storage/transport boundary | Every one of the 46 canonical event names maps to an exact strict payload model and retention spec. Current producers validate and JSON-dump before constructing the envelope; reducers parse through the registered model before typed consumption. |
| Typed output-record `value` fields | schema-owned record value | Typed by record discriminator | The explicit 22-entry `OUTPUT_RECORD_MODELS_BY_TYPE` map rejects missing/unknown discriminators and validates each complete record. No generic or legacy output fallback remains. |
| `ResourceClaimProjection` | already sufficiently constrained by Pydantic | Converted | Projection-state claim shape that normalizes legacy `path` claims while preserving scheduler-invalid but structurally valid claims for scheduler readiness decisions. |
| `ResourceClaim` | already sufficiently constrained by Pydantic | Keep strict | Command/patch model claim shape; external claims still require `external_resource_key`. |
| `LeaseProjection.resource_claims` | derived structural state | Converted | Now `list[ResourceClaimProjection]`; scheduler command output still serializes claims as JSON dicts. |
| `NodeCreationProjection.resource_claims` | direct copied event payload | Converted | Now `list[ResourceClaimProjection]`; direct event payload compatibility is preserved through legacy normalization. |
| `NodeCreationProjection.decision_request`, `authority_request_record`, `authority_request`, `authority` | direct copied event payload | Intentionally raw for now | These fields copy command/event request payloads and are normalized into separate request records where needed. |
| `NodeCreationProjection.command_definition` | flexible metadata bag | Explicit raw-value alias | Uses `CommandDefinitionProjection = dict[str, Any]`; command-binding definitions are provider-specific metadata and are separately checked by command-binding helpers. |
| `EdgeProjection.accepted_record_selector` | already sufficiently constrained by Pydantic normalization | Keep JSON dict | Stored as JSON dict to preserve topology/checkpoint shape, but creation normalizes through `RecordSelector`. |
| `EdgeProjection.purpose`, `description`, `selection`, `binding_policy`, `freshness_policy`, `prompt_hydration_policy`, `metadata` | flexible metadata bag | Intentionally raw | Edge policy/metadata fields are intentionally extensible and public topology output must remain dict-shaped. |
| `InputBindingProjection.record_bound_positions` | derived structural state | Keep primitive map | Dynamic `record_id -> position` map; Pydantic validates the value type. |
| `VerificationReportValue.grades` | public view/output shape | Typed | Grade rows use the strict `GradeRow` model while keeping the grade string open for historical and future values. |
| `OversightDecisionProjection.decider`, `scope` and approval/authority decision `scope` fields | public view/output shape | Keep flexible metadata | Decision actor/scope values are exposed as JSON and may contain human/agent metadata beyond the current reducer needs. |
| `CompletionDecisionValue.blockers` | public view/output shape | Keep TypedDict-compatible JSON | Final invariant blockers are typed in projection views as `FinalInvariantBlocker`; completion records preserve public JSON. |
| `CheckResultValue.command`, `environment_policy`, `command_binding` | direct copied event payload | Intentionally raw | Command execution output stores command metadata and environment policy from command binding/runtime layers. |
| `GraphPatchProposalValue.ops`, `macro_invocations`, `PatchOp.node`, `PatchOp.selection`, `PatchOp.metadata` | direct copied event/command payload | Intentionally raw | Patch operations are validated by patch-validator and macro expansion; public command JSON must be preserved. |
| `GraphPatchResultRecord.diagnostics`, `read_set_diff` and `GraphPatchAttempt.diagnostics`, `read_set_diff` | public view/output shape | Intentionally raw | Diagnostics and read-set diffs are public troubleshooting payloads whose keys vary by validator result. |
| `RecoveryPlanValue.graph_changes` | public view/output shape | Intentionally raw | Recovery plans summarize patch-like changes as JSON output; no stable richer schema in this pass. |
| `CallbackEnvelope.records` | direct copied event payload | Intentionally raw | External callbacks submit heterogeneous output records; per-record validation happens after callback acceptance. |
| `GraphTopologyNode.contract`, `GraphTopologyEdge.accepted_record_selector`, `metadata`, `source_port_contract`, `target_port_contract` | public view/output shape | Keep TypedDict JSON | Topology endpoints intentionally expose JSON dictionaries for contract and selector summaries. |
| `GraphPatchAttempt` | public view/output shape | Keep TypedDict JSON | Public patch-attempt read model must remain dict-shaped for API/read-model consumers. |
| `project_planner_chain`, `project_planner_session`, `project_node_metadata`, `project_planner_freshness_packet`, `project_pattern_library`, `project_gatekeeper_report`, `project_residue_report` | public view/output shape | Keep JSON dicts | These are read-model/API output shapes. They may gain additional TypedDicts later, but external JSON shape should not change. |

## Current Pass Summary

Converted or hardened in this pass:

1. `GraphProjection.node_resource_claims`, `LeaseProjection.resource_claims`,
   and `NodeCreationProjection.resource_claims` now use
   `ResourceClaimProjection`; strict command/patch validation remains on
   `ResourceClaim`.
2. `GraphProjection.recovery_nodes_by_record_id` now stores
   `RecoveryNodeIndexEntry` Pydantic values.
3. `GraphProjection.latest_routine_snapshot_record` now stores a
   `LatestRoutineSnapshotRecord` Pydantic value.
4. Remaining primitive checkpoint maps listed above now restore through
   explicit shape filters instead of raw checkpoint merge-through.
5. Related primitive checkpoint fields that can corrupt map consumers
   (`run_state`, `ready_nodes`, `completion_decision_passed`,
   `passed_verification_candidate_ids`, and `planner_generation_budget`) are
   also restore-filtered.

Intentionally raw maps remain only where the payload is an external/public
JSON shape, a direct heterogeneous event payload, or a broad metadata bag whose
schema is owned by another validator layer.

## W5 Closeout

The final W5 audit confirms:

- All 46 canonical events have exact strict models and explicit projection,
  light, summary-rebuild, and node-detail retention specs.
- The four generated sorted unique allowlists contain 101, 141, 159, and 84
  fields. No retained field is unowned by its model and no `extra` field is
  generated.
- `GraphProjection` outer identifier indexes remain maps by design; structured
  values and record envelopes are typed as documented above. Compatibility
  mapping facades and generic output-record fallbacks are deleted.
- `GradeRow` is strict and `VerificationReportValue.grades` is typed.

W5.5 is not part of this closure. Check stdout/stderr still use current inline
complete-value retention and 20,000-character truncation. Durable artifact
storage, reference cutover, hydration, garbage collection, and truncation
recovery remain pending in the separate W5.5 design and implementation plan.
