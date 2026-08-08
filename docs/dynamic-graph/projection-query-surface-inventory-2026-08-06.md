# Projection query surface inventory

This records the query/export surface change for Finding 1 of the projection
simplification work. Production evidence was collected from `src/` and
`scripts/`, excluding tests and `src/orchestrator/graph/__init__.py` itself.
The referenced report file, `docs/dynamic-graph/projection-simplification-report-2026-08-05.html`,
is not present in this checkout, so the inventory below is based on the current
checkout's imports and calls.

## Before

`projection_queries.py` contained 142 public top-level names: 88 convenience
getters/projectors with no production import or call root, plus 54 query
functions used by production code. The package initializer imported 141 query
names (the module's two private helpers were not package exports) and exposed
the broad compatibility vocabulary through `orchestrator.graph`.

The 88 removed names were:

```text
accepted_graph_patch_ids, accepted_graph_patches_by_node_view,
accepted_no_successor_patch_id, accepted_no_successor_patch_ids,
accepted_output_records, accepted_output_records_for_node_port,
action_count_by_node_kind_view, active_leases, active_requirement_version,
approval_decision, approval_decisions_view, authority_decision,
authority_decisions_view, authority_revision_blocker, bound_record_ids,
callback_idempotency_event, check_result, check_results, cleanup_applied,
cleanup_request, configured_gates, decision_request,
decision_request_details_view, edge_by_id, edges_from_node, edges_to_node,
environment_failure, environment_failures, execution_count_by_node_kind_view,
failed_verification_candidate_ids, failed_verification_result,
failed_verification_results, file_state_record, gate_decision,
input_binding_for_port, input_bindings_for_node, invalid_test_block,
invalid_test_blocks, invalid_test_blocks_view, iter_edges, iter_leases,
latency_ms_by_node_kind_view, lease_generation, node_allowed_actions,
node_allowed_actions_view, node_attempt, node_candidate_id,
node_command_definition, node_creation_position, node_exists,
node_failed_candidate_id, node_gate_decision, node_kind,
node_last_deferred_reason, node_output_ports_view, node_preconditions,
node_retry_not_before, node_role, node_state, node_states, node_task_region,
node_usage_recorded, open_proposal_blocker, output_record_ids_for_node_port,
output_record_payload, oversight_decision, passed_verification_candidate_ids,
passed_verification_result, passed_verification_results, planner_generation,
planner_region_label, planner_session, planner_session_carryover,
planner_session_current_node, planner_session_state, planner_successor,
recovery_nodes, recovery_nodes_for_record, requirement_revision,
requirement_revisions_view, support_evidence, support_evidence_view,
task_candidates, task_state, task_states, tokens_by_node_kind_view,
tokens_by_node_view, verifier_verdict
```

## After

The remaining production-shaped query functions in `projection_queries.py` are:

```text
accepted_no_successor_patches_by_node_view
accepted_output_records_by_node_port_view
accepted_record_summaries_by_id_view
active_requirement_versions_view
cache_authority_binding
cache_authority_is_new_format
callback_idempotency_events_view
check_results_view
cleanup_applied_ids_view
cleanup_requested_events_view
completion_decision_passed
edges_view
environment_failures_view
execution_attempts_view
failed_verification_candidate_ids_view
failed_verification_results_by_record_id_view
file_state_records_view
input_bindings_view
last_deferred_reasons_view
latest_routine_snapshot_record
lease_by_id
leases_view
node_attempts_view
node_cache_authority_hash
node_command_definitions_view
node_creation_positions_view
node_failed_candidates_view
node_gate_decisions_view
node_kinds_view
node_max_attempts_view
node_pending_appeals_view
node_preconditions_view
node_resource_claims_view
node_roles_view
node_states_view
node_task_regions_view
non_gap_planner_has_accepted_patch
output_record_payloads_view
output_records_by_node_port_view
passed_verification_candidate_ids_view
passed_verification_results_by_record_id_view
planner_generation_budget
planner_generations_view
planner_session_carryovers_view
planner_sessions_view
ready_nodes_view
recorded_node_usage_keys_view
recovery_nodes_by_record_id_view
resource_claims_for_node
retry_not_before_by_node_view
run_state
task_candidates_view
task_states_view
verifier_verdicts_view
```

Fifty-three of these are exported by `orchestrator.graph`. The retained
`node_max_attempts_view` is intentionally module-level only: the graph command
boundary imports it directly as an internal consumer, while no production code
requires a package-root alias. This is the report-listed single-item/map
candidate retained on concrete production evidence. The other retained
functions likewise correspond to direct command, projection, patch-validation,
recovery, or runner consumers; they are not compatibility aliases.

The four private helpers used by the retained queries remain private. Tests
were updated to exercise retained consumer-shaped views and to keep legacy
assertion coverage local to test utilities; no removed name is exported by the
production graph package.
