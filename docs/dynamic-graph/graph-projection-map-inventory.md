# GraphProjection Map Inventory

This inventory covers every map-shaped field on `GraphProjection` in
`src/orchestrator/graph/projections.py`. "Keep map" means the outer map is
the right shape because keys are dynamic graph ids; the decision is about
whether the map values need stronger structure or checkpoint validation.

| Field | Classification | Decision | Rationale |
|---|---|---|---|
| `node_states` | structural state index | Harden | Values are finite node lifecycle states copied from events and widely read. Keep `node_id -> state` map, but validate values on checkpoint restore. |
| `task_states` | derived structural state index | Harden | Values are finite derived task states. Keep `task_region_id -> state` map, but validate values on checkpoint restore. |
| `leases` | typed projection records | Already typed | `LeaseProjection` is Pydantic-backed, dumped/restored explicitly, keyed by lease id. |
| `node_kinds` | structural state index | Harden | Values are finite `NodeKind` strings copied from events and drive contracts/topology. Keep `node_id -> kind` map, but validate values on checkpoint restore. |
| `node_roles` | structural state index | Keep map | Roles are intentionally extensible strings used by contracts/prompts. |
| `node_creation_positions` | derived index | Keep map | Primitive `node_id -> event position` ordering index. |
| `node_task_regions` | id index | Keep map | Primitive `node_id -> task_region_id` link; ids are free-form. |
| `node_attempts` | numeric index | Keep map | Primitive `node_id -> attempt_number` index. |
| `node_candidates` | id index | Keep map | Primitive `node_id -> candidate_id` link. |
| `node_failed_candidates` | id index | Keep map | Primitive `node_id -> failed_candidate_id` link. |
| `node_resource_claims` | structured nested records | Harden | Values are resource-claim records currently held as raw dicts. Keep `node_id -> claims` map, but validate claim entries and drop malformed historical entries. |
| `node_allowed_actions` | policy string list | Keep map | Extensible action strings, no stable richer shape. |
| `node_preconditions` | policy string list | Keep map | Extensible scheduler precondition strings. |
| `node_command_definitions` | command metadata bag | Keep map | Command definitions are command-binding payloads with intentionally flexible provider-specific shape. |
| `node_output_ports` | derived lookup index | Keep map | Compact `node_id -> port -> record_ids` lookup. |
| `accepted_output_records_by_node_port` | typed public record payload index | Already typed | Uses `AcceptedOutputRecord` with typed `OutputRecordPayload` and checkpoint validation. |
| `accepted_record_summaries_by_id` | public summary shape | Keep map | `GraphRecordSummary` is a small `TypedDict`; it stores selected scalar summary fields, not raw payloads. |
| `output_records_by_node_port` | typed record payload index | Already typed | Uses `OutputRecordPayload` and checkpoint validation. |
| `edges` | structural routing records | Hardened in this pass | Now uses `EdgeProjection`, explicit reducer construction, and checkpoint validation. Metadata/selectors remain flexible by design. |
| `input_bindings` | structural routing records | Hardened in this pass | Now uses `InputBindingProjection`, explicit reducer construction, and checkpoint validation. |
| `node_pending_appeals` | sparse bool index | Keep map | Dynamic `node_id -> pending` scheduler flag. |
| `node_gate_decisions` | sparse bool index | Keep map | Dynamic `node_id -> decision passed` scheduler flag. |
| `task_candidates` | typed projection records | Already typed | Uses `CandidateProjection` list values and checkpoint validation. |
| `verifier_verdicts` | typed projection records | Already typed | Uses `VerifierVerdictProjection` and checkpoint validation. |
| `passed_verification_results_by_record_id` | typed projection records | Already typed | Uses `VerificationResultProjection` and checkpoint validation. |
| `failed_verification_results_by_record_id` | typed projection records | Already typed | Uses `VerificationResultProjection` and checkpoint validation. |
| `failed_verification_candidate_ids` | sparse set-as-map | Keep map | JSON-friendly `candidate_id -> true` set. |
| `recovery_nodes_by_record_id` | structural index entries | Harden | Values are small structural entries. Keep `record_id -> entries` map, but validate `node_id` and `recovery_reason` on checkpoint restore. |
| `check_results` | typed projection records | Already typed | Uses `CheckResultProjection` and checkpoint validation. |
| `invalid_test_blocks` | typed projection records | Already typed | Uses `InvalidTestBlockProjection` and checkpoint validation. |
| `configured_gates` | bool matrix | Keep map | Dynamic `task_region_id -> gate_id -> configured` matrix. |
| `gate_decisions` | bool matrix | Keep map | Dynamic `task_region_id -> gate_id -> passed` matrix. |
| `environment_failures` | typed projection records | Already typed | Uses `EnvironmentFailureProjection` and checkpoint validation. |
| `file_state_records` | typed graph records | Already typed | Uses `FileStateRecord` and checkpoint validation. |
| `planner_successors` | id index | Keep map | Primitive planner-node successor lookup. |
| `accepted_graph_patches_by_node` | id-list index | Keep map | Primitive patch history by planner node. |
| `accepted_no_successor_patches_by_node` | id-list index | Keep map | Primitive no-successor patch history. |
| `accepted_no_successor_patch_ids_by_node` | redundant id index | Keep map for now | Not a typing candidate; potential cleanup is consolidation/removal, not projection modeling. |
| `latest_routine_snapshot_record` | tiny structural ref | Harden | Three-field routine snapshot reference used by recovery commands. Convert to a typed projection shape and validate checkpoints. |
| `planner_generations` | numeric index | Keep map | Primitive planner-node generation lookup. |
| `planner_sessions` | id index | Keep map | Primitive planner-node to session id lookup. |
| `planner_session_states` | state index | Keep map | Planner session states are narrow today but local to session read model; defer unless this becomes a public contract. |
| `planner_session_current_nodes` | id index | Keep map | Primitive session to current node lookup. |
| `planner_session_carryovers` | nullable id index | Keep map | Primitive session to carryover record id lookup. |
| `planner_region_labels` | label index | Keep map | Primitive planner-node to display label lookup. |
| `requirement_revisions` | typed projection records | Already typed | Uses `RequirementRevisionProjection` and checkpoint validation. |
| `active_requirement_versions` | id index | Keep map | Primitive requirement to active version lookup. |
| `support_evidence` | typed projection records | Already typed | Uses `SupportEvidenceProjection` and checkpoint validation. |
| `last_deferred_reasons` | reason index | Keep map | Scheduler/read-model annotation keyed by node id. |
| `retry_not_before_by_node` | nullable timestamp index | Keep map | Primitive node retry timestamp string; parsing is local and bounded. |
| `node_creation_payloads` | typed projection records | Already typed | Uses `NodeCreationProjection` and checkpoint validation. |
| `output_record_payloads` | typed record payloads | Already typed | Uses `OutputRecordPayload` union and checkpoint validation. |
| `approval_decisions` | typed projection records | Already typed | Uses `ApprovalDecisionProjection` and checkpoint validation. |
| `authority_decisions` | typed projection records | Already typed | Uses `AuthorityDecisionProjection` and checkpoint validation. |
| `oversight_decisions` | typed projection records | Already typed | Uses `OversightDecisionProjection` and checkpoint validation. |
| `decision_request_details` | typed projection records | Already typed | Uses `PendingGateDecisionProjection` and checkpoint validation. |
| `callback_idempotency_events` | typed projection records | Already typed | Uses `CallbackIdempotencyEvent` and checkpoint validation. |
| `open_proposal_blockers` | final-invariant view entries | Keep map | Uses `FinalInvariantBlocker` `TypedDict`; entries are derived and heterogeneous by blocker kind. A future discriminated blocker union would be broader than this pass. |
| `suspect_node_reasons` | reason index | Keep map | Primitive node to reason lookup. |
| `authority_revision_blockers` | final-invariant view entries | Keep map | Same `FinalInvariantBlocker` rationale as proposal blockers. |
| `cleanup_requested_events` | typed projection records | Already typed | Uses `CleanupRequestedProjection` and checkpoint validation. |
| `cleanup_applied_ids` | sparse set-as-map | Keep map | JSON-friendly `cleanup_id -> true` set. |

## Work Queue From This Inventory

This pass hardens:

1. `edges` and `input_bindings`.
2. Finite primitive maps: `node_states`, `task_states`, `node_kinds`.
3. Structured nested/index entries: `node_resource_claims`,
   `recovery_nodes_by_record_id`, and `latest_routine_snapshot_record`.

Everything else remains a map for the rationale above, or is already
Pydantic-backed.
