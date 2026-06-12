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
| §14 | accepted | task_projection.yaml::task_projection_accepted |
| §14 | needs_revision | task_projection.yaml::task_projection_needs_revision |
| §14 | blocked_invalid_test | task_projection.yaml::task_projection_blocked_invalid_test |
| §14 | blocked_environment | task_projection.yaml::task_projection_blocked_environment |
| §14 | in_progress | task_projection.yaml::task_projection_in_progress |
| §14 | pending | task_projection.yaml::task_projection_pending |
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
| §17 | single planned node becomes ready | readiness.yaml::readiness_single_node_planned_to_ready |
| §17 | blocked node becomes ready | readiness.yaml::readiness_blocked_node_becomes_ready |
| §17 | multiple independent nodes become ready | readiness.yaml::readiness_multiple_nodes_independent |
| §17 | write node blocked by active write | readiness.yaml::readiness_write_node_blocked_by_active_write |
| §17 | read node compatible with active read | readiness.yaml::readiness_read_node_compatible_with_read |
| §17 | gate blocked until input | readiness.yaml::readiness_gate_blocked_until_input |
| §17 | retired node not eligible | readiness.yaml::readiness_retired_node_not_eligible |
| §17 | inactive run prevents scheduling | readiness.yaml::readiness_run_not_active_no_scheduling |
| §19 | duplicate same key and same payload | stale_callbacks.yaml::stale_duplicate_same_payload |
| §19 | duplicate same key and different payload | stale_callbacks.yaml::stale_duplicate_different_payload |
| §19 | callback for revoked lease | stale_callbacks.yaml::stale_callback_for_revoked_lease |
| §19 | callback for old lease generation | stale_callbacks.yaml::stale_callback_for_old_generation |
| §19 | success after node already retried | stale_callbacks.yaml::stale_success_after_retry |
| §19 | failure after node completed | stale_callbacks.yaml::stale_failure_after_completed |
| §19 | approval after cancellation | stale_callbacks.yaml::stale_approval_after_cancellation |
| §19 | resume after cancel | stale_callbacks.yaml::stale_resume_after_cancel |
| §19 | pause and callback race callback first | stale_callbacks.yaml::stale_pause_callback_race_callback_first |
| §19 | pause and callback race pause first | stale_callbacks.yaml::stale_pause_callback_race_pause_first |
| §27.2 | replaying same event stream is deterministic | invariants.yaml::invariant_replay_is_deterministic |
| §27.2 | no conflicting write leases active | invariants.yaml::invariant_no_conflicting_write_leases |
| §27.2 | no callback without valid lease alters outcome | invariants.yaml::invariant_no_callback_without_valid_lease |
| §27.2 | successor cannot release before inputs | invariants.yaml::invariant_successor_requires_inputs |
| §27.2 | retired nodes cannot become running | invariants.yaml::invariant_retired_nodes_cannot_run |
| §27.2 | planner cannot grant out-of-scope authority | invariants.yaml::invariant_planner_authority_scoped |
| §27.2 | verification failure preserves builder facts | invariants.yaml::invariant_verification_failure_preserves_builder |
| §27.2 | reader output bound to S0 not consumed for S1 | invariants.yaml::invariant_snapshot_mismatch_not_consumed |
| §27.2 | human approval gates block successors | invariants.yaml::invariant_human_gate_blocks_successors |
| §27.2 | file-state rejects undeclared residue | invariants.yaml::invariant_file_state_rejects_residue |
