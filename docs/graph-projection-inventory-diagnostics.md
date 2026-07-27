# GraphProjection Inventory Diagnostic Fixture

Generated from the tracked repository with the diagnostic command.
The command intentionally exits nonzero while unresolved flows remain.

## Complete sorted diagnostics

```text
Unresolved GraphProjection flows: 646
unsupported_binding: 9
unsupported_call: 566
unsupported_comparison: 71

src/orchestrator/api/presenters/evidence_digest.py:143:18: _representative_nodes: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/presenters/evidence_digest.py:147:20: _representative_nodes: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/presenters/evidence_digest.py:213:25: build_run_evidence_digest_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/presenters/evidence_digest.py:214:21: build_run_evidence_digest_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/presenters/evidence_digest.py:215:24: build_run_evidence_digest_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:607:18: build_graph_projection_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:608:20: build_graph_projection_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:609:20: build_graph_projection_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:610:15: build_graph_projection_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:611:20: build_graph_projection_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:759:18: build_graph_regions_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:760:15: build_graph_regions_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:803:21: build_scheduler_view_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:804:17: build_scheduler_view_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:917:16: build_graph_health_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:918:13: build_graph_health_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:919:16: build_graph_health_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:920:18: build_graph_health_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:933:23: build_graph_health_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:960:16: build_graph_health_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:1487:18: build_node_detail_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:1488:20: build_node_detail_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/api/routers/graph.py:1489:13: build_node_detail_response: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:300:19: _apply_lifecycle_command: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:372:12: _apply_record_heartbeat: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:375:7: _apply_record_heartbeat: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:429:11: _apply_record_node_usage: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:453:27: _cancel_active_lease_events: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:475:21: _cancel_active_lease_events: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:499:7: _apply_evaluate_final_gate: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:502:15: _apply_evaluate_final_gate: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:548:7: _apply_evaluate_join: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:585:15: _join_source_record_ids: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:624:27: _release_active_node_leases: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:756:13: _apply_callback_command: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:914:12: _lease_node_id: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:979:12: _file_state_authority_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:983:7: _file_state_authority_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1092:16: _output_record_contract_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1095:16: _output_record_contract_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1480:11: _verification_record_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1512:16: _required_output_record_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1515:16: _required_output_record_conflict: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1581:21: _accepted_verification_record_events: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:1619:14: _candidate_is_bound_to_verifier: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2031:22: _file_state_record_ids_for_candidate_records: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2039:18: _file_state_record_ids_for_candidate_records: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2051:15: _bound_record_ids_for_ports: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2080:16: _input_bound_events_for_record: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2129:14: _existing_bound_record_ids: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2141:18: _target_port_contract_for_edge: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2144:18: _target_port_contract_for_edge: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2203:13: _apply_patch_command: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2286:24: _apply_patch_command: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2384:24: _planner_budget_rejection: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2405:21: _apply_schedule_tick: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2411:21: _apply_schedule_tick: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2423:31: _apply_schedule_tick: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2449:19: _apply_schedule_tick: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2491:17: _apply_schedule_tick: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2564:7: _append_node_deferred_if_changed: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2739:21: _active_lease_node_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2750:17: _project_with_events: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2776:7: _failed_check_recovery_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:2781:62: _failed_check_recovery_events: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2784:48: _failed_check_recovery_events: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2796:11: _failed_check_recovery_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:2872:7: _failed_verification_recovery_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:2876:48: _failed_verification_recovery_events: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2888:11: _failed_verification_recovery_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:2958:24: _current_failed_verification_results: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2992:18: _superseded_by_later_regional_pass: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:2999:18: _superseded_by_later_regional_pass: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3022:15: _verification_task_region: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3041:14: _candidate_verdict_position: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3054:7: _passed_verification_terminalization_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:3092:7: _passed_check_terminalization_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:3098:33: _passed_check_terminalization_events: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3115:7: _no_successor_recovery_terminal_failure_events: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:3121:21: _no_successor_recovery_terminal_failure_events: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3124:48: _no_successor_recovery_terminal_failure_events: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3180:15: _completed_no_successor_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3213:37: _recovery_nodes_by_record_id: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3218:16: _accepted_no_successor_patch_id: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3233:24: _recovery_created_executable_successors: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3234:16: _recovery_created_executable_successors: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3238:11: _recovery_created_executable_successors: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:3240:11: _recovery_created_executable_successors: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3242:11: _recovery_created_executable_successors: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3263:24: _recovery_lineage_superseded: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3267:18: _recovery_lineage_superseded: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3270:33: _recovery_lineage_superseded: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3280:16: _downstream_node_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3377:16: _would_create_directed_cycle: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3398:29: _has_final_invariant_check: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3405:24: _current_passed_verification_results: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3419:25: _final_checks_waiting_for_verification_evidence: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3422:11: _final_checks_waiting_for_verification_evidence: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3424:11: _final_checks_waiting_for_verification_evidence: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3426:38: _final_checks_waiting_for_verification_evidence: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3437:16: _has_verification_evidence_edge: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3454:16: _unreachable_failure_branch_node_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3472:16: _unreachable_check_failure_branch_node_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3497:16: _downstream_retirable_node_ids: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3505:24: _downstream_retirable_node_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3515:8: _is_final_invariant_check: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3516:12: _is_final_invariant_check: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3522:8: _is_gap_planner: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3523:11: _is_gap_planner: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3546:7: _retire_node_events: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3572:16: _has_existing_failed_verification_recovery: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3580:11: _has_existing_failed_verification_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3582:11: _has_existing_failed_verification_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3583:12: _has_existing_failed_verification_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3591:27: _current_failed_check_results: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3606:26: _current_failed_check_results: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3607:11: _current_failed_check_results: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3609:11: _current_failed_check_results: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3611:11: _current_failed_check_results: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:3628:33: _current_failed_check_results: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3643:16: _has_existing_failed_check_recovery: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3651:11: _has_existing_failed_check_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3653:11: _has_existing_failed_check_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3654:12: _has_existing_failed_check_recovery: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3669:19: _latest_routine_snapshot_record: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3723:15: _base_snapshot_id_for_node: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3739:23: _retry_backoff_deferred_reason: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3758:17: _planner_session_id: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3767:17: _next_lease_generation: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3770:21: _next_lease_generation: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3779:14: _session_carryover_record_id: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3796:17: _planner_session_state_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3816:8: _is_chain_planner: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3817:12: _is_chain_planner: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3831:12: _apply_acknowledge_start: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3863:12: _apply_agent_died: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:3994:21: _apply_agent_died: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4180:8: _non_gap_planner_has_accepted_patch: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4181:12: _non_gap_planner_has_accepted_patch: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4182:12: _non_gap_planner_has_accepted_patch: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4244:16: _apply_record_decision: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4262:17: _apply_record_decision: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4287:21: _apply_record_decision: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4364:16: _decision_output_record: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4407:13: _apply_record_gatekeeper_verdicts: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4526:41: _apply_record_cleanup_applied: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:4639:33: _apply_record_support_evidence: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4667:11: _cleanup_requested_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:4671:11: _cleanup_applied_exists: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5087:17: _expired_lease_events: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5140:36: _expired_active_lease_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5160:11: _node_schedule_info: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5168:49: _node_schedule_info: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5171:30: _node_schedule_info: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5189:42: _node_schedule_info: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5194:35: _node_schedule_info: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:5199:11: _node_creation_position: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5207:16: _required_edges_for_node: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5256:11: _node_exists: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:5256:51: _node_exists: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/_commands.py:5318:26: _input_bound_events_for_edge: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5357:8: _projection_edge_accepts_producer: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5361:8: _projection_edge_accepts_producer: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5380:12: _edge_payload_accepts_producer: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5386:12: _edge_payload_accepts_producer: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/_commands.py:5401:23: _edge_backfill_producer_node_ids: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/callbacks.py:69:12: validate_callback: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/callbacks.py:112:17: validate_callback: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/callbacks.py:141:17: _validate_expired_lease_callback: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/callbacks.py:155:27: _has_replacement_active_lease: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/callbacks.py:199:20: _validate_idempotency: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:146:20: validate_patch: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:154:20: validate_patch: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:260:43: _validate_typed_topology: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/patch_validator.py:315:35: _register_created_node: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/patch_validator.py:343:11: _node_contract_identity: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:346:11: _node_contract_identity: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:396:16: _validate_no_forbidden_cycles: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:526:21: _validate_no_poisoned_final_invariant_edges: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:580:11: _node_kind_role: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:580:50: _node_kind_role: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/patch_validator.py:843:43: _existing_resource_claim_rank: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projection_queries.py:12:11: resource_claims_for_node: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:548:22: projection_to_checkpoint: unsupported_call: invalid cast projection call shape; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:549:32: projection_to_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:553:32: projection_to_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:557:31: projection_to_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:561:41: projection_to_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:570:31: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:574:29: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:583:30: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:587:33: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:593:33: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:599:31: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:603:37: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:607:32: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:611:33: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:615:42: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:619:37: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:632:30: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:639:30: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:643:34: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:647:26: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:651:39: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:655:33: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:657:48: projection_to_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:664:51: projection_to_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:673:32: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:677:32: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:681:32: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:685:36: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:689:35: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:693:32: projection_to_checkpoint: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1808:23: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1809:23: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1812:35: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1815:23: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1816:22: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1817:22: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1818:35: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1819:29: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1820:25: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1821:27: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1822:34: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1824:57: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1827:59: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1831:42: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1833:36: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1836:34: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1840:34: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1844:38: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1848:34: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1852:33: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1861:34: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1863:32: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1864:31: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1867:46: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1869:29: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1871:52: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1874:52: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1877:45: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1880:45: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1885:41: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1887:25: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1890:41: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1895:41: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1899:45: _clone_projection: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1901:32: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1902:30: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1904:30: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1907:38: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1911:38: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1913:51: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1917:31: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1918:28: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1919:34: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1920:41: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1921:38: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1922:33: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1923:33: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1924:39: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1925:28: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1926:33: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1927:36: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1928:34: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1929:34: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1930:30: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1931:31: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1932:31: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1935:36: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1938:39: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1941:40: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1943:32: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1946:40: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1950:45: _clone_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1953:31: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1954:26: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1955:31: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1956:35: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1957:40: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1958:36: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1959:36: _clone_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1974:28: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:1988:12: reduce_event: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2009:20: reduce_event: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2010:20: reduce_event: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2035:16: reduce_event: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2046:11: reduce_event: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/projections.py:2050:16: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2053:16: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2057:20: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2060:20: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2063:20: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2095:63: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2103:17: reduce_event: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/projections.py:2107:34: reduce_event: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2122:16: reduce_event: unsupported_call: projection field method pop is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2138:28: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2150:28: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2195:8: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2201:8: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2205:8: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2231:23: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2237:39: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2247:16: reduce_event: unsupported_call: projection field method pop is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2287:8: reduce_event: unsupported_call: projection field method pop is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2292:32: reduce_event: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2336:31: final_invariant_blockers_for_events: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2337:15: final_invariant_blockers_for_events: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2338:15: final_invariant_blockers_for_events: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2386:38: final_invariant_blockers_for_events: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2402:31: _node_fulfillment_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2424:25: _node_fulfillment_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2434:25: _impossible_input_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2442:11: _impossible_input_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2444:11: _impossible_input_blockers: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/projections.py:2452:21: _impossible_input_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2454:25: _impossible_input_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2465:25: _dead_required_input_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2473:23: _dead_required_input_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2476:23: _dead_required_input_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2479:18: _dead_required_input_blockers: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2492:25: _dead_required_input_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2510:31: _non_terminal_node_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2514:15: _non_terminal_node_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2523:25: _non_terminal_node_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2591:28: _failed_check_result_blockers_from_projection: unsupported_call: projection.get result method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2650:29: _completion_decision_blockers: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2665:27: _completion_decision_blockers: unsupported_call: projection.get result method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2687:29: _completion_decision_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2702:25: _completion_decision_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2747:23: _open_proposal_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2780:21: _suspect_node_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2830:23: _authority_revision_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2872:31: _blocked_requirement_node_blockers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2873:11: _blocked_requirement_node_blockers: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2909:8: _record_open_proposal_blocker: unsupported_call: projection field method pop is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:2942:12: _record_authority_revision_blocker: unsupported_call: projection field method pop is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3019:29: project_planner_chain: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3046:18: project_planner_session: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3048:22: project_planner_session: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3080:17: project_planner_session: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3082:27: project_planner_session: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3083:31: project_planner_session: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3136:19: project_graph_topology: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3137:15: project_graph_topology: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3138:15: project_graph_topology: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3143:21: project_graph_topology: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3152:23: project_graph_topology: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3302:31: support_evidence_freshness_from_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3328:45: requirement_freshness_facts_from_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3331:19: requirement_freshness_facts_from_projection: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3334:35: requirement_freshness_facts_from_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3505:26: project_decision_view_from_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3506:15: project_decision_view_from_projection: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3646:18: _edge_port_contracts: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3650:18: _edge_port_contracts: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3654:18: _edge_port_contracts: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3655:18: _edge_port_contracts: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3691:14: _binding_for_edge: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3694:17: _binding_for_edge: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:3726:34: _record_summaries_by_id: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4105:24: _project_missing_input_sources: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4230:4: _record_callback_idempotency_event: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4325:15: _gate_type: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4330:11: _gate_type: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4417:12: _planner_region_label: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4420:23: _planner_region_label: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4481:46: _record_candidate: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4489:25: _record_candidate: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4512:4: _record_candidate: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4546:4: _record_recovery_node: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4573:11: _record_verification_result: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/projections.py:4608:46: _record_check_result: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4655:12: _record_node_output_port: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4670:12: _record_accepted_output_record: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4702:4: _record_output_record: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4739:24: _record_open_appeal: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4794:25: _record_gate_decision: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4800:4: _record_gate_decision: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4819:8: _clear_authority_revision_blocker: unsupported_call: projection field method pop is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4950:33: _record_support_evidence: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:4982:31: _mark_superseded_support_stale: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5008:24: _support_stale_reason: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5102:23: _record_input_binding: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5124:8: _record_input_binding: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5148:15: _edge_for_input_binding: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5151:16: _edge_for_input_binding: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5167:18: _target_port_for_binding: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5170:18: _target_port_for_binding: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5242:46: _record_environment_failure: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5319:13: _record_gatekeeper_verdicts: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5341:8: _record_cleanup_requested: unsupported_call: projection field method setdefault is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5346:13: _record_cleanup_requested: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5371:13: _record_cleanup_applied: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5587:22: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5588:4: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5589:4: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5590:4: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5591:4: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5594:21: _derive_task_states: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5597:4: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5601:27: _derive_task_states: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5610:27: _derive_task_states: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5611:25: _derive_task_states: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5613:24: _derive_task_states: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5616:18: _derive_task_states: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5640:13: _derive_task_states: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/projections.py:5655:38: _apply_accepted_region_supersessions: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5695:44: _task_region_node_ids: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5701:11: _contract_for_node: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5704:11: _contract_for_node: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5715:17: _node_contract_fulfilled: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5733:12: _missing_fulfillment_ports: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5742:17: _final_invariant_node_passed: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5745:15: _final_invariant_node_passed: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5754:14: _verifier_requirement_passed: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5768:29: _verifier_requirement_passed: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5777:18: _task_file_state_accepted: unsupported_call: projection.get result method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5782:35: _task_file_state_accepted: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5796:23: _required_checks_passed: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5799:29: _required_checks_passed: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5807:17: _required_checks_passed: unsupported_call: projection.get result method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5853:20: _check_result_recovery_superseded: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5864:24: _failed_verification_recovery_superseded: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5872:24: _failed_verification_recovery_superseded: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5885:24: _recovery_lineage_has_complete_verification: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5892:18: _recovery_lineage_has_complete_verification: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5897:29: _recovery_lineage_has_complete_verification: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5900:27: _recovery_lineage_has_complete_verification: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5901:25: _recovery_lineage_has_complete_verification: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5916:24: _recovery_lineage_passed: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5920:18: _recovery_lineage_passed: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5923:33: _recovery_lineage_passed: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5933:16: _downstream_node_ids: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5978:21: _replacement_verification_passed: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5979:18: _replacement_verification_passed: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:5990:17: _has_active_task_lease: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/projections.py:6001:38: _task_region_for_candidate: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph/scenario.py:60:25: run_scenario: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/scenario.py:61:21: run_scenario: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/scenario.py:77:21: run_scenario: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/scenario.py:79:7: run_scenario: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph/scenario.py:81:4: run_scenario: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/scenario.py:82:4: run_scenario: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph/scenario.py:83:27: run_scenario: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/dispatch.py:908:12: _recovered_lease_still_active: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/dispatch.py:1088:19: _guard_no_pending_compromised_file_state_bindings: unsupported_call: calling a projection-derived value is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/dispatch.py:1090:21: _guard_no_pending_compromised_file_state_bindings: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:288:15: _prompt_summary_input_ports: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:464:23: _planner_packet: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:478:30: _planner_packet: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:552:18: _planner_frontier: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:556:19: _planner_frontier: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:557:21: _planner_frontier: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:605:25: _gap_analysis_obligations: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:614:11: _gap_analysis_obligations: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:616:22: _gap_analysis_obligations: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:636:11: _gap_analysis_obligations: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:638:11: _gap_analysis_obligations: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:659:15: _planner_evidence: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:680:15: _planner_evidence: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph_runtime/prompts.py:685:39: _planner_evidence: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:744:11: _hydration_policy_for_binding: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:888:21: _planner_outstanding_failures: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:891:30: _planner_outstanding_failures: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:905:17: _planner_session_carryover_record: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:908:16: _planner_session_carryover_record: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:1307:29: _file_state_record_ids_for_task_region: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:1312:35: _file_state_record_ids_for_task_region: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/prompts.py:1327:15: _bound_record_ids_for_ports: unsupported_call: projection field method get is unsupported; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/recovery.py:80:7: reconcile_graph: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph_runtime/store.py:704:22: GraphEventStore.load_projection_with_tail: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:706:19: GraphEventStore.load_projection_with_tail: unsupported_binding: projection escapes through a collection constructor; retain the GraphProjection annotation through this binding
src/orchestrator/graph_runtime/store.py:714:18: GraphEventStore.load_projection_with_tail: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:716:15: GraphEventStore.load_projection_with_tail: unsupported_binding: projection escapes through a collection constructor; retain the GraphProjection annotation through this binding
src/orchestrator/graph_runtime/store.py:863:15: GraphEventStore.advance_projection_snapshot: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
src/orchestrator/graph_runtime/store.py:873:25: GraphEventStore.advance_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:874:14: GraphEventStore.advance_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1276:22: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1277:22: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1278:17: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1279:22: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1280:25: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1281:26: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1283:25: _assign_projection_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1329:36: _decisions_with_projection_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
src/orchestrator/graph_runtime/store.py:1330:34: _decisions_with_projection_checkpoint: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/integration/test_graph_event_store.py:87:21: _rebuild_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/integration/test_graph_event_store.py:88:4: _rebuild_projection: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/integration/test_graph_gatekeeper_flow.py:397:21: test_gatekeeper_secret_verdict_scrubs_compromised_snapshot: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/integration/test_graph_node_detail_read_models.py:671:44: test_incremental_rich_lease_summaries_match_rebuild_and_canonical_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/integration/test_graph_routine_compile.py:51:11: test_routine_corpus_loads_and_compiles_cleanly: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/integration/test_graph_routine_compile.py:141:11: test_dynamic_graph_feature_compiles_to_single_initial_planner_head: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/integration/test_graph_routine_compile.py:142:11: test_dynamic_graph_feature_compiles_to_single_initial_planner_head: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/integration/test_graph_routine_compile.py:144:42: test_dynamic_graph_feature_compiles_to_single_initial_planner_head: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
tests/integration/test_graph_routine_compile.py:416:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/integration/test_graph_routine_compile.py:442:34: _count_nodes: unsupported_call: projection field method values is unsupported; replace the dynamic call with a typed projection query
tests/unit/test_artifact_prompt_hydration.py:80:14: test_default_planner_evidence_keeps_check_output_tails_without_references: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_artifact_prompt_hydration.py:96:15: test_default_planner_evidence_keeps_check_output_tails_without_references: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_callbacks.py:147:13: test_projected_prior_rejection_does_not_return_duplicate: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_final_review_contracts.py:378:11: test_canonical_lifecycle_serialization_preserves_reducer_semantics: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_commands.py:48:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_commands.py:49:4: _project: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/unit/test_graph_compiler.py:701:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_compiler.py:702:4: _project: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/unit/test_graph_dispatch_on_output.py:104:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_gatekeeper.py:545:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_gatekeeper.py:546:4: _project: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/unit/test_graph_macros.py:100:13: test_gap_planner_corrective_region_macro_expands_to_valid_patch: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_macros.py:141:13: test_create_join_macro_uses_distinct_source_record_ports: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_macros.py:243:21: test_submit_patch_command_accepts_macro_invocations: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_macros.py:246:11: test_submit_patch_command_accepts_macro_invocations: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_macros.py:247:11: test_submit_patch_command_accepts_macro_invocations: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_parent_child_translation.py:475:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_parent_child_translation.py:476:4: _project: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/unit/test_graph_planner.py:832:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_planner.py:833:4: _project: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/unit/test_graph_planner_packet.py:47:21: _projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_planner_packet.py:53:11: _planner_context: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_planner_packet.py:83:11: _gap_planner_context: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_planner_session.py:294:21: _project: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_planner_session.py:295:4: _project: unsupported_binding: projection escapes through an unresolved return annotation; retain the GraphProjection annotation through this binding
tests/unit/test_graph_projection_inventory.py:173:11: test_resource_claim_query_returns_an_immutable_sequence: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projection_inventory.py:174:11: test_resource_claim_query_returns_an_immutable_sequence: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:239:42: test_callback_idempotency_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:360:42: test_decision_projection_checkpoint_round_trips_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:450:21: test_decision_view_behavior_is_preserved_with_typed_decision_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:451:42: test_decision_view_behavior_is_preserved_with_typed_decision_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:494:21: test_decision_request_details_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:499:42: test_decision_request_details_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:594:42: test_environment_failure_projection_checkpoint_round_trips_check_result_record: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:651:17: test_file_state_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:652:17: test_file_state_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:665:42: test_file_state_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:747:42: test_task_candidate_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:802:42: test_verifier_verdict_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:859:42: test_requirement_revision_projection_uses_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:884:21: test_support_evidence_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:886:42: test_support_evidence_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:960:42: test_oversight_decision_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1038:11: test_malformed_file_state_payload_is_tolerated_without_raw_projection_entry: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:1154:11: test_node_creation_projection_retains_first_typed_retry_limit: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:1161:13: test_clone_projection_covers_initial_keys_without_nested_aliasing: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1165:11: test_clone_projection_covers_initial_keys_without_nested_aliasing: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:1185:42: test_node_creation_projection_checkpoint_round_trips_typed_payload: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1207:11: test_malformed_node_created_payload_is_tolerated_without_raw_projection_entry: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:1208:11: test_malformed_node_created_payload_is_tolerated_without_raw_projection_entry: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:1253:21: test_input_binding_replay_accumulates_many_cardinality_records: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1301:21: test_edge_projection_uses_typed_payload_and_preserves_topology_shape: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1364:21: test_input_binding_projection_uses_typed_payload_and_drops_raw_event_extras: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1403:21: test_edge_and_input_binding_projection_checkpoint_round_trips_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1405:42: test_edge_and_input_binding_projection_checkpoint_round_trips_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1805:8: test_invalid_persisted_edge_selector_raises_projection_error: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1819:16: test_replay_determinism: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1820:17: test_replay_determinism: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1822:11: test_replay_determinism: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:1853:11: test_lease_projection_uses_typed_payload_and_preserves_public_shape: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1865:11: test_lease_projection_uses_typed_payload_and_preserves_public_shape: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1891:42: test_lease_projection_checkpoint_round_trips_typed_payload_and_drops_malformed_entries: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1987:21: test_output_record_checkpoint_round_trip_preserves_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:1989:42: test_output_record_checkpoint_round_trip_preserves_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2027:21: test_verification_result_projections_are_typed_at_fold: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2048:21: test_canonical_verification_result_payload_projects_required_identifiers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2050:11: test_canonical_verification_result_payload_projects_required_identifiers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2051:11: test_canonical_verification_result_payload_projects_required_identifiers: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2058:17: test_verification_result_checkpoint_round_trip_preserves_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2071:42: test_verification_result_checkpoint_round_trip_preserves_typed_payloads: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2137:42: test_sparse_check_result_fixture_is_completed_to_a_canonical_failed_summary: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2161:42: test_check_result_checkpoint_round_trip_preserves_typed_summary: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2274:33: test_graph_projection_derived_indexes_match_legacy_event_scan.append_command: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2275:27: test_graph_projection_derived_indexes_match_legacy_event_scan.append_command: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2446:21: test_graph_projection_derived_indexes_match_legacy_event_scan: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2453:8: test_graph_projection_derived_indexes_match_legacy_event_scan: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2458:33: test_graph_projection_derived_indexes_match_legacy_event_scan: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2460:11: test_graph_projection_derived_indexes_match_legacy_event_scan: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2515:21: test_residual_command_projection_fields_fold_incrementally: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2517:11: test_residual_command_projection_fields_fold_incrementally: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2518:11: test_residual_command_projection_fields_fold_incrementally: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2521:33: test_residual_command_projection_fields_fold_incrementally: unsupported_call: projection field method items is unsupported; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2530:11: test_residual_command_projection_fields_fold_incrementally: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2531:11: test_residual_command_projection_fields_fold_incrementally: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2536:11: test_residual_command_projection_fields_fold_incrementally: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2559:21: test_cleanup_requested_events_checkpoint_round_trips_typed_envelopes: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2569:17: test_cleanup_requested_events_checkpoint_round_trips_typed_envelopes: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2665:16: test_support_evidence_freshness_can_be_queried_from_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2667:11: test_support_evidence_freshness_can_be_queried_from_projection: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2880:17: test_projection_immutability: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:2885:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2886:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2887:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2888:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2889:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2890:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:2928:11: test_projection_immutability: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:3634:21: test_failed_check_result_blocks_projected_completion_after_task_acceptance: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:3971:26: test_task_state_projection_matches_full_projection_for_recovery_supersession: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:3973:11: test_task_state_projection_matches_full_projection_for_recovery_supersession: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:4116:21: test_check_result_candidate_id_does_not_replace_latest_task_candidate: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:4436:17: test_run_unknown_event_ignored: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:4438:11: test_run_unknown_event_ignored: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:4439:11: test_run_unknown_event_ignored: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_graph_projections.py:4696:21: test_invalid_test_block_projection_uses_typed_payload_and_preserves_task_state_behavior: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_graph_projections.py:4721:42: test_invalid_test_block_checkpoint_round_trips_typed_payload_and_drops_malformed_entries: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_node_created_event_payloads.py:80:11: test_node_created_reducer_reads_direct_membership_fields: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_created_event_payloads.py:81:11: test_node_created_reducer_reads_direct_membership_fields: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_created_event_payloads.py:178:11: test_explicit_empty_authority_change_controls_override_nested_authority: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_created_event_payloads.py:179:11: test_explicit_empty_authority_change_controls_override_nested_authority: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_created_event_payloads.py:180:11: test_explicit_empty_authority_change_controls_override_nested_authority: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_lifecycle_event_payloads.py:55:11: test_authority_reducer_reads_direct_fields: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_lifecycle_event_payloads.py:56:11: test_authority_reducer_reads_direct_fields: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_usage_events.py:37:13: test_record_node_usage_emits_one_idempotent_fact_per_execution_model: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_node_usage_events.py:138:21: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_node_usage_events.py:140:11: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_usage_events.py:141:11: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_usage_events.py:142:11: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_usage_events.py:143:11: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_usage_events.py:144:11: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_node_usage_events.py:146:42: test_node_usage_reducer_deduplicates_facts_and_counts_execution_latency_once: unsupported_call: projection escapes through an unrecognized callable; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:109:13: test_required_pass_gated_final_check_from_recoverable_verifier_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:185:13: test_patch_stale_neutral_events_only_accepted: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:202:13: test_patch_stale_invalidating_event_in_read_set_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:224:13: test_patch_stale_invalidating_event_not_in_read_set_accepted: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:297:13: test_planner_cannot_create_check_with_hidden_oracle_command: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:339:13: test_planner_can_create_check_with_command_definition: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:377:13: test_planner_can_create_check_with_dynamic_feature_oracle_binding: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:499:13: test_create_edge_accepts_revision_attempt_embedded_worker_in_same_patch: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:535:13: test_create_edge_accepts_revision_attempt_embedded_worker_with_default_kind: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:570:13: test_create_edge_accepts_producer_class_source: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:820:13: test_create_edge_rejects_new_cycle: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:940:13: test_gap_planner_no_op_allowed_when_classified_gap_successor_waits: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1065:13: test_set_resource_claims_escalation_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1094:13: test_set_resource_claims_narrowing_accepted: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1292:13: test_retire_running_node_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1303:13: test_retire_planned_node_accepted: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1312:13: test_gap_planner_cannot_retire_executable_node: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1396:13: test_edge_unknown_port_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1422:13: test_edge_selector_incompatible_with_source_port_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_patch_validator.py:1459:13: test_multi_op_patch_one_fails_rejected: unsupported_call: projection escapes through a non-projection or ambiguous callable parameter; replace the dynamic call with a typed projection query
tests/unit/test_planner_session_event_payloads.py:53:11: test_planner_session_reducer_preserves_explicit_null_carryover: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_record_routing_event_payloads.py:113:11: test_verification_replay_ignores_contradictory_outcome: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_record_routing_event_payloads.py:114:11: test_verification_replay_ignores_contradictory_outcome: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_record_routing_event_payloads.py:115:11: test_verification_replay_ignores_contradictory_outcome: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_w5_compatibility_removal.py:66:11: test_output_replay_requires_exact_record_type_discriminator: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_w5_compatibility_removal.py:87:11: test_output_replay_rejects_unknown_nonempty_discriminator: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
tests/unit/test_w5_compatibility_removal.py:195:11: test_verification_record_rejects_unknown_nested_fields: unsupported_comparison: projection comparison is unsupported; compare an explicit typed projection field
```
