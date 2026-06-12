| PRD section | Row | Fixture |
|---|---|---|
| §10.1 | draft -> queued | run_lifecycle.yaml::run_draft_to_queued |
| §10.1 | queued -> active | run_lifecycle.yaml::run_queued_to_active |
| §10.1 | active -> pausing | run_lifecycle.yaml::run_active_to_pausing |
| §10.1 | pausing -> paused | run_lifecycle.yaml::run_pausing_to_paused |
| §10.1 | paused -> resuming | run_lifecycle.yaml::run_paused_to_resuming |
| §10.1 | resuming -> active | run_lifecycle.yaml::run_resuming_to_active |
| §10.1 | active/paused -> cancelling | run_lifecycle.yaml::run_active_to_cancelling |
| §10.1 | cancelling -> cancelled | run_lifecycle.yaml::run_cancelling_to_cancelled |
| §10.1 | active -> completed | run_lifecycle.yaml::run_active_to_completed |
| §10.1 | any nonterminal -> failed | run_lifecycle.yaml::run_nonterminal_to_failed |
| §10.1 | illegal complete from queued rejected | run_lifecycle.yaml::run_illegal_complete_from_queued_rejected |
| §10.1 | resume after cancel rejected | run_lifecycle.yaml::run_resume_after_cancel_rejected |
| §14 | accepted | task_projection.yaml::task_projection_accepted |
| §14 | configured gate requires approval | tests/unit/test_graph_projections.py::test_task_projection_configured_gate_requires_decision |
| §14 | needs_revision | task_projection.yaml::task_projection_needs_revision |
| §14 | active invalid-test appeal overrides failure | tests/unit/test_graph_projections.py::test_task_projection_active_appeal_overrides_latest_failure |
| §14 | blocked_invalid_test | task_projection.yaml::task_projection_blocked_invalid_test |
| §14 | replacement verification exits invalid-test block | tests/unit/test_graph_projections.py::test_task_projection_invalid_test_block_exits_after_replacement_pass |
| §14 | blocked_environment | task_projection.yaml::task_projection_blocked_environment |
| §14 | in_progress | task_projection.yaml::task_projection_in_progress |
| §14 | pending | task_projection.yaml::task_projection_pending |
| §14 | latest candidate event-position tie-break | tests/unit/test_graph_projections.py::test_task_projection_latest_candidate_position_tiebreak |
| §15.1 | worker planned -> ready | node_lifecycle_worker.yaml::worker_planned_to_ready |
| §15.1 | worker ready -> leased | node_lifecycle_worker.yaml::worker_ready_to_leased |
| §15.1 | worker leased -> running | node_lifecycle_worker.yaml::worker_leased_to_running |
| §15.1 | worker running -> completed | node_lifecycle_worker.yaml::worker_running_to_completed |
| §15.1 | worker running -> suspended | node_lifecycle_worker.yaml::worker_running_to_suspended |
| §15.1 | worker suspended -> leased | node_lifecycle_worker.yaml::worker_suspended_to_leased |
| §15.1 | worker running -> failed | node_lifecycle_worker.yaml::worker_running_to_failed |
| §15.1 | worker planned/ready -> retired | node_lifecycle_worker.yaml::worker_planned_to_retired |
| §15.2 | verifier planned -> ready | node_lifecycle_verifier.yaml::verifier_planned_to_ready |
| §15.2 | verifier ready -> leased | node_lifecycle_verifier.yaml::verifier_ready_to_leased |
| §15.2 | verifier leased -> running | node_lifecycle_verifier.yaml::verifier_leased_to_running |
| §15.2 | verifier running -> completed pass | node_lifecycle_verifier.yaml::verifier_running_to_completed_pass |
| §15.2 | verifier running -> completed failure | node_lifecycle_verifier.yaml::verifier_running_to_completed_failure |
| §15.2 | verifier running -> failed | node_lifecycle_verifier.yaml::verifier_running_to_failed |
| §15.3 | check planned -> ready | node_lifecycle_check.yaml::check_planned_to_ready |
| §15.3 | check ready -> leased | node_lifecycle_check.yaml::check_ready_to_leased |
| §15.3 | check leased -> running | node_lifecycle_check.yaml::check_leased_to_running |
| §15.3 | check running -> completed | node_lifecycle_check.yaml::check_running_to_completed |
| §15.3 | check running -> failed | node_lifecycle_check.yaml::check_running_to_failed |
| §15.3 | failed plus recovery node created | node_lifecycle_check.yaml::check_failed_creates_recovery |
| §15.4 | gate planned -> ready | node_lifecycle_gate.yaml::gate_planned_to_ready |
| §15.4 | gate ready -> blocked | node_lifecycle_gate.yaml::gate_ready_to_blocked |
| §15.4 | gate blocked -> completed approval | node_lifecycle_gate.yaml::gate_blocked_to_completed_approved |
| §15.4 | gate blocked -> completed rejection | node_lifecycle_gate.yaml::gate_blocked_to_completed_rejected |
| §15.5 | appeal planned -> ready | node_lifecycle_appeal.yaml::appeal_planned_to_ready |
| §15.5 | appeal ready -> completed | node_lifecycle_appeal.yaml::appeal_ready_to_completed |
| §15.5 | appeal ready -> failed | node_lifecycle_appeal.yaml::appeal_ready_to_failed |
| §15.6 | planner planned -> ready | node_lifecycle_planner.yaml::planner_planned_to_ready |
| §15.6 | planner ready -> leased | node_lifecycle_planner.yaml::planner_ready_to_leased |
| §15.6 | planner leased -> running | node_lifecycle_planner.yaml::planner_leased_to_running |
| §15.6 | planner running -> completed | node_lifecycle_planner.yaml::planner_running_to_completed |
| §15.6 | planner running -> failed | node_lifecycle_planner.yaml::planner_running_to_failed |
| §15.6 | planner completion independent of patch acceptance | node_lifecycle_planner.yaml::planner_completed_patch_rejected_stays_completed |
| §15.7 | review planned -> ready | node_lifecycle_review.yaml::review_planned_to_ready |
| §15.7 | review ready -> leased | node_lifecycle_review.yaml::review_ready_to_leased |
| §15.7 | review ready -> blocked | node_lifecycle_review.yaml::review_ready_to_blocked |
| §15.7 | review leased -> running | node_lifecycle_review.yaml::review_leased_to_running |
| §15.7 | review running -> completed | node_lifecycle_review.yaml::review_running_to_completed |
| §15.7 | review running -> failed | node_lifecycle_review.yaml::review_running_to_failed |
| §16 | stale neutral lease accepted | patch_validator.yaml::patch_stale_neutral_lease_accepted |
| §16 | stale neutral heartbeat accepted | patch_validator.yaml::patch_stale_neutral_heartbeat_accepted |
| §16 | stale requirement in read-set rejected | patch_validator.yaml::patch_stale_requirement_in_read_set_rejected |
| §16 | stale retired region rejected | patch_validator.yaml::patch_stale_retired_region_rejected |
| §16 | planner create gate rejected | patch_validator.yaml::patch_planner_create_gate_rejected |
| §16 | resource claim escalation rejected | patch_validator.yaml::patch_resource_claim_escalation_rejected |
| §16 | accepted v1 patch ops emit graph events | tests/unit/test_graph_commands.py::test_patch_accept_emits_events_for_all_v1_ops |
| §17 | single planned node becomes ready | readiness.yaml::readiness_single_node_planned_to_ready |
| §17 | blocked node becomes ready | readiness.yaml::readiness_blocked_node_becomes_ready |
| §17 | multiple independent nodes become ready | readiness.yaml::readiness_multiple_nodes_independent |
| §17 | write node blocked by active write | readiness.yaml::readiness_write_node_blocked_by_active_write |
| §17 | read node compatible with active read | readiness.yaml::readiness_read_node_compatible_with_read |
| §17 | gate blocked until input | readiness.yaml::readiness_gate_blocked_until_input |
| §17 | retired node not eligible | readiness.yaml::readiness_retired_node_not_eligible |
| §17 | inactive run prevents scheduling | readiness.yaml::readiness_run_not_active_no_scheduling |
| §18 | path rule: repository-relative POSIX paths | tests/unit/test_scheduler.py::test_path_escape_is_treated_as_conflicting |
| §18 | path rule: normalize dot and dotdot | tests/unit/test_scheduler.py::test_path_normalization_resolves_dot_dot_inside_repo |
| §18 | path rule: deterministic glob handling | tests/unit/test_scheduler.py::test_glob_path_overlap_detects_file_under_recursive_glob |
| §18 | path rule: directory claims expand recursively | tests/unit/test_scheduler.py::test_directory_claim_matches_recursively |
| §18 | read x read | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | read x write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | read x graph_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | read x review_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | read x external | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | write x read | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | write x write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | write x graph_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | write x review_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | write x external | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | graph_write x read | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | graph_write x write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | graph_write x graph_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | graph_write x review_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | graph_write x external | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | review_write x read | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | review_write x write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | review_write x graph_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | review_write x review_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | review_write x external | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | external x read | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | external x write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | external x graph_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | external x review_write | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18 | external x external | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18.1 | external claim missing key conflicts conservatively | tests/unit/test_scheduler.py::test_external_missing_key_conflicts_conservatively |
| §18.1 | external claim missing key invalid for readiness | tests/unit/test_scheduler.py::test_evaluate_readiness_external_claim_missing_key_invalid |
| §18.1 | external claim missing key rejected by model | tests/unit/test_graph_models.py::test_external_resource_claim_requires_key |
| §18.2 | many stable snapshot readers may run | tests/unit/test_scheduler.py::test_claims_read_read_compatible |
| §18.2 | write requires exclusive worktree lease | tests/unit/test_scheduler.py::test_schedule_decision_has_deferred_reasons |
| §18.2 | live reader cannot run during writer | tests/unit/test_scheduler.py::test_live_read_during_write_is_deferred_both_directions |
| §18.2 | immutable snapshot reader may run during writer | tests/unit/test_scheduler.py::test_snapshot_read_during_write_is_compatible_both_directions |
| §18.2 | graph patch application is single-threaded | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §18.2 | destructive review operations require exclusive write authority | tests/unit/test_scheduler.py::test_resource_conflict_matrix_cells |
| §19 | duplicate same key and same payload | stale_callbacks.yaml::stale_duplicate_same_payload |
| §19 | duplicate same key and different payload | stale_callbacks.yaml::stale_duplicate_different_payload |
| §19 | callback for revoked lease | stale_callbacks.yaml::stale_callback_for_revoked_lease |
| §19 | callback for old lease generation | stale_callbacks.yaml::stale_callback_for_old_generation |
| §19 | callback execution identity mismatch rejected | tests/unit/test_callbacks.py::test_execution_mismatch_rejected |
| §19 | callback snapshot mismatch rejected as snapshot_incompatible via callback_rejected_stale | invariants.yaml::invariant_snapshot_mismatch_not_consumed |
| §19 | success after node already retried | stale_callbacks.yaml::stale_success_after_retry |
| §19 | failure after node completed | stale_callbacks.yaml::stale_failure_after_completed |
| §19 | approval after cancellation | stale_callbacks.yaml::stale_approval_after_cancellation |
| §19 | resume after cancel | stale_callbacks.yaml::stale_resume_after_cancel |
| §19 | pause and callback race callback first | stale_callbacks.yaml::stale_pause_callback_race_callback_first |
| §19 | pause and callback race pause first | stale_callbacks.yaml::stale_pause_callback_race_pause_first |
| §19 | schedule tick emits lease_expired | tests/unit/test_graph_commands.py::test_schedule_tick_expires_past_leases_only |
| §27.2 | replaying same event stream is deterministic | invariants.yaml::invariant_replay_is_deterministic |
| §27.2 | no conflicting write leases active | invariants.yaml::invariant_no_conflicting_write_leases |
| §27.2 | no callback without valid lease alters outcome | invariants.yaml::invariant_no_callback_without_valid_lease |
| §27.2 | successor cannot release before inputs | invariants.yaml::invariant_successor_requires_inputs |
| §27.2 | retired nodes cannot become running | invariants.yaml::invariant_retired_nodes_cannot_run |
| §27.2 | planner cannot grant out-of-scope authority | invariants.yaml::invariant_planner_authority_scoped |
| §27.2 | verification failure preserves builder facts | invariants.yaml::invariant_verification_failure_preserves_builder |
| §27.2 | reader output bound to incompatible snapshot rejected | invariants.yaml::invariant_snapshot_mismatch_not_consumed |
| §27.2 | human approval gates block successors | invariants.yaml::invariant_human_gate_blocks_successors |
| §27.2 | file-state rejects undeclared residue | invariants.yaml::invariant_file_state_rejects_residue |
