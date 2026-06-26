# Dynamic Graph Proof Ledger

This is the source of truth for current dynamic graph work. Progress is measured
by validated functional requirements from
`docs/dynamic-graph/typed-work-graph-requirements.md`, not by implementation
slices, clean tests, or static checks.

Tests are regression evidence only. A row is not `validated` unless the dynamic
graph feature has been used through the product path it is meant to support: an
orchestrator-created graph run, driven through the graph workflow/API/runtime
surface, with observable graph events/readbacks showing the required behavior.

Older status logs, run ledgers, and comparison plans are archived in
`docs/dynamic-graph/complete/`.

The current remaining-work and proof-scenario update is available as
`docs/dynamic-graph/remaining-fr-validation-plan.html`. It summarizes the
remaining FR proof clusters, the systemic testing gaps that let product-path
bugs escape isolated tests, and the minimal state-pack/product scenarios needed
to close the ledger without repeatedly rerunning broad dogfood tasks.

## Current Regression Evidence

Regression checks are useful guardrails, not validation:

```bash
uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 716 passed in 13.97s, before the latest dispatch fix

uv run pytest tests/unit/test_scheduler.py tests/unit/test_graph_commands.py tests/unit/test_graph_scheduler_view.py -q
# 145 passed, before the latest dispatch fix

uv run pytest tests/unit/test_graph_dispatch_on_output.py -q
# 28 passed in 2.18s, after the latest dispatch fix

uv run pytest tests/unit/test_graph_dispatch_on_output.py::test_execute_check_command_cites_bound_verification_and_region_file_state tests/unit/test_graph_projections.py::test_check_result_candidate_id_does_not_replace_latest_task_candidate tests/integration/test_graph_event_store.py::test_read_run_light_preserves_projection_fields_without_heavy_payloads -q
# 3 passed in 2.12s

uv run pytest tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py -q
# 215 passed in 6.02s

uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/file_state.py src/orchestrator/graph_runtime/store.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py tests/unit/test_graph_dispatch_on_output.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py
# All checks passed

uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph_runtime/file_state.py src/orchestrator/graph_runtime/store.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_scheduler_view.py::test_scheduler_view_buckets_ready_resource_deferral -q
# 1 passed in 0.93s

uv run pytest tests/integration/test_graph_scheduler_api.py tests/unit/test_graph_scheduler_view.py -q
# 6 passed in 2.03s

uv run pytest tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_event_store.py tests/integration/test_graph_scheduler_api.py tests/unit/test_graph_scheduler_view.py -q
# 34 passed in 2.55s

uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py -q
# 185 passed in 5.02s

uv run pytest tests/unit/test_scheduler.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_event_store.py tests/integration/test_graph_scheduler_api.py tests/unit/test_graph_scheduler_view.py -q
# 77 passed in 2.92s

uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_event_store.py -q
# 185 passed in 5.78s

uv run ruff check src/orchestrator/graph_runtime/store.py src/orchestrator/graph/projections.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_event_store.py tests/integration/test_graph_scheduler_api.py
# All checks passed

uv run pyright src/orchestrator/graph_runtime/store.py src/orchestrator/graph/projections.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_event_store.py tests/integration/test_graph_scheduler_api.py
# 0 errors, 0 warnings, 0 informations

uv run ruff check src/orchestrator/graph/scheduler.py tests/unit/test_scheduler.py tests/integration/test_graph_scheduler_api.py src/orchestrator/graph_runtime/store.py src/orchestrator/graph/projections.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_event_store.py
# All checks passed

uv run pyright src/orchestrator/graph/scheduler.py src/orchestrator/graph_runtime/store.py src/orchestrator/graph/projections.py tests/unit/test_scheduler.py tests/integration/test_graph_scheduler_api.py tests/integration/test_graph_api.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_event_store.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 757 passed in 12.42s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 759 passed in 14.07s

uv run pytest tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries -q
# 1 passed in 2.31s

uv run ruff check src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py tests/integration/test_graph_node_detail_read_models.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py src/orchestrator/graph_runtime/store.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/integration/test_graph_runner_e2e.py::test_reconcile_runtime_skips_lease_already_recovered_by_another_driver tests/integration/test_graph_runner_e2e.py::test_graph_runner_restart_marks_missing_builder_dead_and_redispatches -q
# 2 passed in 2.92s

uv run ruff check src/orchestrator/graph_runtime/controller.py src/orchestrator/graph_runtime/dispatch.py tests/integration/test_graph_runner_e2e.py
# All checks passed

uv run pyright src/orchestrator/graph_runtime/controller.py src/orchestrator/graph_runtime/dispatch.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/integration/test_graph_api.py::test_graph_projection_uses_paused_run_row_as_effective_state tests/integration/test_graph_api.py::test_graph_projection_reflects_seeded_events -q
# 2 passed in 2.53s

uv run ruff check src/orchestrator/api/routers/graph.py tests/integration/test_graph_api.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 759 passed in 13.57s, before the 2026-06-22 control/readback product probes

uv run pytest tests/unit/test_signal_consumer.py::test_cancel_graph_run_appends_graph_cancel_before_run_row_failure tests/unit/test_graph_commands.py::test_cancel_revokes_active_lease_and_cancels_running_node tests/integration/test_graph_run_start_routing.py tests/integration/test_graph_scheduler_api.py tests/integration/test_graph_node_detail_read_models.py -q
# 19 passed in 2.81s

uv run ruff check src/orchestrator/api/routers/runs.py src/orchestrator/workflow/signals/consumer.py tests/unit/test_signal_consumer.py
# All checks passed

uv run pyright src/orchestrator/api/routers/runs.py src/orchestrator/workflow/signals/consumer.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 759 passed in 14.08s, after the 2026-06-22 graph cancel hardening and product-proof ledger refresh

uv run pytest tests/integration/test_graph_run_start_routing.py::test_graph_cancel_route_appends_graph_cancel_before_signal_drain tests/unit/test_signal_consumer.py::test_cancel_graph_run_appends_graph_cancel_before_run_row_failure tests/unit/test_graph_commands.py::test_cancel_revokes_active_lease_and_cancels_running_node -q
# 3 passed in 2.39s

uv run ruff check src/orchestrator/api/routers/runs.py src/orchestrator/workflow/graph_driver.py src/orchestrator/workflow/signals/consumer.py tests/integration/test_graph_run_start_routing.py tests/unit/test_signal_consumer.py
# All checks passed

uv run pyright src/orchestrator/api/routers/runs.py src/orchestrator/workflow/graph_driver.py src/orchestrator/workflow/signals/consumer.py tests/integration/test_graph_run_start_routing.py tests/unit/test_signal_consumer.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 760 passed in 14.51s, after terminal graph cancel and cancel-response readback hardening

uv run pytest tests/integration/test_graph_node_detail_read_models.py::test_check_node_detail_summary_derives_command_precondition tests/integration/test_graph_node_detail_read_models.py::test_node_detail_summary_matches_existing_light_builder tests/integration/test_graph_node_detail_read_models.py::test_append_creates_and_updates_node_detail_summaries -q
# 3 passed in 2.11s

uv run ruff check src/orchestrator/api/routers/graph.py tests/integration/test_graph_node_detail_read_models.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py tests/integration/test_graph_node_detail_read_models.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 761 passed in 14.45s, after check-node precondition summary readback fix

uv run pytest tests/unit/test_graph_commands.py::test_lifecycle_complete_accepts_clean_graph_without_blockers tests/unit/test_graph_commands.py::test_evaluate_final_gate_emits_blocked_completion_decision tests/unit/test_graph_commands.py::test_lifecycle_complete_rejected_when_final_gate_has_no_completion_decision tests/unit/test_graph_projections.py::test_failed_check_result_blocks_projected_completion_after_task_acceptance tests/unit/test_graph_projections.py::test_final_gate_requires_passed_completion_decision_for_projected_completion -q
# 5 passed in 0.91s, after failed-final-invariant product proof and completion-decision scope update

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 761 passed in 14.64s, after failed-final-invariant product proof and completion-decision scope update

uv run ruff check src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py src/orchestrator/api/routers/graph.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_dynamic_e2e.py
# All checks passed

uv run pyright src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py src/orchestrator/api/routers/graph.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_dynamic_e2e.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/integration/test_graph_decisions_api.py tests/unit/test_graph_commands.py::test_record_decision_accepts_authority_request_with_typed_record tests/unit/test_graph_commands.py::test_record_decision_rejects_authority_for_non_authority_target -q
# 6 passed in 2.71s, after adding the graph decision API bridge and authority target guard

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 764 passed in 14.64s, after the graph decision API bridge and authority target guard

uv run ruff check src/orchestrator/api/routers/graph.py src/orchestrator/graph/commands.py tests/integration/test_graph_decisions_api.py tests/unit/test_graph_commands.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py src/orchestrator/graph/commands.py tests/integration/test_graph_decisions_api.py tests/unit/test_graph_commands.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_dynamic_contract.py::test_worker_contract_accepts_authority_decision_input tests/unit/test_graph_dynamic_contract.py::test_authority_request_edge_to_worker_authority_port_is_valid tests/unit/test_graph_commands.py::test_patch_accepts_authority_request_edge_to_worker_authority_input tests/unit/test_scheduler.py::test_evaluate_readiness_authority_request_input_must_be_granted tests/unit/test_scheduler.py::test_evaluate_readiness_granted_authority_request_input_passes -q
# 5 passed in 1.05s, after authority-request product probes exposed the missing worker authority input contract

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 767 passed in 14.91s, after authority input contract regression coverage

uv run ruff check src/orchestrator/graph/contracts.py tests/unit/test_graph_dynamic_contract.py tests/unit/test_graph_commands.py
# All checks passed

uv run pyright src/orchestrator/graph/contracts.py tests/unit/test_graph_dynamic_contract.py tests/unit/test_graph_commands.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/integration/test_graph_runner_e2e.py::test_graph_dispatch_carries_projection_base_snapshot_id_to_callback tests/integration/test_graph_runner_e2e.py::test_graph_runner_exception_appends_agent_died_and_releases_retry tests/unit/test_graph_commands.py::test_record_heartbeat_renews_active_lease tests/unit/test_graph_commands.py::test_cancel_revokes_active_lease_and_cancels_running_node tests/unit/test_graph_commands.py::test_patch_rejected_after_run_cancellation tests/unit/test_codex_server_common.py::test_lifecycle_and_artifact_callbacks_are_not_agent_routable_tools -q
# 8 passed in 2.79s, after runtime-owned graph dispatch heartbeat and post-cancel submit_patch guard

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 768 passed in 29.93s, after runtime-owned graph dispatch heartbeat and post-cancel submit_patch guard

uv run pytest tests/unit/test_codex_server_common.py::test_planner_macros_are_exposed_with_typed_schemas tests/unit/test_graph_commands.py::test_patch_accepts_authority_request_typed_record_envelope tests/unit/test_graph_commands.py::test_record_decision_binds_authority_decision_to_worker_input tests/unit/test_graph_commands.py::test_schedule_tick_allows_granted_authority_request_input tests/integration/test_graph_decisions_api.py::test_record_authority_decision_updates_decision_readback tests/integration/test_graph_decisions_api.py::test_record_authority_decision_binds_and_recomputes_active_scheduler -q
# 6 passed in 2.47s, after native authority-request decision binding and active scheduler recompute fixes

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 771 passed in 15.40s, after native authority-request decision binding and active scheduler recompute fixes

uv run ruff check src/orchestrator/runners/agents/codex/common.py src/orchestrator/graph/commands.py src/orchestrator/api/routers/graph.py tests/unit/test_codex_server_common.py tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py
# All checks passed

uv run pyright src/orchestrator/runners/agents/codex/common.py src/orchestrator/graph/commands.py src/orchestrator/api/routers/graph.py tests/unit/test_codex_server_common.py tests/unit/test_graph_commands.py tests/integration/test_graph_decisions_api.py
# 0 errors, 0 warnings, 0 informations

uv run ruff check src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/commands.py tests/integration/test_graph_runner_e2e.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py
# All checks passed

uv run pyright src/orchestrator/graph_runtime/dispatch.py src/orchestrator/graph/commands.py tests/integration/test_graph_runner_e2e.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_compiler.py::test_worker_write_claims_are_scoped_to_declared_artifacts tests/unit/test_graph_compiler.py::test_same_step_artifact_scoped_workers_can_schedule_without_conflict tests/integration/test_graph_runner_e2e.py::test_parallel_worker_start_acknowledgements_retry_stale_positions tests/integration/test_graph_scheduler_api.py::test_path_scoped_write_claims_can_progress_without_resource_conflict -q
# 4 passed in 2.81s, after artifact-derived path-scoped write claims and stale start-ack retry coverage

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 774 passed in 15.34s, after path-scoped write claims and stale graph start-ack retry coverage

uv run ruff check src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_compiler.py tests/integration/test_graph_runner_e2e.py tests/integration/test_graph_scheduler_api.py
# All checks passed

uv run pyright src/orchestrator/graph/compiler.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_compiler.py tests/integration/test_graph_runner_e2e.py tests/integration/test_graph_scheduler_api.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 774 passed in 14.42s, ledger-refresh baseline on 2026-06-22

uv run pytest tests/unit/test_graph_commands.py::test_callback_accepts_artifact_reference_output_record tests/unit/test_graph_commands.py::test_callback_allows_tool_cache_file_state_outside_write_scope tests/unit/test_graph_commands.py::test_callback_rejects_file_state_path_outside_lease_write_scope tests/unit/test_graph_dispatch_on_output.py::test_worker_submit_emits_declared_artifact_references tests/integration/test_graph_runner_e2e.py::test_graph_runner_exception_appends_agent_died_and_releases_retry -q
# 5 passed in 2.67s, after worker artifact-reference submit support and the tool-cache write-authority fix

uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py tests/integration/test_graph_runner_e2e.py tests/integration/test_graph_event_store.py -q
# 164 passed in 6.85s

uv run ruff check src/orchestrator/graph/contracts.py src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py
# All checks passed

uv run pyright src/orchestrator/graph/contracts.py src/orchestrator/graph/commands.py src/orchestrator/graph_runtime/dispatch.py tests/unit/test_graph_commands.py tests/unit/test_graph_dispatch_on_output.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 777 passed in 14.93s

uv run pytest tests/integration/test_graph_fr16_acceptance.py -q
# 5 passed in 5.76s, after adding the executable FR-16 acceptance harness

uv run pytest tests/integration/test_graph_fr16_acceptance.py tests/integration/test_graph_runner_e2e.py tests/unit/test_graph_commands.py::test_agent_died_fails_node_when_max_attempts_exhausted tests/unit/test_graph_commands.py::test_agent_died_rate_limit_revokes_lease_and_fails_without_retry tests/unit/test_graph_commands.py::test_record_heartbeat_renews_active_lease tests/unit/test_codex_server_common.py::test_lifecycle_and_artifact_callbacks_are_not_agent_routable_tools -q
# 21 passed in 6.23s

uv run pytest tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/integration/test_graph_event_store.py tests/integration/test_graph_runner_e2e.py tests/integration/test_graph_fr16_acceptance.py -q
# 192 passed in 6.43s

uv run ruff check src/orchestrator/graph/compiler.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py src/orchestrator/graph_runtime/dispatch.py tests/integration/test_graph_fr16_acceptance.py tests/unit/test_graph_commands.py
# All checks passed

uv run pyright src/orchestrator/graph/compiler.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py src/orchestrator/graph_runtime/dispatch.py tests/integration/test_graph_fr16_acceptance.py tests/unit/test_graph_commands.py
# 0 errors, 0 warnings, 0 informations

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 782 passed in 14.30s, after FR-16 acceptance harness and terminal failure-record callback support

uv run pytest tests/integration/test_graph_fr12_acceptance.py tests/integration/test_graph_runner_e2e.py::test_reconcile_runtime_skips_lease_already_recovered_by_another_driver tests/integration/test_graph_runner_e2e.py::test_graph_runner_restart_marks_missing_builder_dead_and_redispatches -q
# 3 passed in 2.81s, after adding the executable FR-12 recovery re-entry acceptance harness

uv run pytest tests/integration/test_graph_fr14_final_gate_acceptance.py -q
# 1 passed in 3.49s, after adding the executable final-gate completion-decision acceptance harness

uv run pytest tests/integration/test_graph_fr14_final_gate_acceptance.py tests/integration/test_graph_node_detail_read_models.py tests/integration/test_graph_api.py::test_fresh_control_and_topology_readbacks_preserve_runtime_controls tests/integration/test_graph_dynamic_e2e.py::test_dynamic_full_happy_path_completes -q
# 14 passed in 3.95s, after final-gate node-detail task-region readback and provenance hardening

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 784 passed in 15.55s, after the final-gate acceptance harness and readback fixes

uv run ruff check src/orchestrator/api/routers/graph.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py tests/integration/test_graph_fr14_final_gate_acceptance.py
# All checks passed

uv run pyright src/orchestrator/api/routers/graph.py src/orchestrator/graph/commands.py src/orchestrator/graph/projections.py tests/integration/test_graph_fr14_final_gate_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

The latest code fix in `src/orchestrator/graph_runtime/dispatch.py` is driven by
product evidence from the dogfood run, not by a blind implementation slice:
dynamic feature verifier packets now fall back to the feature acceptance
requirement when no explicit requirement nodes are bound, and rejected submit
callbacks are surfaced instead of being treated as successful agent submission.
Follow-up fixes from the same product proof prevent check results from becoming
synthetic task candidates, preserve nested check status in light graph readbacks,
and propagate check-result citations from bound verification/file-state evidence.

The resource-deferral testing gap now has a cross-surface regression oracle:
`tests/integration/test_graph_scheduler_api.py::test_resource_conflict_readback_matches_run_graph_scheduler_and_events`
seeds one active write lease plus one ready writer deferred for
`resource_conflict:write:write`, then asserts public `/api/runs`, `/graph`,
`/graph/scheduler`, and `/graph/events` agree on the graph-backed run state,
ready node, active lease, scheduler `waiting_resources` bucket, and raw
`node_deferred` event. This supports FR-10, FR-15, and FR-17 as regression
evidence only; live product proof is still required.

Path-scoped write scheduling now has controller/API regression coverage:
`tests/integration/test_graph_scheduler_api.py::test_path_scoped_write_claims_can_progress_without_resource_conflict`
drives a real `GraphController.schedule_tick` with three ready writers. Two
non-overlapping write claims for `docs/` and `tests/` are leased together, while
an overlapping `docs/api.md` writer is deferred with
`resource_conflict:write:write`; public `/graph`, `/graph/scheduler`, and
`/graph/events` readbacks agree on active leases and the waiting resource
bucket. This supports FR-11 and FR-15 as regression evidence only.

FR-11 now has row-level acceptance coverage:
`tests/integration/test_graph_fr11_acceptance.py::test_fr11_scheduler_orders_frontier_and_progresses_deferred_work`
seeds a graph-backed run with a mixed ready frontier, drives repeated
`GraphController.schedule_tick` commands through the real graph store/API path,
and asserts deterministic priority/kind lease order, `max_grants_reached`
deferrals, non-conflicting eligible agent progress, `resource_conflict:write:write`
deferral for an overlapping writer, runtime start acknowledgment, accepted
worker callback, candidate/file-state readbacks, lease release, and eventual
lease of the previously resource-blocked node after the conflicting write lease
is released. The finite fairness policy validated for FR-11 is: across repeated
schedule ticks, ready nodes are granted in deterministic priority/kind order;
ready nodes not blocked by active resource claims are not starved; and a
resource-blocked ready node is granted after the conflicting active lease
releases.

```bash
uv run pytest tests/integration/test_graph_fr11_acceptance.py -q
# 1 passed in 2.08s

uv run pytest tests/integration/test_graph_fr11_acceptance.py tests/integration/test_graph_scheduler_api.py tests/unit/test_scheduler.py tests/unit/test_graph_scheduler_view.py -q
# 50 passed in 2.97s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 785 passed in 13.99s
```

FR-08 now has row-level acceptance coverage:
`tests/integration/test_graph_fr08_acceptance.py::test_fr08_invalid_patch_matrix_rejected_and_readable`
drives rejected `submit_patch` commands through `GraphController` and verifies
public `/graph/events`, `/graph/patches`, and `/graph/topology` readbacks for
stale base-position conflict, unauthorized actor role, duplicate node ID,
hidden-oracle command scrubbing, resource-claim escalation, and active-node
retirement. The harness asserts no rejected mutation creates nodes/edges and
the hidden command text never appears in event or patch readbacks.
`tests/integration/test_graph_fr08_acceptance.py::test_fr08_authority_denial_and_rejection_readbacks`
drives authority denial through `POST /graph/decisions`, then verifies typed
authority decision/output events, authority node completion, lease release,
worker authority input binding/topology readback, durable `node_deferred`
reason `authority_not_granted`, no ready worker lease, invalid authority target
409 rejection, and API-boundary invalid decision 422 rejection. Authority
revocation is explicitly out of current FR-08 scope because there is no
first-class revocation or supersede-authority command; lease revocation remains
covered by FR-12/FR-16.

```bash
uv run pytest tests/integration/test_graph_fr08_acceptance.py -q
# 2 passed in 1.95s

uv run pytest tests/integration/test_graph_fr08_acceptance.py tests/integration/test_graph_decisions_api.py tests/unit/test_patch_validator.py tests/unit/test_graph_commands.py::test_record_decision_rejects_authority_for_non_authority_target tests/unit/test_graph_commands.py::test_record_decision_rejects_malformed_typed_authority_record_atomically -q
# 51 passed in 2.17s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 787 passed in 13.65s
```

FR-15 now has row-level acceptance coverage:
`tests/integration/test_graph_fr15_acceptance.py::test_fr15_gatekeeper_cleanup_is_explicit_graph_work_and_readable`
creates a real graph run row, captures an accepted file-state boundary with
gatekeeper-needed residue, drives `record_gatekeeper_verdicts` through
`GraphController`, verifies the resulting `snapshot_cleanup` outbox work, lets
`GraphDispatchExecutor` apply cleanup, and reads public `/graph/events`,
`/graph/nodes/worker-cleanup`, `/graph/file-state`, and `/graph/scheduler`.
The test proves `cleanup_requested` is durable graph work, the compromised
snapshot ref is deleted, `cleanup_applied` is emitted, a superseding
`file_state_accepted` record is accepted, the superseding snapshot excludes the
secret path, and the old/new file-state records are readable through graph
APIs. `tests/integration/test_graph_fr15_acceptance.py::test_fr15_rejected_file_state_revokes_write_lease_and_retries_cleanly`
drives a graph run through `GraphRunDriver` and supported `codex_server`-style
runtime callbacks where the first worker attempt creates a rejected secret
file-state boundary. It proves public events show `file_state_rejected` before
`agent_died`, the rejected lease is revoked, retry is scheduled, no accepted
file-state snapshot contains the secret path, the clean retry produces an
artifact-reference plus accepted file-state snapshot, `/api/runs` and `/graph`
complete, `/graph/scheduler` has no active leases, and
`/graph/final-blockers` is empty.

```bash
uv run pytest tests/integration/test_graph_fr15_acceptance.py -q
# 2 passed in 3.26s

uv run pytest tests/integration/test_graph_fr15_acceptance.py tests/integration/test_graph_outbox_crash_points.py tests/integration/test_graph_file_state_boundary.py tests/unit/test_graph_gatekeeper.py -q
# 36 passed in 5.32s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 789 passed in 13.91s

uv run ruff check tests/integration/test_graph_fr15_acceptance.py
# All checks passed

uv run ruff format --check tests/integration/test_graph_fr15_acceptance.py
# 1 file already formatted

uv run pyright tests/integration/test_graph_fr15_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-17 now has row-level acceptance coverage:
`tests/integration/test_graph_fr17_acceptance.py::test_fr17_less_used_readbacks_survive_projection_rebuild`
creates a real graph run row, seeds a compact less-used graph with recovery,
review, appeal, pending human gate, approved human gate, bound recovery-plan
and decision records, and rejected patch diagnostics, then writes an approval
through `POST /graph/decisions`. The harness verifies public `/api/runs`,
`/graph`, full `/graph/events`, `/graph/topology`, `/graph/scheduler`,
`/graph/decisions`, `/graph/patches`, `/graph/regions`,
`/graph/final-blockers`, and `/graph/nodes/{id}` readbacks for event
positions, run-state coherence, released leases, recovery/review contract
summaries, bound record positions, decision-request details, appeal/review
views, patch diagnostics, region blockers, and final blockers. It then deletes
graph event summaries, projection snapshots, and node-detail summaries and
re-reads the same public surfaces, proving rebuildable projection/read-model
coherence for the less-used families that remained in FR-17 scope.

```bash
uv run pytest tests/integration/test_graph_fr17_acceptance.py -q
# 1 passed in 2.23s

uv run pytest tests/integration/test_graph_fr17_acceptance.py tests/integration/test_graph_api.py tests/integration/test_graph_node_detail_read_models.py tests/integration/test_graph_decisions_api.py tests/integration/test_graph_fr14_final_gate_acceptance.py tests/integration/test_graph_fr16_acceptance.py -q
# 37 passed in 5.43s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 790 passed in 13.91s

uv run ruff check tests/integration/test_graph_fr17_acceptance.py
# All checks passed

uv run ruff format --check tests/integration/test_graph_fr17_acceptance.py
# 1 file already formatted

uv run pyright tests/integration/test_graph_fr17_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-03 now has row-level acceptance coverage:
`tests/integration/test_graph_fr03_acceptance.py::test_fr03_less_used_contracts_govern_validation_runtime_and_readbacks`
drives a real graph run row through `GraphController.submit_patch`,
`GraphController.evaluate_join`, and public graph API readbacks. The harness
creates less-used contract families and aliases including `summarizer`, `join`,
`review` as the `recovery` contract alias, `gap_planner`, and
`authority_request`; proves accepted patch validation plus rejected unknown-port
validation; proves `evaluate_join` emits the contract-owned `join_result`; and
reads `/graph/events`, `/graph/topology`, `/graph/patches`,
`/graph/scheduler`, `/graph/final-blockers`, and `/graph/nodes/{id}` for
contract handler types, input/output port schemas, allowed tools, resource
claims, allowed actions, preconditions, command definitions, prompt-hydration
metadata, binding policies/positions, patch rejection diagnostics, scheduler
readiness, and blocker node IDs. This closes the remaining less-used
contract-schema-depth/readback gap without new live `codex_server` product
proof because the unproven tail was controller/API contract behavior; runner
prompt/tool paths were already product-proven above and are covered by adjacent
prompt-packet regressions.

```bash
uv run pytest tests/integration/test_graph_fr03_acceptance.py -q
# 1 passed in 2.41s

uv run pytest tests/integration/test_graph_fr03_acceptance.py tests/integration/test_graph_api.py tests/integration/test_graph_node_detail_read_models.py tests/unit/test_graph_dynamic_contract.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_api_projection.py -q
# 63 passed in 3.23s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 791 passed in 16.11s

uv run ruff check tests/integration/test_graph_fr03_acceptance.py
# All checks passed

uv run ruff format --check tests/integration/test_graph_fr03_acceptance.py
# 1 file already formatted

uv run pyright tests/integration/test_graph_fr03_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-06 now has row-level acceptance coverage:
`tests/integration/test_graph_fr06_acceptance.py::test_fr06_edges_bind_fanout_join_optional_bind_all_and_supersede`
creates a real graph run row, seeds a compact typed topology, drives worker
callbacks through `GraphController.submit_callback`, drives
`GraphController.evaluate_join`, rejects invalid `submit_patch` edge mutations,
and verifies public `/graph/events`, `/graph/topology`, `/graph/scheduler`,
`/graph/patches`, `/graph/nodes/{id}`, and `/graph/final-blockers` readbacks.
The harness proves fan-out from one candidate to two verifier inputs,
`bind_all` accumulation into a summarizer many-cardinality port, join input
binding plus controller-owned `join_result`, optional-edge non-blocking
readiness with no binding, `rebind_on_superseding` replacing a superseded
file-state record with deterministic bound-position readback, and rejected edge
validation for unknown target ports, incompatible binding policies, and
incompatible accepted-record selectors. The pass also fixed a product readback
bug in light topology projection: SQLite light reads returned JSON `false` as
integer `0`, so optional edges were incorrectly displayed as required even
though full `/graph/events` showed `required=false`.

```bash
uv run pytest tests/integration/test_graph_fr06_acceptance.py -q
# 1 passed in 2.65s

uv run pytest tests/integration/test_graph_fr06_acceptance.py tests/integration/test_graph_api.py tests/integration/test_graph_node_detail_read_models.py tests/unit/test_graph_commands.py tests/unit/test_graph_projections.py tests/unit/test_graph_api_projection.py -q
# 203 passed in 3.17s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 792 passed in 16.02s

uv run ruff check src/orchestrator/graph/projections.py tests/integration/test_graph_fr06_acceptance.py
# All checks passed

uv run ruff format --check src/orchestrator/graph/projections.py tests/integration/test_graph_fr06_acceptance.py
# 2 files already formatted

uv run pyright src/orchestrator/graph/projections.py tests/integration/test_graph_fr06_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-10 now has row-level acceptance coverage:
`tests/integration/test_graph_fr10_acceptance.py::test_fr10_scheduler_readiness_command_precondition_and_retry_readbacks`
creates a real graph run row, seeds command-bound and command-missing check
nodes plus a running worker lease, drives `GraphController.schedule_tick`,
`GraphController.agent_died`, and subsequent schedule ticks, advances the
injected clock past retry backoff, and verifies public `/graph/events`,
`/graph/scheduler`, and `/graph/nodes/{id}` readbacks. The harness proves
missing command preconditions defer checks with
`precondition_failed:has_command_definition`, known
`dynamic_feature_hidden_oracle` command binding satisfies check scheduling and
node-detail command-definition readback, retry backoff emits durable
`runtime_retry_scheduled` and blocks readiness with
`retry_backoff_until:<timestamp>`, and advancing time lets the retried worker
receive a new active lease. No new live `codex_server` product run was needed
because the remaining FR-10 gap was deterministic scheduler/readback behavior;
the runner packet and live gate/authority/resource paths were already
product-proven above.

```bash
uv run pytest tests/integration/test_graph_fr10_acceptance.py -q
# 1 passed in 2.36s

uv run pytest tests/integration/test_graph_fr10_acceptance.py tests/integration/test_graph_scheduler_api.py tests/unit/test_scheduler.py tests/unit/test_graph_scheduler_view.py tests/unit/test_graph_commands.py::test_schedule_tick_check_precondition_requires_command_definition tests/unit/test_graph_commands.py::test_schedule_tick_check_precondition_passes_with_known_command_binding tests/unit/test_graph_commands.py::test_agent_died_retry_backoff_blocks_until_not_before -q
# 53 passed in 2.65s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 793 passed in 16.07s

uv run ruff check tests/integration/test_graph_fr10_acceptance.py
# All checks passed

uv run ruff format --check tests/integration/test_graph_fr10_acceptance.py
# 1 file already formatted

uv run pyright tests/integration/test_graph_fr10_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-07 now has row-level acceptance coverage:
`tests/integration/test_graph_fr07_acceptance.py::test_fr07_macro_tools_route_expand_validate_and_read_back_patch_attempts`
creates a real graph run row, routes planner macro tools through
`route_tool_call`, sends the normalized macro-backed patch envelopes to
`GraphController.submit_patch`, and verifies public `/graph/events`,
`/graph/patches`, `/graph/topology`, and `/graph/nodes/{id}` readbacks. The
harness proves accepted macro-tool paths for `create_join`, human
`request_gate`, authority `request_gate`, `retire_or_supersede` with `retire`,
and `retire_or_supersede` with `supersede`; proves malformed macro args become
durable `command_rejected` graph events; proves disallowed tool names are
rejected by the Codex server allow-list without invoking the patch callback;
and reads back the created join edges, human-gate node, authority-request
record, retired nodes, and superseding replacement node. No new live
`codex_server` product run was needed because simple live planner
`submit_graph_patch` routing and patch readbacks were already product-proven;
the unproven tail was deterministic macro-tool routing, expansion, validation,
and graph API readback.

```bash
uv run pytest tests/integration/test_graph_fr07_acceptance.py -q
# 1 passed in 2.40s

uv run pytest tests/integration/test_graph_fr07_acceptance.py tests/unit/test_graph_macros.py tests/unit/test_codex_server_common.py::test_planner_macros_are_exposed_with_typed_schemas tests/unit/test_codex_server_common.py::test_gap_planner_macros_are_exposed_with_typed_schemas tests/unit/test_codex_server_common.py::test_macro_tool_routes_as_graph_patch_invocation tests/unit/test_codex_server_tool_filtering.py tests/unit/test_graph_commands.py::test_patch_rejects_malformed_request_gate_record -q
# 24 passed in 2.54s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 794 passed in 16.27s

uv run ruff check tests/integration/test_graph_fr07_acceptance.py
# All checks passed

uv run ruff format --check tests/integration/test_graph_fr07_acceptance.py
# 1 file already formatted

uv run pyright tests/integration/test_graph_fr07_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-02 now has row-level acceptance coverage:
`tests/integration/test_graph_fr02_acceptance.py::test_fr02_canonical_taxonomy_nodes_are_created_and_readable`
creates a real graph run row, drives a planner-authored
`GraphController.submit_patch` that creates explicit `requirement`,
`artifact_index`, `recovery`, and `review` alias nodes, and verifies public
`/graph/events`, `/graph/topology`, `/graph/patches`, `/graph/nodes/{id}`, and
`/graph/final-blockers` readbacks. The harness proves the remaining canonical
taxonomy families can be created through the graph controller/API path and
their resolved contracts are readable: requirement input/output ports,
artifact-index file-state/verification/check input ports and artifact output,
explicit recovery failure-record input plus recovery-plan/graph-patch outputs,
and alias resolution from `review` to the recovery contract. Alias-only spellings
and future node kinds are scoped out as separate FR-02 criteria because the
registry resolves them to canonical contract families; new contract families
must reopen the row or add new criteria.

```bash
uv run pytest tests/integration/test_graph_fr02_acceptance.py -q
# 1 passed in 2.40s

uv run pytest tests/integration/test_graph_fr02_acceptance.py tests/integration/test_graph_fr03_acceptance.py tests/integration/test_graph_fr17_acceptance.py tests/integration/test_graph_fr14_final_gate_acceptance.py tests/unit/test_graph_dynamic_contract.py tests/unit/test_graph_api_projection.py -q
# 32 passed in 3.89s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 795 passed in 16.32s

uv run ruff check tests/integration/test_graph_fr02_acceptance.py
# All checks passed

uv run ruff format --check tests/integration/test_graph_fr02_acceptance.py
# 1 file already formatted

uv run pyright tests/integration/test_graph_fr02_acceptance.py
# 0 errors, 0 warnings, 0 informations
```

FR-09 now has row-level acceptance coverage:
`tests/integration/test_graph_fr09_acceptance.py::test_fr09_execution_packets_and_prompt_hydration_are_readable_for_less_used_nodes`
creates a real graph run row, drives a planner-authored patch that creates
`summarizer` and `gap_planner` executable nodes, leases both nodes with
`GraphController.schedule_tick`, dispatches them through the durable outbox and
`GraphDispatchExecutor`, builds the actual runner `ExecutionContext`, records
runtime-start acknowledgement with prompt summary, and
verifies public `/graph/events`, `/graph/nodes/{id}?payload_mode=full`, and
`/graph/topology` readbacks. The harness proves the summarizer receives a
`Summarizer context packet` with source records and `AnalysisSummary` schema,
the gap planner receives a gap-analysis planner packet with corrective-work
macro guidance and contract-derived macro tools, runtime-start events carry
bounded `prompt_summary` evidence, node-detail callback history preserves that
summary, and prompt hydration policy readbacks distinguish structured-json
candidate hydration from artifact-reference verification hydration.

```bash
uv run pytest tests/integration/test_graph_fr09_acceptance.py -q
# 1 passed in 2.37s

uv run pytest tests/integration/test_graph_fr09_acceptance.py tests/unit/test_graph_planner_packet.py tests/unit/test_graph_dispatch_on_output.py tests/integration/test_graph_node_detail_read_models.py tests/integration/test_graph_fr03_acceptance.py -q
# 53 passed in 2.72s

uv run pytest tests/unit/test_graph_*.py tests/unit/test_patch_validator.py tests/unit/test_scheduler.py tests/integration/test_graph_*.py tests/unit/test_codex_server_common.py tests/unit/test_codex_server_tool_filtering.py -q
# 796 passed in 16.19s
```

Worker write claims are now derived from declared routine artifact paths instead
of defaulting every compiled worker to repo-wide writes. The compiler ignores
absolute and traversal paths, falls back to repo-wide only when no safe artifact
path exists, and regression coverage proves two artifact-scoped workers can be
leased together while an overlapping writer defers. Runtime dispatch also
retries stale start acknowledgements, closing the product bug where two
simultaneously leased workers could race projection freshness and falsely mark
one worker dead.

The broader testing-gap pass now covers the main state-pack/readback gaps that
previously let product-path bugs escape isolated tests. New integration oracles
assert fresh node detail preserves `resource_claims`, `allowed_actions`,
`preconditions`, and `command_definition` through both summary and full node
detail paths; `/graph/topology` preserves edge binding policy, freshness and
prompt hydration metadata, bound record IDs, bound positions, and bound-record
summaries from compact events; `/graph/decisions` exposes pending authority
request details from light readbacks; `/graph/patches` returns rejected patch
diagnostics without crashing on legacy `base_graph_position=-1`; and a
callback-lifecycle state pack proves heartbeat renewal, cancellation, artifact
records, and failure records are visible through `/graph`, `/graph/scheduler`,
`/graph/events`, and node detail. This closes the systemic testing gaps as
regression coverage; remaining FR rows still require live product proof where
the ledger says product validation is missing.

## Product-Path Evidence

Dogfood run `e2c81109-ea77-496c-9d62-7f35fb17f296` used the real
`dynamic-graph-feature` routine, `/api/runs`, graph execution mode, a worktree,
and the `codex_server` runner. It reached planner, worker, and verifier nodes;
the worker changed the actual worktree artifact. The verifier received no real
requirement packet, submitted without grades, and the graph correctly rejected
the callback with `verification record at index 0 missing grades`. The run then
paused with an active verifier lease and no accepted callback. This is product
evidence for callback validation and blockers, and also evidence of a real
packet/dispatch bug.

Dogfood run `2aa3be3b-7900-49c8-8cc3-06e9b0eb99c6` re-ran the scenario after
the dispatch fix. It created planner-authored worker/verifier/gap/corrective
nodes and typed edges, accepted a worker candidate and file-state record, gave
the verifier a requirement fallback, accepted a real grade callback
(`R-01=A`), bound verification evidence into the gap planner, rejected a
duplicate gap edge patch, accepted a corrected gap patch, emitted gap records,
dispatched a corrective worker that updated the worktree artifact and ran the
configured acceptance command, recovered a dead final-check lease after restart,
ran the deterministic hidden-oracle check, and reached run status `completed`.
After the readback fixes, product API readbacks show `/graph/final-blockers`
returns `[]`, `/graph/regions` returns `region-dynamic-feature-2=accepted`,
and `/graph/scheduler` returns no ready/blocked work and no active leases.

Dogfood run `f85e3af1-297f-4966-9a5f-51d20c173456` was a fresh post-fix run
created to validate the final check citation change through the product path. It
created topology, exposed typed blockers for pending corrective/final nodes, and
eventually completed. Its final check ran before the corrective candidate and
did not cite candidate/file-state/evaluated records, proving the previous
ledger claim was too strong and exposing a stale-check acceptance gap.

Dogfood run `395b07e6-2048-496e-a56f-1d2d213f46f1` was run after tightening
check acceptance to require citations to the latest candidate/file-state
evidence. It proved the dispatch-side citation expansion by producing verifier
output with both candidate and file-state IDs, but the command validator
rejected it because validator-side citation derivation still expected only
directly bound candidate IDs. The same run also exposed two separate product
gaps: callback staging attempted to include the worktree `.venv`, and resume
after startup pause reported `is_graph_backed=false` instead of cleanly
recovering the graph run.

Dogfood run `b213b5df-b30e-4584-bb6f-a90b8c6ec277` was a fresh patched run
after aligning command validation with dispatch citation expansion. It used the
real `/api/runs` product path, graph execution mode, worktree `worktrees/r313`,
and the `codex_server` runner. The planner created worker, verifier, gap
planner, and final-check nodes; the worker produced candidate
`dogfood-smoke-5-candidate` and file-state
`file-state-exec-0be7fbaeeadf468799636aef6bd53113`; the verifier accepted
`verification-exec-3aa73ea6f44d4922a7a4d553e3fa1f45` with both
`candidate_record_ids` and `file_state_record_ids`; the deterministic final
check accepted `check-exec-e1e4e0f0830d492a9e889712febed5a9` with
`evaluated_record_ids` containing the verifier record, candidate record, and
file-state record; `/graph/scheduler` returned no ready/blocked/leased work;
`/graph/final-blockers` returned `[]`; and the run reached status `completed`.
After this product proof, `capture_file_state_boundary` was narrowed so ignored
`tool_cache` paths such as `.venv` remain classified in file-state evidence but
are not force-included into snapshot staging; that fix is regression-proven and
needed a follow-up product run to prove the broad callback-staging issue was
closed.

Dogfood run `5268031d-2b1a-415e-bead-7d364c10eb59` was the fresh product run
after the `.venv`/tool-cache staging fix. It used the real `/api/runs` graph
path, graph execution mode, worktree `worktrees/r314`, and the `codex_server`
runner. The worktree had an ignored `.venv/` directory. Worker file-state
`file-state-exec-0e05ad8d6a974e6f921a7385fbc73ad6` was accepted with ignored
`.venv` and `ui/node_modules` entries classified as `tool_cache`; its snapshot
commit `a892b000f444191fe7b171cabe112ba5037f1880` contained
`docs/dynamic-graph/dogfood-smoke-output-6.txt` and zero `.venv/` paths. The
artifact content was read back from the worktree as exactly
`dynamic graph dogfood ok 6`. The verifier accepted
`verification-exec-29e9863403fa4a2a8ebd8b4b12897d95` with
`candidate_record_ids=[dogfood-smoke-6-candidate]` and
`file_state_record_ids=[file-state-exec-0e05ad8d6a974e6f921a7385fbc73ad6]`; the
final check accepted `check-exec-33e408ffa16c462f9aecc3418e7d4c9a` with
`evaluated_record_ids` containing the verifier, candidate, and file-state
records, and it ran against snapshot
`dd529579652f448c825a467aa368688b`. `/graph` showed all runtime nodes
completed and `region-dogfood-smoke-6=accepted`; `/graph/scheduler` had no
ready, blocked, or leased work; `/graph/final-blockers` returned `[]`; and the
run reached status `completed`.

Final-invariant blocker probe `f3501792-dbf8-4ce5-b641-719244c8390a` was
created through `/api/runs` with `dynamic-graph-feature`, execution mode
`graph`, worktree `worktrees/r322`, and the supported `codex_server` runner.
The feature request was intentionally satisfiable by the worker/verifier, but
both `acceptance_command` and `hidden_oracle_command` were `false`. The run
accepted worker and verifier callbacks, then dispatched
`check-final-invariant-dynamic-final-blocker`; full
`/graph/events?from_position=66&payload_mode=full` readback showed check record
`check-exec-5ff1f51b8b5b497c8779a158d6c866fe` with `status=failed`,
`classification=failed`, `exit_code=1`, `command_text=false`, and
`evaluated_record_ids` containing the verifier, candidate, and file-state
records. Public `/api/runs/{id}` paused with `pause_reason=graph_blocked` and
`last_error="graph quiescent with non-accepted task(s): region-dynamic-final-blocker=pending"`;
`/graph` showed all runtime nodes completed but
`region-dynamic-final-blocker=pending`; `/graph/scheduler` was quiescent with
no ready, blocked, or leased work; `/graph/regions` and
`/graph/final-blockers` both returned `failed_check_result` plus
`task_not_accepted` blockers. This proves through the product API/runtime path
that a failed final invariant blocks run completion.

Completion-decision scope decision from the same 2026-06-22 product readbacks:
`dynamic-graph-feature` currently uses deterministic `check` nodes as final
invariant gates and does not create separate `final_gate` nodes. Completed run
`5268031d-2b1a-415e-bead-7d364c10eb59` had 92 graph events, an accepted final
check, `/graph/final-blockers=[]`, `/graph/regions` accepted, and run status
`completed`, but no `completion_decision` output record in bounded event-tail
readbacks. The existing `completion_decision` contract remains in scope for
explicit `final_gate` nodes and lifecycle `complete` commands; it is not
required for check-gated dynamic-feature completion unless a future routine
actually creates a `final_gate` node.

Dogfood run `3c5bfc81-9f0c-4cfb-bab5-cb0877ce86bd` was a resource-conflict
probe for FR-15. It used the real `/api/runs` graph path, graph execution mode,
worktree `worktrees/r315`, and the `codex_server` runner. The planner created
two independent workers in `region-resource-conflict-1` with repo write claims.
`worker-resource-conflict-a` received lease
`lease-b0cdb1a25b54474a9661ce7b062f45f5` at graph position 54 while
`worker-resource-conflict-b` was ready; the scheduler emitted
`node_deferred` at position 57 with `resource_conflict:write:write`. After
worker A accepted `candidate-rcf-a` and file-state
`file-state-exec-34de2b4cafc941b59d3456c7842bce5c`, the lease was released at
position 65. The next useful scheduler sequence re-readied worker B at position
76, granted lease `lease-830534fbd1ac49aabc39d57626ad1f07` at position 77, and
worker B accepted `candidate-rcf-b` with file-state
`file-state-exec-cf181eded15740ff95205e7cfd262b7c` before completing at
position 96. The worktree files were read back as exact contents
`resource conflict A` and `resource conflict B`. This product run also exposed
that the scheduler API did not bucket a ready-but-resource-deferred node under
`waiting_resources`; `project_scheduler_view` has been fixed and regression
tested, but that readback fix still needs a fresh product readback at the live
conflict moment. After an operator restart, resume produced recovery events
`agent_died`, `lease_revoked`, `runtime_retry_scheduled`, a recovery-plan
record, and `verifier-resource-conflict-b` returning to `ready`; subsequent
full `/run` and `/graph` readbacks timed out under load, so this run is not
terminal-completion proof.

During the 2026-06-22 temporary server session, startup recovery for the same
`3c5bfc81...` run also logged a duplicate-position append failure
(`UNIQUE constraint failed: events_v2.aggregate_id, events_v2.version`) and a
later SQLite `database is locked` error while recovering/driving the stale run.
This is product-path evidence that graph recovery/re-entry still has an
idempotency or concurrency gap; it strengthens, rather than closes, the FR-12
remaining work.

The first targeted FR-12 fix after that product failure makes runtime
reconciliation re-read durable graph state before converting recovered leases
to `agent_died`; if another driver or restart path has already revoked the
lease, reconciliation skips it instead of appending a rejected command, and if
the graph position goes stale it retries only while the lease remains active.
This is regression-proven by an integration test with real DB/controller/outbox
objects, but not product-validated yet: it still needs a server recovery run
that shows the duplicate-position/lock class no longer occurs.

Follow-up product API probe on 2026-06-22 restarted the temporary server on the
same dogfood DB after the stale-report guard. Startup did not re-arm
`3c5bfc81...` because the run was already paused with
`pause_reason=graph_blocked`; no duplicate-position or SQLite-lock error
appeared during startup/readback, but this did not exercise the stale recovery
guard. The public `/api/runs/3c5bfc81...` readback returned quickly with
`status=paused`, `is_graph_backed=true`, and `last_error` listing failed
`gap-planner-resource-conflict` and `verifier-resource-conflict-b` nodes.
`/graph`, `/graph/scheduler`, `/graph/regions`, and `/graph/final-blockers`
also returned quickly instead of timing out. `/graph` returned `event_count=154`
and no ready nodes, but its projected `run_state` was still `active` while the
public run row was paused; that is a remaining API/readback coherence gap.
Node-detail summary readbacks for `worker-resource-conflict-a` and
`worker-resource-conflict-b` returned released leases and top-level
`resource_claims=[{"mode":"write","scope":"repo"}]`, proving resource-claim
summary readback for worker nodes. Topology readback returned 11 nodes and 10
edges, but the stale run's edge rows did not expose binding policy or bound
record positions, so FR-06 remained partial at that point.

After adding the `/graph` effective-state fix, the temporary server was
restarted and the same product readback returned coherent state for
`3c5bfc81...`: public `/api/runs/{id}` reported `status=paused`,
`pause_reason=graph_blocked`, and `is_graph_backed=true`; `/graph` reported
`run_state=paused`, `event_count=154`, no ready nodes, and
`region-resource-conflict-1=pending`.

Follow-up product API readbacks on 2026-06-22 used the temporary server against
the same dogfood DB and exposed both proof and gaps. For completed run
`5268031d-2b1a-415e-bead-7d364c10eb59`, summary node-detail readbacks for
`planner-s-01`, `worker-implementation-dogfood-smoke-6`,
`verifier-validation-dogfood-smoke-6`, and
`check-final-invariant-dogfood-smoke-6` returned node kind/role/state,
contract keys, input ports, output/file-state record IDs, released lease data,
and callback history. `/graph/decisions` returned an empty pending-gate,
appeal, and review view for both `5268031d...` and `3c5bfc81...`.
`/graph/scheduler` and `/graph/regions` returned quiescent accepted state for
`5268031d...` and explicit missing-input blockers for the paused
`3c5bfc81...` run. Bounded full `/graph/events?from_position=45&limit=40`
readback on `3c5bfc81...` returned the raw product evidence for write-claim
resource behavior: `lease_granted` at positions 54 and 77 carried
`resource_claims=[{"mode":"write","scope":"repo"}]`, `node_deferred` at
position 57 carried `resource_conflict:write:write`, and releases/second lease
followed in order. Full node-detail readback on the existing DB timed out, and
old summary rows did not contain resource/control fields, so node-detail
resource/control readback remains a product gap. The code now preserves
`resource_claims`, `allowed_actions`, `preconditions`, and
`command_definition` in future node-detail summaries, but that is regression
evidence until a fresh product run exercises it.

Unsupported-runner product probe `b9621fcc-7094-4be1-b526-eb54f302f94a` was
created through `/api/runs` with `dynamic-graph-feature`, `execution_mode=graph`,
and `agent_runner_type=cli_subprocess`. Starting it through
`POST /api/runs/{id}/start` returned 202; public run readback then moved to
`status=paused` with `pause_reason=graph_runner_unsupported` and
`last_error="Graph execution requires a runner with native graph callback tools;
unsupported runner 'cli_subprocess'. Supported runners: claude_sdk,
codex_server."` The run reported `is_graph_backed=false` and
`/graph/events` returned zero events, proving unsupported graph runners fail
before graph seeding or agent execution.

Control/readback product probe `963c40bd-938a-4abb-86b6-4e797a4dc96d` was
created through `/api/runs` with an embedded graph routine, graph execution
mode, worktree `worktrees/r317`, and the supported `codex_server` runner. The
run paused as graph-backed with `pause_reason=graph_blocked`; `/graph` reported
`run_state=paused`, `event_count=37`, and `gate-s-01` as the ready node.
`/graph/decisions` returned an actual pending gate
`{"node_id":"gate-s-01","gate_type":"step_gate"}`. `/graph/scheduler` returned
`waiting_gates=[{"node_id":"worker-s-01-t-01","reason":"gate_not_approved:gate-s-01"}]`
and missing-input blockers for the verifier/check. Node detail for
`worker-s-01-t-01` returned resource claims, non-resource
`allowed_actions=["submit_records","request_clarification","raise_appeal"]`,
input bindings, and contract ports. Node detail for
`check-s-01-t-01-auto_verify-check-artifact` returned
`allowed_actions=["submit_records"]`, read resource claims, and the concrete
`command_definition` for `uv run python -c "print(42)"`; its `preconditions`
field was still empty, so precondition readback remains unproven. Topology
readback exposed edge binding metadata including binding policy `bind_first`,
bound positions, source/target port contracts, and bound record details for
routine snapshot and requirement edges. `/graph/patches` returned an empty
attempt list, `/graph/regions` returned pending region blockers, and
`/graph/final-blockers` returned pending-check/node blockers.

Post-fix product readback on the same real graph run
`963c40bd-938a-4abb-86b6-4e797a4dc96d` proved the compact node-detail summary
path now preserves the derived check-node scheduler precondition. Public
`/api/runs/{id}` returned `status=paused`, `pause_reason=graph_blocked`, and
`is_graph_backed=true`; `/graph/nodes/check-s-01-t-01-auto_verify-check-artifact`
returned `kind=check`, `role=auto_verify`, read `resource_claims`, 
`allowed_actions=["submit_records"]`, `preconditions=["has_command_definition"]`,
and the concrete `command_definition` for `uv run python -c "print(42)"`.
`/graph/scheduler` still showed the check blocked only on
`missing_required_input:candidate_under_test`, not on a command-definition
precondition failure, and bounded `/graph/events` returned the corresponding
deferred check events at positions 34 and 37.

Resource-conflict product probe `c4902f8e-bd04-407f-b428-392fb8bb9679` was
created through `/api/runs` with an embedded graph routine, graph execution
mode, worktree `worktrees/r318`, and the supported `codex_server` runner. At
graph position 39 the scheduler granted
`lease-d56a1fc887a64ec2a1b69dff851d34ef` to `worker-s-01-t-a` with a repo
write claim; at position 42 it emitted `node_deferred` for `worker-s-01-t-b`
with `resource_conflict:write:write`. During that same live state,
`/graph/scheduler` returned `waiting_resources=[{"node_id":"worker-s-01-t-b","reason":"resource_conflict:write:write"}]`,
`leases.active` containing the worker A lease, and `/graph` returned
`worker-s-01-t-b` as ready. This is fresh product proof for the previously
regression-only `waiting_resources` readback fix.

Cancellation product probes from the same two-writer shape exposed a remaining
FR-12/FR-16 race. Run `c4902f8e...` was cancelled while worker A was leased; the
public run row moved to `failed`, but graph scheduler initially still showed
the active lease and late callback events were accepted. A targeted fix now
regression-proves that graph cancel signals append graph `cancel`, revoke active
leases, and cancel running nodes before the run-row failure. A follow-up product
run `db9f1313-6fa4-4445-855b-f4ecd2e790e0` after the signal-consumer and API
ordering fixes still showed the product cancel signal enqueued only after
worker A submitted: callback accepted at graph position 44, file-state accepted
at 48, lease released at 51, then graph `run_lifecycle_changed` to `cancelling`
at 52. The run row later moved to `failed`. This validates the diagnosis but
does not close cancellation product proof; the remaining issue is the
end-to-end API/executor timing that lets active graph callbacks complete before
the cancel signal is durable.

Terminal-cancel product probe `c67baf63-91f4-41a0-9159-dac333adbdbd` was
created through `/api/runs` with an embedded two-worker routine, graph execution
mode, worktree `worktrees/r321`, and the supported `codex_server` runner. Public
activity/events showed worker B deferred for `resource_conflict:write:write` at
graph position 42 while worker A held the repo write lease, then deferred again
for `resource_conflict:read:write` at position 58 while verifier A held a read
lease. After worker B was later leased and running, `POST /api/runs/{id}/cancel`
appended graph `run_lifecycle_changed` to `cancelling` at position 73,
`lease_revoked` for worker B's active write lease at 74, worker B
`node_state_changed` to `cancelled` at 75, and graph `run_lifecycle_changed` to
`cancelled` at 76 before the signal consumer marked the public run row
`failed`. Post-reload readbacks returned `/api/runs.status=failed`,
`is_graph_backed=true`, `/graph.run_state=failed`, worker B state `cancelled`,
the worker B lease state `revoked`, `/graph/scheduler.leases.active=[]`,
`/graph/decisions` empty, `/graph/patches` empty, `/graph/regions` with
`S-01/T-A=accepted` and `S-01/T-B=pending`, and `/graph/final-blockers` with
the expected unfinished task-B blockers. Node detail for `worker-s-01-t-b`
returned resource claims, allowed actions, input bindings, revoked lease data,
and cancellation history. This closes the post-cancel graph/API coherence
portion of FR-12/FR-17 and proves terminal graph cancellation through the
product API, but it does not prove late callback rejection because the cancelled
worker did not submit after position 76.

Decision API product probe `5263df20-a03d-4d5c-8474-c99c7522949b` was created
through `/api/runs` with an embedded gated routine, graph execution mode,
worktree `worktrees/r324`, and the supported `codex_server` runner. The run
paused graph-backed with gate `gate-s-01` ready; `/graph/decisions` returned
the actual pending step gate and `/graph/scheduler` returned
`waiting_gates=[{"node_id":"worker-s-01-t-01","reason":"gate_not_approved:gate-s-01"}]`.
`POST /api/runs/{id}/graph/decisions` with an approval decision emitted
`approval_decision_recorded` at position 19, an enriched
`output_record_accepted` decision record at position 20, and
`node_state_changed` to completed for the gate at position 21. Immediate
readbacks showed `/graph/decisions.pending_gates=[]`, full
`/graph/events?from_position=18&payload_mode=full` returned the same decision
events, and `/graph/nodes/gate-s-01` showed the accepted decision record in
`output_records`. After `POST /api/runs/{id}/resume`, the graph driver
re-entered scheduling: the downstream worker was leased and
`/graph/scheduler.waiting_gates=[]`. The run was then cancelled; follow-up
readback reached public `status=failed`, graph `run_state=failed`, and no
active leases. This is product proof for approval decision write/readback and
gate scheduling re-entry, not for native `authority_request` decisions.

Invalid decision probe `2bade738-eb8e-4613-80e8-5673fdc95478` intentionally
posted an authority decision against a human gate through the product API. That
initially returned a decision record but did not unblock the gate, exposing a
real target-validation bug. `record_decision` now rejects authority decisions
unless the target node is an `authority_request`; this is covered by focused
unit and integration regression tests, but native authority-request product
proof remains open.

Authority-request product probes `407dff61-0d92-4806-a869-de377dd89adb` and
`1b19441e-6271-4f5a-8bff-1240ae54124e` used `/api/runs`,
`dynamic-graph-feature`, graph execution mode, worktrees `worktrees/r325` and
`worktrees/r326`, and the supported `codex_server` runner. The first run's
planner submitted `authority-request-product-proof-v1` through the real
`submit_graph_patch` callback; `/graph/patches` and full event readback showed
the patch rejected with
`edge ... references unknown target port worker.authority`. That exposed a real
contract gap: scheduler logic already supported authority inputs, but executable
node contracts did not expose an `authority` input port. The worker/common
executable contract now accepts optional `authority_decision` input, with
regression coverage. The second run, after the contract fix, showed the
contract change through `/graph/topology`, where executable node contracts
included `authority`, and the original edge error was gone. Its planner patch
was still rejected because the authority request record itself was malformed
(`value.requested_authority` missing), so no native `authority_request` node was
accepted and no authority decision could be product-validated. Both probes were
cancelled through `/api/runs/{id}/cancel`; post-cancel readbacks showed failed
public run rows and no active leases.

Native authority-request product probe `3a9af7c4-34fc-46bc-8bcf-7bd68630be81`
used `/api/runs`, `dynamic-graph-feature`, graph execution mode, worktree
`worktrees/r332`, and the supported `codex_server` runner. The planner first
submitted a malformed authority request and received a product-visible
`graph_patch_rejected` at position 19, then submitted corrected patch
`authority-proof-final`, accepted at position 20. `/graph/events` showed the
native `authority_request` node `authority-proof-gate`, its
`authority_request_record`, worker `worker-authority-proof`, and required edge
`edge-authority-proof`; `/graph/decisions` exposed a pending
`authority_request` for `repo:docs/dynamic-graph/status.md:write` targeting
`worker-authority-proof`. Posting `POST /graph/decisions` with
`decision_type=authority` and `decision=granted` emitted
`authority_decision_recorded` at position 41, an enriched
`authority_decision` output record at position 42, `input_bound` for
`edge-authority-proof` at position 43, completion of the authority node at
position 44, and `lease_released` for the authority lease at position 45. The
same API request performed no-grant scheduler re-entry: `worker-authority-proof`
became ready at positions 46-47 and was deferred at position 48 only because
`max_grants=0` for API-side recompute. Public readbacks before cancellation
showed `/graph/scheduler.ready=["worker-authority-proof"]`, `blocked=[]`,
`waiting_gates=[]`, `waiting_resources=[]`, and no active leases;
`/graph/topology` showed `edge-authority-proof` bound to
`authority_decision-authority-proof-gate` with `bound_at_position=43`,
`record_bound_positions`, `binding_policy=bind_first`, source/target port
contracts, and the bound record summary; `/graph/nodes/authority-proof-gate`
showed both request and decision records and a released lease; and
`/graph/nodes/worker-authority-proof` showed the bound `authority` input and
ready state. The run was then cancelled through `/api/runs/{id}/cancel` to
avoid leaving ready work active.

Callback lifecycle product probes `961b0f47-4d7f-49fa-b22f-a39f4fc7c56d` and
`1010af96-df86-47b2-8824-5d6269226481` used `/api/runs`,
`dynamic-graph-feature`, graph execution mode, worktrees `worktrees/r327` and
`worktrees/r328`, and the supported `codex_server` runner. Runtime dispatch now
records a controller-owned heartbeat immediately after start acknowledgement,
without exposing `record_heartbeat` as an agent-routable Codex tool. In
`961b0f47...`, public `/graph/events` showed `lease_granted` at position 12,
`heartbeat_recorded` at position 17, and `lease_renewed` at position 18;
`/graph/scheduler` showed the renewed active planner lease. Cancelling the run
then exposed a product bug: the still-running planner accepted additional graph
patches after run cancellation had begun, before its final submit was rejected
as `callback_rejected_stale` at position 38 with `reason=lease revoked`.
`submit_patch` now rejects non-active graph runs, with regression coverage. The
follow-up product run `1010af96...` again showed heartbeat and lease renewal at
positions 17 and 18; after `/api/runs/{id}/cancel`, readbacks showed
`lease_revoked` at position 32, graph cancellation at position 34, no active
leases in `/graph/scheduler`, and a late runner submit rejected as
`callback_rejected_stale` at position 35 with `reason=lease revoked`.

Path-scoped write product probe `35c4d760-16f7-44fb-b224-09fad79cb16a`
created an embedded routine through `/api/runs`, graph execution mode, worktree
`worktrees/r333`, and the supported `codex_server` runner. The routine declared
three same-step workers: one writing a `docs/dynamic-graph/...` artifact, one
writing a `tests/fixtures/...` artifact, and one overlapping the docs path.
Public `/graph/events` showed worker creation with artifact-scoped write claims,
`lease_granted` for the docs worker at position 22, `lease_granted` for the
tests worker at position 25, and the overlapping docs worker deferred at
position 28 with `resource_conflict:write:write`. `/graph/scheduler` reported
the overlap in `waiting_resources` and active docs/tests leases. The same run
exposed a real FR-12/FR-16 race: while acknowledging concurrent starts, the
tests worker hit a stale projection and was incorrectly converted to
`agent_died` with a revoked lease. Runtime dispatch now retries stale
start-acknowledgement commands before treating the worker as failed.

Follow-up product probe `7bd58637-03ad-4817-aed0-4190c149cb08` reran the same
artifact-scoped shape after the stale-start fix through `/api/runs`, graph
execution mode, worktree `worktrees/r334`, and the supported `codex_server`
runner. `/graph/events` showed the three workers created with scoped write
claims for `docs/dynamic-graph/path-scope-proof-docs-2.txt`,
`tests/fixtures/path_scope_proof_tests_2.txt`, and the overlapping docs path;
all three became ready at positions 16-21; the docs worker was leased at
position 22; the tests worker was leased at position 25; and the overlapping
docs worker was deferred at position 28 with
`resource_conflict:write:write`. Both non-conflicting workers then acknowledged
running and emitted runtime-owned heartbeat/lease-renewal facts: docs at
positions 29-31 and tests at positions 32-34, with zero `agent_died` events
before cancellation. Public `/graph/scheduler` showed
`ready=["worker-s-01-docs-overlap"]`,
`waiting_resources=[{"node_id":"worker-s-01-docs-overlap","reason":"resource_conflict:write:write"}]`,
and active docs/tests leases. Public `/api/runs`, `/graph`, `/graph/events`,
`/graph/topology`, `/graph/nodes` for all three workers, `/graph/decisions`,
`/graph/patches`, `/graph/regions`, and `/graph/final-blockers` were captured
as coherent readbacks. After `POST /api/runs/{id}/cancel`, `/api/runs` returned
`status=failed`, `/graph.run_state=failed`, `/graph/scheduler.leases.active=[]`,
and the docs/tests leases were revoked with `run_cancelled`. This product-proves
artifact-derived path-scoped non-conflicting writes, multi-ready deterministic
leasing for the two eligible workers, overlapping-resource deferral, concurrent
start heartbeat durability, and cancel cleanup of the active scoped leases.

Callback-tail probe `e47f5708-5dde-4087-a83b-8e9e0c9de315` used an embedded
routine through `/api/runs`, graph execution mode, worktree `worktrees/r335`,
and the supported `codex_server` runner to target the worker artifact/output
callback path. It exposed a product bug instead of proof: the worker callback
was rejected at graph position 35 because file-state authority treated
`.claude/settings.local.json`, classified as `tool_cache`, as a changed path
outside the worker's scoped write lease. Callback file-state write-authority
checks now ignore entries classified as `tool_cache`, matching the staging
semantics already proven for ignored dependency/tool directories.

Follow-up callback-tail probe `a9b658fa-4442-4ef9-82b5-dbabf2c0857c` reran the
artifact/output shape through `/api/runs`, graph execution mode, worktree
`worktrees/r336`, and the supported `codex_server` runner. The worker wrote
`docs/dynamic-graph/callback-output-proof-20260622205127.txt`; runtime dispatch
accepted the worker callback at graph position 35 with output records
`candidate-s-01-t-01-1`,
`artifact-reference-exec-c90c40a5f96e4008a541bcf86673a9c7-0`, and
`file-state-exec-c90c40a5f96e4008a541bcf86673a9c7`. Full
`/graph/events?from_position=35&limit=30&payload_mode=full` readback showed the
artifact reference accepted at position 39 with
`record_type=artifact_reference`, `producer_port=artifact_reference`, and
`uri=docs/dynamic-graph/callback-output-proof-20260622205127.txt`; the
file-state record was accepted at positions 40-41 and bound into verifier/check
inputs at positions 42-43; the worker completed and released its lease at
positions 44-45. The deterministic check later accepted its
callback/check-result at positions 58-59 after verifying the artifact from the
snapshot. `/graph/nodes/worker-s-01-t-01` exposed state `completed`, the
candidate and artifact-reference output records, and callback history with
running position 32 plus accepted callback position 35. Final readbacks showed
`/api/runs.status=completed`, `is_graph_backed=true`, `/graph.run_state=completed`,
`event_count=70`, `/graph/scheduler.leases.active=[]`, accepted region
`s-01/t-01`, and `/graph/final-blockers=[]`. This product-proves the supported
runner artifact/output callback path and the tool-cache file-state authority
fix through runtime callbacks and graph readback APIs.

Failure-tail probe `32be2af2-60ed-49e6-838f-7a7af651ab53` used an embedded
routine through `/api/runs`, graph execution mode, and the supported
`codex_server` runner, with a worker prompt that intentionally finished without
submitting through graph callback tools. Full
`/graph/events?from_position=24&limit=30&payload_mode=full` readback showed
worker lease `lease-3a5c848c7c5d43a5b7620579b409584f` granted at position 24,
running at position 26, `agent_died` at position 29 with
`reason="agent exited without submit"`, `lease_revoked` at position 30, and
`runtime_retry_scheduled` at position 31. A second attempt leased
`lease-339041aca05d4364b353965c34a117b0` at position 36, reached running at
position 39, then emitted a second `agent_died` at position 42,
`lease_revoked` at position 43, `runtime_retry_scheduled` at position 44, and
returned the worker to ready at position 46 with recovery-plan output records.
`/api/runs` reported `status=paused`, `pause_reason=graph_blocked`, and
`is_graph_backed=true`; `/graph` reported `run_state=paused` and
`event_count=46`; `/graph/scheduler` had no ready nodes and no active leases;
`/graph/nodes/worker-s-01-t-01` exposed both `agent_died` callbacks in
callback history and only recovery-plan output records. This product-proves the
real supported-runner `agent_died` failure/retry callback tail, but not a
terminal `failure_record` callback path.

Final-gate acceptance harness
`tests/integration/test_graph_fr14_final_gate_acceptance.py::test_final_gate_completion_decision_and_region_readbacks`
drives an embedded graph routine through the real `GraphRunDriver`, graph
controller/runtime, and HTTP readback surface. The planner creates an explicit
`final_gate` node and a typed edge from the compiler-created auto-verify check;
the worker, verifier, check, and final gate then complete through runtime
dispatch. The harness asserts `/api/runs.status=completed`,
`/graph.run_state=completed`, `/graph/scheduler.leases.active=[]`,
`/graph/final-blockers=[]`, and `/graph/regions` accepted for `s-01/t-01`.
Full `/graph/events` readback proves candidate, file-state,
`verification_report`, and `check_result` records all exist before the
`completion_decision`; the `completion_decision` has immutable ID,
`record_type=completion_decision`, `schema=CompletionDecision`, producer
`final-gate-s-01-t-01`, port/producer_port `completion_decision`, run ID,
position/time enrichment, payload `{"status":"passed","blockers":[]}`, and
provenance `{"source":"final_gate_evaluated"}`. Full
`/graph/nodes/final-gate-s-01-t-01` readback exposes kind/role/state,
`task_region_id`, bound `check_result` input, output record envelope,
runtime-start callback history, and the lifecycle event with
`trigger=final_gate_evaluated`. `/graph/topology` exposes the final-gate edge
binding policy, bound record IDs/positions, and bound check-result summary. No
new live `codex_server` product run was required because final-gate execution
is controller-owned/deterministic and the harness uses the same product
graph/API/runtime path needed for this row scope.

## Functional Requirements Ledger

### 2026-06-25 Final-Gate Acceptance Harness Refresh

The explicit final-gate gap is now covered by a row-level executable acceptance
harness. This validates FR-04, FR-05, and FR-14 because their only remaining
row-scope ambiguity was explicit `final_gate`/`completion_decision` production,
record envelope/readback, and region acceptance semantics. FR-03 and FR-17 kept
that evidence but stayed partial until their later row-level harnesses closed
the broader contract/readback gaps.

### 2026-06-25 FR-12 Acceptance Harness Refresh

Product-scope FR rows remain `partial` except FR-02, FR-03, FR-04, FR-05, FR-06, FR-07, FR-08, FR-09, FR-10,
FR-11, FR-12, FR-14, FR-15, FR-16, and FR-17, which now have row-level executable acceptance
coverage plus calibrated product-path evidence, and FR-19, which is explicitly
out of scope. No additional row should be promoted to `validated` until every acceptance
criterion for that row has product-real proof or deterministic
graph-runtime/API harness coverage through `/api/runs`, graph workflow
execution, runtime callbacks, and graph API/readback paths.

Unresolved or implemented-unproven rows now cluster as follows:

- FR-01/FR-13/FR-18: validated. Two-task multi-region acceptance harness in
  `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py` covers
  multi-region bootstrap, invalid-patch probe, partial-region blockers,
  unauthorized-actor patch in quiescent state, and terminal no-blocker state.
  No remaining gap in the current row scope.
- FR-09: planner/worker/verifier/check packets and prompt hydration are
  product-proven, and the remaining less-used summarizer/gap-planner
  packet/readback gap is now covered by a row-level executable acceptance
  harness. No FR-09 gap remains in the current row scope.
- FR-12/FR-16: heartbeat, terminal cancellation, late stale-callback rejection,
  authority lease release, concurrent start-ack retry, artifact/output
  callbacks, and real `agent_died` failure/retry callbacks are product-proven.
  FR-16 terminal `failure_record` behavior and FR-12 recovery re-entry are now
  covered by executable row-level acceptance harnesses. No FR-12/FR-16 gap
  remains in the current row scope.
- FR-15: worktree file-state capture, tool-cache staging exclusion,
  verifier/check citations, repo write conflicts, path-scoped non-conflicting
  writes, tool-cache file-state write-authority exclusion, and active
  scoped-lease cancellation are product-proven. Cleanup as explicit graph work
  and failed/revoked write-lease cleanup are now row-level
  acceptance-harness-proven through real graph controller/runtime/API
  readbacks. No FR-15 gap remains in the current row scope.

Contradictions resolved in this refresh:

- Earlier remaining-plan text listed native authority gates,
  `waiting_resources`, path-scoped non-conflicting writes, heartbeat,
  cancellation, and failed-final-invariant blocking as missing proof. This
  refresh treats those as product-proven by `3a9af7c4...`,
  `c4902f8e...`, `7bd58637...`, `961b0f47...`/`1010af96...`,
  `c67baf63...`, and `f3501792...` respectively, while preserving the narrower
  gaps above.
- Check-gated `dynamic-graph-feature` runs do not require a separate
  `completion_decision` record. Explicit `final_gate`/lifecycle completion
  decisions remain in scope only for routines that actually create those nodes
  or call lifecycle completion.

### 2026-06-22 Validation Strategy Correction

The remaining partial rows are too broad to close reliably with one-off manual
product probes. Manual probes remain useful for discovering product bugs and
calibrating expected API/event shapes, but they should not be the primary
validation mechanism for promoting FR rows to `validated`.

Before another row-promotion attempt, add an executable FR acceptance harness
that encodes the row's full acceptance criteria as repeatable checks against
the product graph surfaces: `/api/runs`, graph execution mode, runtime
callbacks, `/graph/events`, node detail, scheduler readbacks, regions, final
blockers, and public run state. A row may move from `partial` to `validated`
only when:

- every remaining criterion for that row is represented in the acceptance
  harness or explicitly scoped out in this ledger;
- the harness has product-real coverage, not only isolated command/projection
  unit coverage;
- a final bounded product probe confirms the harness assertions match live
  `/api/runs` behavior for any runner/runtime path that cannot be reproduced
  deterministically in-process; and
- the ledger update cites both the executable test names and exact product run
  IDs/API readbacks used to calibrate them.

For FR-16, the acceptance suite now covers the already-proven supported-runner
paths (submit, grade, patch, heartbeat, artifact/output, stale rejection,
unsupported-runner fail-fast) and terminal exhausted-failure/`failure_record`
behavior. For FR-12, the acceptance suite now covers durable recovery re-entry
and stale-report guarding, not just ordinary `agent_died` retry. This is a
process correction: do not add another partial-proof-only commit unless it
first installs or extends the executable row-level acceptance harness.

| ID | Required behavior | Acceptance criteria | Implementation evidence | Validation evidence | Status | Remaining gap / next proof needed |
|---|---|---|---|---|---|---|
| FR-01 Scope and bootstrap | A graph run starts from a feature goal/routine snapshot, creates typed planner/worker/verifier/check/control topology, routes records, schedules work, supports authorized mutation, and completes only by invariants. | Real orchestrator graph run reaches terminal completion through planner-authored topology and cannot complete while final invariants fail. | `src/orchestrator/graph/compiler.py`, `src/orchestrator/workflow/graph_driver.py`, `src/orchestrator/graph/commands.py`, `src/orchestrator/graph_runtime/dispatch.py`. | Product run `2aa3be3b...` completed through planner-authored topology, worker/verifier/gap/corrective/check path, recovery, accepted region, and empty final blockers. Fresh run `f85e3af1...` exposed typed blockers instead of false completion. Product run `f3501792...` proved a failed final invariant keeps the run paused `graph_blocked` with explicit `failed_check_result` and `task_not_accepted` blockers. The row-level harness `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py::test_fr01_fr18_two_task_bootstrap_completes` closes the non-smoke topology gap through a two-task inline routine with two parallel task regions (s-01/t-01 and s-01/t-02): it drives `GraphRunDriver` through an inline `RoutineConfig`, proves the compiler creates named worker/verifier/check nodes for both tasks (`worker-s-01-t-01`, `verifier-s-01-t-01`, `check-s-01-t-01-auto_verify-check-t01`, and t-02 equivalents), proves the planner submits a rejected invalid patch (hidden_oracle_command) and an accepted noop patch before completing, proves both task workers write their artifacts and the auto-verify checks pass, and reads `/api/runs`, `/graph`, `/graph/events`, `/graph/nodes`, `/graph/regions`, `/graph/final-blockers`, `/graph/scheduler`, and `/graph/patches` confirming `run.status=completed`, both regions `accepted`, no final blockers, no active leases, two `file_state_accepted` and two passed `check_result` output records, and both patch attempts durable. | validated | No remaining FR-01 gap in the current row scope. Future topology shapes require new criteria. |
| FR-02 Canonical node taxonomy | Canonical graph node types are registered with contracts. | Product run creates/uses canonical node kinds and readback exposes their contracts. | `DEFAULT_NODE_CONTRACTS` in `src/orchestrator/graph/contracts.py`; FR-02 acceptance harness in `tests/integration/test_graph_fr02_acceptance.py`. | Product topology/events showed `root`, `artifact`, `planner`, `worker`, `verifier`, and `check` nodes created by planner/runtime. Product probes `963c40bd...`, `5263df20...`, and `3a9af7c4...` exercised human-gate and native authority-request node families with node-detail/topology readbacks. The final-gate acceptance harness exercises an explicit `final_gate` node with topology and node-detail readback. FR-03 and FR-17 harnesses cover less-used contract/readback families including summarizer, join, gap planner, recovery/review/appeal surfaces, and rebuildable projections. The row-level harness `tests/integration/test_graph_fr02_acceptance.py::test_fr02_canonical_taxonomy_nodes_are_created_and_readable` closes the remaining taxonomy gap through a real graph run row, planner-authored `GraphController.submit_patch`, and public graph API readbacks: it creates explicit `requirement`, `artifact_index`, `recovery`, and `review` alias nodes; proves accepted patch/readback metadata; reads topology contract summaries; reads node detail contract summaries for requirement, artifact-index, and recovery input/output ports; proves alias resolution from `review` to the recovery contract; and verifies the created pending taxonomy nodes appear in final blockers rather than only static registry data. Alias-only spellings and future contract families are scoped out of the current row unless they introduce new canonical behavior. | validated | No remaining FR-02 gap in the current row scope. Future canonical node families or alias semantics require new criteria. |
| FR-03 Node contract schema depth | Node contracts and runtime controls govern validation, scheduling, prompt rendering, tool exposure, lifecycle, completion, deterministic handlers, and readback shape. | Real graph run shows contract-derived tools/ports plus runtime controls such as resource claims, preconditions, command definitions, leases, and node detail readback. | `contracts.py`, `scheduler.py`, `dispatch.py`, `commands.py`, `api/routers/graph.py`; FR-03 acceptance harness in `tests/integration/test_graph_fr03_acceptance.py`. | Product run exercised graph patch tools, submit/grade callbacks, leases, scheduler readback, and command execution. 2026-06-22 product node-detail summary readbacks for completed planner/worker/verifier/check nodes returned contracts, ports, output/file-state record IDs, released leases, callbacks, and lifecycle state. Bounded full event readback on `3c5bfc81...` returned write resource claims and conflict deferral evidence; follow-up node-detail summary readbacks for both conflict workers returned top-level write `resource_claims` from released leases. Fresh product probe `963c40bd...` returned worker node detail with resource claims and non-resource `allowed_actions`, and check node detail with `allowed_actions` plus concrete `command_definition`. Post-fix readback on the same product run returned check-node `preconditions=["has_command_definition"]` through `/graph/nodes`. Product authority probe `407dff61...` exposed a missing worker `authority` input contract; regression now proves executable contracts accept optional `authority_decision` input. Product run `3a9af7c4...` accepted a native `authority_request`, posted an authority grant through `/graph/decisions`, released the authority lease, and `/graph/nodes` showed authority request/decision records plus worker `authority` input and ready state. The final-gate acceptance harness `tests/integration/test_graph_fr14_final_gate_acceptance.py::test_final_gate_completion_decision_and_region_readbacks` proves explicit `final_gate` controller execution, node detail `task_region_id`, bound input, output record, runtime-start callback, and `final_gate_evaluated` lifecycle readback through `/api/runs`, `/graph/events`, `/graph/nodes`, `/graph/topology`, `/graph/regions`, and `/graph/final-blockers`. The row-level harness `tests/integration/test_graph_fr03_acceptance.py::test_fr03_less_used_contracts_govern_validation_runtime_and_readbacks` closes the remaining contract-schema-depth gap through a real graph run row, `GraphController.submit_patch`, `GraphController.evaluate_join`, and public `/graph/events`, `/graph/topology`, `/graph/patches`, `/graph/scheduler`, `/graph/final-blockers`, and `/graph/nodes/{id}` readbacks: it proves less-used `summarizer`, `join`, `review`/`recovery`, `gap_planner`, and `authority_request` contract summaries; allowed tools/actions; resource claims; preconditions; command definitions; prompt-hydration metadata; accepted and rejected contract validation; controller-owned `join_result` lifecycle; scheduler readiness; and blocker readback. Existing prompt-packet regressions remain the executable prompt/tool exposure proof for runner packet rendering. | validated | No remaining FR-03 gap in the current row scope. Future node/control contract families or prompt surfaces require new criteria. |
| FR-04 Universal typed record envelope | Records on graph edges have immutable IDs, type/schema metadata, producer identity/port, run/position/time enrichment, payload, and provenance. | Real run emits accepted bootstrap, candidate, file-state, verification, check, and completion records with enriched universal fields. | `models.py`, `store.py`, `commands.py`, `compiler.py`; final-gate provenance hardening in `src/orchestrator/graph/commands.py`; node-detail region readback in `src/orchestrator/api/routers/graph.py` and `src/orchestrator/graph/projections.py`. | Product run emitted bootstrap, candidate, file-state, verification, gap, recovery, and check records with graph positions and producer identity. Product run `5263df20...` emitted an enriched approval decision record, and `3a9af7c4...` emitted enriched authority-request and authority-decision records. Product run `a9b658fa...` emitted and read back an enriched `artifact_reference` output record with producer port `artifact_reference` and URI `docs/dynamic-graph/callback-output-proof-20260622205127.txt`. Completion is reflected in lifecycle/readbacks. 2026-06-22 scope decision: check-gated `dynamic-graph-feature` runs do not require separate `completion_decision` records unless they create explicit `final_gate` nodes. The final-gate acceptance harness `tests/integration/test_graph_fr14_final_gate_acceptance.py::test_final_gate_completion_decision_and_region_readbacks` closes the explicit completion-record gap: it reads a `completion_decision` from `/graph/events` and `/graph/nodes/final-gate-s-01-t-01` with immutable ID, type/schema metadata, producer node/port, run ID, graph position, timestamp/created_at, payload `{"status":"passed","blockers":[]}`, and provenance `{"source":"final_gate_evaluated"}`. | validated | No remaining FR-04 gap in the current row scope. Future record families require new rows or reopened criteria. |
| FR-05 Record type catalog and producers | Required record types have concrete typed contracts and producer/callback validation paths. | Real run produces the required record families and rejects malformed/unsupported output paths through runtime callbacks. | `models.py`, `commands.py`, `compiler.py`, `projections.py`, `dispatch.py`; `/graph/decisions` API bridge in `api/routers/graph.py`; final-gate acceptance harness in `tests/integration/test_graph_fr14_final_gate_acceptance.py`. | Product runs rejected a malformed verifier record, accepted candidate/file-state/verification/gap/check/recovery records, and exposed missing-grade and pending-node diagnostics. 2026-06-22 scope decision narrows `completion_decision` for check-gated dynamic-feature runs; explicit `final_gate` producers remain in the catalog. Product run `5263df20...` accepted an approval decision through `POST /graph/decisions` and emitted an enriched `decision_record` output visible through events and node detail. Product run `1b19441e...` rejected a malformed `authority_request_record` with explicit Pydantic diagnostics through `/graph/patches`. Product run `3a9af7c4...` accepted a native `authority_request_record` and emitted an enriched `authority_decision` output record through the public decision API. Product run `a9b658fa...` accepted a worker `artifact_reference` callback record through the supported runner/runtime path, and product run `32be2af2...` emitted real `agent_died`, `lease_revoked`, `runtime_retry_scheduled`, and recovery-plan records after the runner exited without submit. The FR-16 harness covers terminal `failure_record`; the final-gate harness now covers explicit `completion_decision` production through controller/runtime/API readbacks. | validated | No remaining FR-05 gap in the current row scope. Future record families or producer paths require new rows or reopened criteria. |
| FR-06 Typed edges and bindings | Edges validate endpoints/ports/schema/cardinality/policies and bind accepted records deterministically. | Real topology readback shows typed edges, bound record IDs, policies, metadata, and no missing required inputs at completion. | `contracts.py`, `commands.py`, `projections.py`; light topology optional-edge readback fix in `src/orchestrator/graph/projections.py`; FR-06 acceptance harness in `tests/integration/test_graph_fr06_acceptance.py`. | Product run bound candidate/file-state into verifier, verification into gap planner, classified gap into corrective work, corrective verification into final check, and ended with accepted region and no final blockers. Follow-up topology readback for `3c5bfc81...` returned 11 nodes and 10 edges, but edge rows did not expose binding policy or bound-record positions for this stale run. Fresh product probe `963c40bd...` returned topology edges with `binding_policy=bind_first`, `bound_at_position`, `record_bound_positions`, source/target port contracts, and bound routine-snapshot records. Product run `3a9af7c4...` returned `edge-authority-proof` bound to `authority_decision-authority-proof-gate` with `bound_at_position=43`, `record_bound_positions`, `binding_policy=bind_first`, source/target authority port contracts, and bound record summary. Terminal no-missing-required-input behavior is proven for the completed dynamic-feature path. The row-level harness `tests/integration/test_graph_fr06_acceptance.py::test_fr06_edges_bind_fanout_join_optional_bind_all_and_supersede` closes the remaining topology-shape gap through a real graph run row, `GraphController.submit_callback`, `GraphController.evaluate_join`, rejected `submit_patch` attempts, and public graph API readbacks: it proves fan-out candidate binding to two verifier inputs, `bind_all` accumulation into a summarizer many-cardinality port, dynamic join input binding and `join_result` output, optional-edge non-blocking readiness with `required=false` preserved in light `/graph/topology`, `rebind_on_superseding` replacing a superseded file-state record with bound-position metadata, scheduler ready readback for the optional worker without missing required inputs, and deterministic rejection diagnostics for unknown ports, incompatible binding policy, and incompatible selectors. No new live product run was required because the unproven tail was deterministic controller/API binding behavior; live simple binding and terminal no-missing-input paths were already product-proven above. | validated | No remaining FR-06 gap in the current row scope. Future edge policies or supersede semantics require new criteria. |
| FR-07 Planner graph mutation tools and macros | Planner/gap-planner mutate topology through validated tools/macros, with raw ops only as validated patch expansion. | A real planner submits graph patches/macros through `submit_graph_patch`; accepted/rejected attempts are visible in patch readback. | `macros.py`, `runners/agents/codex/common.py`, `dispatch.py`, `commands.py`; FR-07 acceptance harness in `tests/integration/test_graph_fr07_acceptance.py`. | Product run accepted the initial planner patch, rejected a duplicate gap edge patch, accepted a corrected gap patch, and `/graph/patches` was used during proof gathering. The row-level harness `tests/integration/test_graph_fr07_acceptance.py::test_fr07_macro_tools_route_expand_validate_and_read_back_patch_attempts` closes the macro catalog gap through a real graph run row, `route_tool_call`, `GraphController.submit_patch`, and public graph API readbacks: it proves accepted/readable `create_join`, human `request_gate`, authority `request_gate`, retire, and supersede macro-tool paths; rejected/readable malformed macro args as durable `command_rejected` graph events; disallowed tool-name rejection before callback invocation; `/graph/patches` accepted attempts for all macro-backed patches; `/graph/topology` join edges; and `/graph/nodes/{id}` readbacks for join, human gate, authority-request record, retired targets, and superseding replacement node. FR-08 safety enforcement, FR-06 binding semantics, and FR-14 completion semantics remain scoped to their own validated rows; FR-07 asserts only enough of those surfaces to prove macro-generated graph mutations landed. | validated | No remaining FR-07 gap in the current row scope. Future macro tools require new criteria. |
| FR-08 Mutation validation and authority | Patch acceptance enforces actor authority, freshness, topology safety, resource safety, active-node safety, hidden-command scrubbing, and diagnostics. | Real run shows authorized accepted patches and deterministic rejection for unsafe paths. | `commands.py`, `contracts.py`, `macros.py`, `dispatch.py`; FR-08 acceptance harness in `tests/integration/test_graph_fr08_acceptance.py`. | Product run proved authorized accepted patches and duplicate-edge rejection diagnostics. Product probe `2bade738...` exposed that authority decisions were incorrectly accepted for a human gate; `record_decision` now rejects authority decisions unless the target node is an `authority_request`, with focused regression coverage. Product probes `407dff61...` and `1b19441e...` added real runner-callback rejection diagnostics for an invalid authority-gated worker edge and a malformed authority request record. Product run `3a9af7c4...` then proved the native accepted path: malformed authority shape was rejected, corrected `authority_request` was accepted, the public authority grant was recorded, and the authority decision bound to the target worker. Product probe `961b0f47...` exposed that a still-running planner could accept graph patches after cancellation began; `submit_patch` now rejects non-active runs with regression coverage. Artifact-derived path sanitization is regression-proven for absolute/traversal paths; product run `7bd58637...` proves safe declared artifact paths flow into scoped resource claims and scheduler conflict checks. The row-level harness `tests/integration/test_graph_fr08_acceptance.py::test_fr08_invalid_patch_matrix_rejected_and_readable` closes the remaining invalid-patch matrix through graph controller/API readbacks for unauthorized role, stale base-position conflict, duplicate node ID, hidden command scrubbing with no command text leakage, resource escalation, active-node retire rejection, and rejected-patch diagnostics. `tests/integration/test_graph_fr08_acceptance.py::test_fr08_authority_denial_and_rejection_readbacks` closes authority denial/rejection proof through `POST /graph/decisions`, typed authority decision output, lease release, topology/input binding readback, `authority_not_granted` deferral, invalid target 409, and invalid decision 422. Authority revocation is scoped out because no first-class authority revocation/supersede command exists; lease revocation remains covered by FR-12/FR-16. | validated | No remaining FR-08 gap in the current row scope. Future authority revocation semantics require a first-class product command and reopened criteria. |
| FR-09 Execution packets and prompt hydration | Executable nodes receive packets derived from contracts and bound records; prompt hydration policies shape visible evidence. | Real graph runner receives planner/worker/verifier/gap/check packets with expected tools and hydrated references. | `dispatch.py`, `runners/agents/codex/common.py`, `projections.py`, `api/routers/graph.py`; prompt-summary runtime-start readback in `src/orchestrator/graph_runtime/dispatch.py`, `src/orchestrator/graph/commands.py`, `src/orchestrator/graph_runtime/store.py`, and `src/orchestrator/api/routers/graph.py`; FR-09 acceptance harness in `tests/integration/test_graph_fr09_acceptance.py`. | First product run proved verifier packets could miss requirements. The fallback fix produced real verifier grades in `2aa3be3b...`; final check resolved and executed the hidden-oracle binding. Product run `2aa3be3b...` also product-proves the common planner/worker/verifier/gap/corrective/check runner path and hidden-oracle check binding, so the remaining unproven tail was deterministic packet/readback coverage for less-used executable node kinds. The row-level harness `tests/integration/test_graph_fr09_acceptance.py::test_fr09_execution_packets_and_prompt_hydration_are_readable_for_less_used_nodes` closes that tail through real graph run rows, planner-authored `GraphController.submit_patch`, `GraphController.schedule_tick`, durable outbox rows, `GraphDispatchExecutor` context construction, runtime-start acknowledgement, and public `/graph/events`, `/graph/nodes/{id}?payload_mode=full`, and `/graph/topology` readbacks: it captures the exact `ExecutionContext.prompt` that a runner receives for `summarizer` and `gap_planner`, proves the summarizer packet contains `source_records`/`AnalysisSummary` and the gap-planner packet contains `gap_analysis_contract`/corrective-work macro guidance, proves gap-planner tool exposure is limited to the contract-derived patch/macro tools, and proves runtime-start events plus node-detail callback history expose bounded `prompt_summary` readbacks with packet type, prompt sections, available tools, lease/base snapshot identity, bound input ports, structured-json candidate hydration for the summarizer, and artifact-reference verification hydration for the gap planner. No new live product probe was required because the runner families and common packet path were already product-proven; this harness covers the remaining deterministic graph-runtime/API readback behavior. | validated | No remaining FR-09 gap in the current row scope. Future executable node kinds, prompt packet families, or hydration policies require new criteria. |
| FR-10 Scheduler readiness | Scheduler only marks nodes ready when lifecycle, lease, inputs, gates, authority, command bindings, resources, retry, and preconditions allow. | Real scheduler readback shows ready/deferred transitions matching graph state during a run. | `scheduler.py`, `commands.py`, `projections.py`; FR-10 acceptance harness in `tests/integration/test_graph_fr10_acceptance.py`. | Product scheduler/readback evidence showed missing-input deferrals, readiness after bindings, final check retry after recovery, then no ready/blocked/leased work after completion. Product run `3c5bfc81...` additionally proved overlapping repo write claims defer a ready worker with `resource_conflict:write:write` until the first write lease releases. Fresh product probes `963c40bd...` and `c4902f8e...` proved public scheduler bucketing for `waiting_gates` and live `waiting_resources` respectively. Product run `5263df20...` proved that posting an approval decision clears `pending_gates` and, after resume, lets the graph driver lease the downstream worker with `waiting_gates=[]`. Product run `3a9af7c4...` proved authority readiness through the public graph path: the authority gate was leased/running, the worker stayed dependent on the authority input before decision, posting the authority grant emitted `input_bound`, and `/graph/scheduler` then reported `ready=["worker-authority-proof"]`, no waiting gates/resources, and no active authority lease. Product run `7bd58637...` proved artifact-scoped readiness/resource evaluation through the public graph path: two same-step workers with non-overlapping declared artifact paths were leased together, while a third worker overlapping the docs path stayed ready but was bucketed under `waiting_resources` with `resource_conflict:write:write`. The row-level harness `tests/integration/test_graph_fr10_acceptance.py::test_fr10_scheduler_readiness_command_precondition_and_retry_readbacks` closes the remaining command/precondition/retry gap through a real graph run row, `GraphController.schedule_tick`, `GraphController.agent_died`, injected clock advancement, and public API readbacks: it proves missing check command preconditions defer with `precondition_failed:has_command_definition`, known command bindings satisfy check scheduling and node-detail command-definition readback, active leases are visible before expiry, retry backoff emits `runtime_retry_scheduled` and blocks readiness with `retry_backoff_until:<timestamp>`, and the retried worker receives a new active lease after the clock passes `retry_not_before`. | validated | No remaining FR-10 gap in the current row scope. Future scheduler blockers or command-binding families require new criteria. |
| FR-11 Scheduler ordering and fairness | Ready nodes are deterministically ordered and controller/deterministic work can run before agent work without starvation. | Real run dispatch order reflects graph priorities/kinds and all eligible nodes progress. | `scheduler.py`, `dispatch.py`; FR-11 acceptance harness in `tests/integration/test_graph_fr11_acceptance.py`. | Product event order showed deterministic dependency order across planner -> worker -> verifier -> gap -> corrective worker. Product run `7bd58637...` proves multi-ready order through `/api/runs`: all three same-step workers became ready, docs then tests were granted leases at positions 22 and 25, and the overlapping docs worker was deferred at position 28. The row-level harness `tests/integration/test_graph_fr11_acceptance.py::test_fr11_scheduler_orders_frontier_and_progresses_deferred_work` closes the broader fairness ambiguity by driving repeated controller/API schedule ticks over a mixed ready frontier: controller/deterministic nodes lease before agents at equal priority, agent workers lease by priority, non-conflicting read/write claims progress together, the overlapping docs writer is held in `/graph/scheduler.waiting_resources` with `resource_conflict:write:write`, runtime start and accepted callback release the blocking writer lease, candidate/file-state records are readable from node detail/events, and the previously blocked writer is leased on the next tick. This validates the finite fairness policy recorded above: deterministic priority/kind ordering, no starvation for ready non-resource-blocked nodes across ticks, and eventual grant after a conflicting lease releases. | validated | No remaining FR-11 gap in the current row scope. Future fairness policies beyond deterministic repeated-tick/resource-release progress require new criteria. |
| FR-12 Lease, execution, retry, heartbeat, cancellation, and recovery durability | Leases/executions/failures/recovery are durable and replayable. | Real run emits durable lease/execution facts; runner failure or retry path is exercised or explicitly not needed for the validated scenario. | `commands.py`, `projections.py`, `store.py`, `graph_driver.py`; `GraphController.read_projection` plus `reconcile_runtime` stale-report guard in `src/orchestrator/graph_runtime/dispatch.py`; terminal graph cancel helper in `src/orchestrator/workflow/graph_driver.py`; graph cancel signal/API handling in `src/orchestrator/workflow/signals/consumer.py` and `src/orchestrator/api/routers/runs.py`; runtime-owned start heartbeat in `src/orchestrator/graph_runtime/dispatch.py`; FR-12 acceptance harness in `tests/integration/test_graph_fr12_acceptance.py`. | Product run `2aa3be3b...` recovered a dead final-check lease after server restart with `agent_died`, `lease_revoked`, `runtime_retry_scheduled`, `recovery_plan`, re-lease, check completion, and terminal run completion. Product run `3c5bfc81...` added recovery evidence for a stale verifier lease after restart/resume and exposed the duplicate-position/SQLite-lock recovery re-entry class. Product run `c67baf63...` proves terminal graph cancellation through `/api/runs/{id}/cancel`: active worker-B write lease was revoked, worker B was cancelled, graph state reached `cancelled`, the signal consumer moved the public run row to `failed`, and post-reload scheduler readback had no active leases. Product runs `961b0f47...` and `1010af96...` prove graph-dispatch heartbeat durability through `/api/runs` and public `/graph/events`; `1010af96...` also proves a late runner submit after terminal graph cancellation is rejected as `callback_rejected_stale` with no active leases remaining. Product run `3a9af7c4...` added lease-release proof for the API authority-decision path. Product run `7bd58637...` proves concurrent start acknowledgements retry stale graph positions instead of producing false failure callbacks, and API cancellation revokes both active scoped leases. Product run `32be2af2...` proves the real supported-runner failure/retry tail: a worker that exited without submit emitted `agent_died`, `lease_revoked`, `runtime_retry_scheduled`, and recovery-plan output records on two attempts, with `/api/runs.status=paused`, `/graph.run_state=paused`, no active leases, and node-detail callback history exposing both failure callbacks. The FR-16 acceptance harness covers terminal exhausted failure through `tests/integration/test_graph_fr16_acceptance.py::test_fr16_terminal_exhausted_failure_record_callback_readbacks`: retry attempts advance durably, the second runtime death emits one `failure_record`, `/api/runs.status=paused`, `/graph.run_state=paused`, no active leases, and `/graph/final-blockers` remains non-empty. The FR-12 acceptance harness closes the remaining recovery re-entry gap through `tests/integration/test_graph_fr12_acceptance.py::test_fr12_recovery_reentry_skips_stale_report_and_rebuilds_readbacks`: it creates an active graph run and active worker lease, feeds the same recovered lease snapshot through `reconcile_runtime` twice, asserts the first recovery emits exactly one `agent_died`, `lease_revoked`, `runtime_retry_scheduled`, and `recovery_plan`, asserts the second stale report re-reads durable graph state and appends no duplicate stale recovery event, verifies positions remain consecutive with no `command_rejected`/duplicate-position failure and no SQLite-lock failure, and proves `/api/runs`, `/graph`, `/graph/events`, `/graph/nodes/worker-step-1-task-1`, `/graph/scheduler`, and `/graph/final-blockers` remain coherent before and after deleting/rebuilding graph read models. | validated | No remaining FR-12 gap. Future recovery modes or runner families require new rows or reopened criteria. |
| FR-13 Progress safety and quiescence blockers | Graph cannot silently stop while work is possible; blockers explain non-terminal or impossible states. | Real run exposes blockers while incomplete and no blockers once complete; failed final invariant keeps run non-completed. | `commands.py`, `projections.py`, `graph_driver.py`, `api/routers/graph.py`. | Product evidence includes first-run callback blocker, fresh-run typed pending blockers, and completed-run `/graph/final-blockers` returning `[]` after accepted final check. Product run `f3501792...` reached quiescence with all nodes completed but run `paused`, region still pending, and `/graph/final-blockers` returning `failed_check_result` plus `task_not_accepted`. Product run `3a9af7c4...` kept the graph non-terminal after authority approval because the downstream worker was ready but unexecuted; `/graph/final-blockers` reported pending work/task acceptance rather than allowing completion. The row-level harnesses in `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py` close the harder blocked-progress and invalid-patch probe gaps. `test_fr01_fr18_two_task_bootstrap_completes` proves criterion (a/d): the planner's `hidden_oracle_command` patch is rejected and durable in `/graph/patches`, and no final blockers exist after both regions complete. `test_fr13_partial_region_blockers_and_invalid_patch_in_blocked_state` proves criteria (b/c): it uses a t-02 check that always fails (`false`), drives the run to quiescence, asserts `/api/runs.status=paused`, T-01 region `accepted` and T-02 region non-accepted in `/graph/regions`, non-empty `/graph/final-blockers` with a T-02-related blocker, no active leases; then submits an unauthorized-actor patch (`actor_role="fixer"`) via `GraphController.handle_command` while the run is quiescent/blocked; asserts the rejection event is durable in `/graph/events`, the injected node does not appear in graph state, blockers are unchanged, the run remains paused, and the rejected attempt appears in `/graph/patches`. | validated | No remaining FR-13 gap in the current row scope. Future quiescence scenarios require new criteria. |
| FR-14 Region and completion semantics | Task regions are completion groups and acceptance requires candidate/file-state/verifier/check/gate evidence. | Real region readback shows pending -> accepted transitions only after typed evidence exists. | `compiler.py`, `macros.py`, `projections.py`, `commands.py`; final-gate acceptance harness in `tests/integration/test_graph_fr14_final_gate_acceptance.py`. | Product readbacks showed pending/in-progress states before evidence and `region-dynamic-feature-2=accepted` only after corrective candidate, verifier pass, file-state, final check, and empty blockers. Product run `f3501792...` showed the same evidence chain is insufficient when the final check fails: `/graph/regions` kept `region-dynamic-final-blocker` pending with `failed_check_result`. 2026-06-22 scope decision: check-gated dynamic-feature runs do not emit separate `completion_decision`; that record is reserved for explicit `final_gate` or lifecycle completion paths. The final-gate harness creates an explicit `final_gate` node, binds it to the accepted check result, proves candidate/file-state/`verification_report`/`check_result` records all exist before the gate's passed `completion_decision`, and reads `/graph/regions` as `s-01/t-01=accepted` with `/graph/final-blockers=[]` and public run/graph state completed. | validated | No remaining FR-14 gap in the current row scope. Future completion-group types require new rows or reopened criteria. |
| FR-15 File-state and worktree semantics | Worker authority, file-state capture, downstream consumption, resource conflicts, checks, citations, and cleanup are graph work. | Real worker changes a scoped file, file-state is captured, verifier/check cite candidate/file-state records, and final state is inspectable. | `commands.py`, `dispatch.py`, `file_state.py`, `projections.py`; FR-15 acceptance harness in `tests/integration/test_graph_fr15_acceptance.py`. | Product run `b213b5df...` completed with verifier citations to candidate/file-state and final check `check-exec-e1e4e0f0830d492a9e889712febed5a9` citing verifier, candidate, and file-state records. Product run `395b07e6...` exposed that callback staging can try to add worktree `.venv`. Product run `5268031d...` proved the fix through the product path: ignored `.venv` was classified as `tool_cache` in file-state evidence, the captured snapshot commit contained the target artifact and zero `.venv/` paths, verifier/check records cited candidate and file-state evidence, API readbacks showed accepted region/no blockers/completed run, and the artifact content was read back from the worktree. Product run `3c5bfc81...` proved overlapping write-claim behavior: worker B was deferred for `resource_conflict:write:write` while worker A held a write lease, then worker B was leased and completed after worker A released; both worker artifacts were read back with exact content. Product run `7bd58637...` proves declared artifact paths now scope worker write claims through the real compiler/runtime/API path: docs and tests artifact writers were leased concurrently, the overlapping docs writer deferred, node detail/topology/scheduler readbacks exposed the scoped claims, and cancellation revoked the two active scoped write leases. Product run `e47f5708...` exposed `.claude/settings.local.json` classified as `tool_cache` could still reject a scoped callback as outside write authority; product run `a9b658fa...` proves the fix, accepting the callback with that tool-cache entry excluded from authority enforcement while the artifact file-state and downstream check completed through product APIs. The row-level harness `tests/integration/test_graph_fr15_acceptance.py::test_fr15_gatekeeper_cleanup_is_explicit_graph_work_and_readable` closes explicit cleanup proof by driving a real graph run row, accepted file-state boundary, `record_gatekeeper_verdicts`, `snapshot_cleanup` outbox dispatch, `cleanup_applied`, superseding `file_state_accepted`, deleted compromised snapshot ref, superseding snapshot without the secret path, and public `/graph/events`, `/graph/nodes`, `/graph/file-state`, and `/graph/scheduler` readbacks. `tests/integration/test_graph_fr15_acceptance.py::test_fr15_rejected_file_state_revokes_write_lease_and_retries_cleanly` closes failed/revoked write-lease cleanup proof through `GraphRunDriver` and supported callback semantics: a rejected secret boundary emits `file_state_rejected`, the same lease is revoked through `agent_died`, retry is scheduled, no accepted file-state snapshot contains the secret, the clean retry accepts an artifact-reference plus file-state snapshot, public run/graph state complete, `/graph/scheduler` has no active leases, and `/graph/final-blockers=[]`. | validated | No remaining FR-15 gap in the current row scope. Future cleanup mechanisms or worktree isolation policies require new criteria. |
| FR-16 Runner support and callback enforcement | Supported graph runners and callbacks enforce submit/grade/patch/heartbeat/artifact/output/failure paths; unsupported runners fail early. | Real graph run uses a supported runner and callback path; unsupported-runner behavior has product-path proof or remains unvalidated. | `graph_driver.py`, `runners/agents/codex/common.py`, `dispatch.py`, `commands.py`, decision API bridge in `api/routers/graph.py`; FR-16 acceptance harness in `tests/integration/test_graph_fr16_acceptance.py`. | Product `codex_server` runner used `submit_graph_patch`, `submit`, and `grade`; callback rejection was observed and dispatch was fixed to surface it. Product probe `b9621fcc...` proved `cli_subprocess` graph runs pause with `graph_runner_unsupported` before graph seeding and emit zero graph events. Product cancellation probes showed a late supported-runner submit callback could be accepted if cancellation was not durable before the agent submitted. Product run `c67baf63...` proves supported-runner cancellation reaches terminal graph state and stops with no post-cancel worker-B callback. Product run `5263df20...` proves the public API can write approval decisions into graph events and re-enter scheduling; this is not runner-callback proof. Product runs `407dff61...` and `1b19441e...` prove supported-runner `submit_graph_patch` rejections are visible for authority-shape errors. Product run `3a9af7c4...` proves the supported `codex_server` planner can create a valid native authority-request patch through `submit_graph_patch`, and the public decision bridge can accept the authority decision, bind it, release the gate lease, and recompute readiness. Product runs `961b0f47...` and `1010af96...` prove runtime-owned heartbeat callback events for a supported `codex_server` graph dispatch, keep lifecycle/artifact callbacks non-agent-routable, and prove a late supported-runner submit after terminal graph cancellation is rejected as `callback_rejected_stale`. Product run `7bd58637...` proves concurrent supported-runner start acknowledgements for two leased workers retry stale graph positions instead of producing false failure callbacks, and both workers emit heartbeat/lease-renewed facts before cancellation. Product run `a9b658fa...` proves supported-runner submit callbacks now emit and accept worker artifact/output records through `/api/runs`, runtime callbacks, and graph readbacks. Product run `32be2af2...` proves the real supported-runner failure/retry callback path via `agent_died`, lease revocation, retry scheduling, and node callback history when the runner exits without submit. Executable row-level harness coverage now closes the manual-proof gap: `test_fr16_supported_codex_callbacks_complete_and_read_back` drives supported submit/grade/heartbeat/artifact callbacks through graph driver/runtime and asserts `/api/runs`, `/graph`, `/graph/events`, `/graph/nodes/worker-step-1-task-1`, `/graph/scheduler`, and `/graph/final-blockers`; `test_fr16_submit_graph_patch_callback_is_required_and_readable` covers planner `submit_graph_patch` and callback history; `test_fr16_stale_callback_rejection_is_readable` covers terminal stale callback rejection; `test_fr16_unsupported_runner_fails_before_graph_seeding` covers unsupported runner fail-fast with zero graph events; and `test_fr16_terminal_exhausted_failure_record_callback_readbacks` covers max-attempt runtime death producing a durable `failure_record`, failed node state, paused public run, paused graph, no active leases, and final blockers. No new product run ID was needed because all live `codex_server` paths except terminal exhaustion were already product-proven above, and terminal exhaustion is now deterministic in the graph driver/runtime/API harness. | validated | No remaining FR-16 gap. Future callback types or runner families require new rows or reopened criteria. |
| FR-17 API and readback | APIs expose topology, node details, scheduler, leases, patch attempts, regions, bindings, blockers, decisions, and rebuildable projections. | Real run readbacks from API return coherent graph state during/after execution. | `api/routers/graph.py`, `api/__init__.py`, `projections.py`, `store.py`; `/graph` now reports the effective paused/terminal run-row state when graph events exist, graph cancel responses preserve graph-backed status, and node detail exposes `task_region_id`; FR-17 acceptance harness in `tests/integration/test_graph_fr17_acceptance.py`. | Product proof used `/api/runs`, `/activity`, `/graph/events`, `/graph/scheduler`, `/graph/topology`, `/graph/regions`, `/graph/final-blockers`, and `/graph/patches`; restart readbacks were fixed to show accepted region and empty blockers from light events. 2026-06-22 API probes added node-detail summary proof for contracts/ports/records/leases/callbacks, empty decision-view proof for completed/paused runs, coherent scheduler/region readbacks for completed and paused runs, and bounded full event readback for resource-conflict facts. Follow-up stale-run readback proved `/run`, `/graph`, `/graph/scheduler`, `/graph/regions`, `/graph/final-blockers`, `/graph/topology`, and worker node-detail summaries return quickly instead of timing out, and worker node detail exposes resource claims. It then exposed and fixed a coherence gap; patched product readback returned `/run.status=paused` and `/graph.run_state=paused` for `3c5bfc81...`. Fresh product probes `963c40bd...` and `c4902f8e...` added actual pending gate decision readback, worker/check node-detail `allowed_actions` and `command_definition` readback, topology binding metadata/readback, and live `waiting_resources` readback. Product run `c67baf63...` added post-cancel coherence proof across `/api/runs`, `/activity`, `/graph`, `/graph/events`, `/graph/scheduler`, `/graph/topology`, `/graph/nodes/worker-s-01-t-b`, `/graph/decisions`, `/graph/patches`, `/graph/regions`, and `/graph/final-blockers`. Post-fix `963c40bd...` readback added check-node precondition proof through `/graph/nodes`. Product run `f3501792...` added failed-final-invariant API proof across `/api/runs`, `/graph`, `/graph/events`, `/graph/scheduler`, `/graph/nodes`, `/graph/regions`, `/graph/decisions`, and `/graph/final-blockers`. Product run `5263df20...` added public decision write/readback proof: `POST /graph/decisions` emitted decision events, `/graph/decisions` cleared pending gates, `/graph/nodes/gate-s-01` exposed the decision output record, and `/graph/scheduler` showed downstream scheduling after resume. Product authority probes `407dff61...` and `1b19441e...` added `/graph/patches`, `/graph/events`, `/graph/topology`, `/graph/decisions`, `/graph/scheduler`, and post-cancel readbacks for authority-shape rejection and lease cleanup. Product run `3a9af7c4...` added native accepted authority-request API proof across `/api/runs`, `/graph/events`, `/graph/patches`, `/graph/topology`, `/graph/nodes/authority-proof-gate`, `/graph/nodes/worker-authority-proof`, `/graph/decisions`, `/graph/scheduler`, and `/graph/final-blockers`: pending authority details were readable before decision, `POST /graph/decisions` emitted the authority decision and bound input, node detail exposed request/decision records and released lease state, topology exposed authority edge binding metadata, scheduler showed the worker ready with no gates/resources/leases, and blockers reflected the still-pending worker. Product callback probes `961b0f47...` and `1010af96...` added heartbeat/lease renewal readback and late stale-callback readback through `/api/runs`, `/graph`, `/graph/events`, and `/graph/scheduler`. Product run `7bd58637...` added path-scoped multi-ready readback across `/api/runs`, `/graph`, `/graph/scheduler`, full `/graph/events`, `/graph/topology`, `/graph/nodes` for all three workers, `/graph/decisions`, `/graph/patches`, `/graph/regions`, and `/graph/final-blockers`; the readbacks exposed scoped claims, active docs/tests leases, overlap `waiting_resources`, zero pre-cancel `agent_died`, and post-cancel no active leases. Product run `a9b658fa...` added artifact/output callback readback across `/api/runs`, `/graph`, bounded full `/graph/events`, `/graph/scheduler`, `/graph/nodes/worker-s-01-t-01`, `/graph/regions`, and `/graph/final-blockers`: it exposed the accepted artifact-reference record, file-state bindings, released lease, completed run, accepted region, and no blockers. Product run `32be2af2...` added failure-tail readback across `/api/runs`, `/graph`, bounded full `/graph/events`, `/graph/scheduler`, and `/graph/nodes/worker-s-01-t-01`: it exposed repeated `agent_died` callbacks, lease revocation, retry scheduling, recovery-plan output records, paused graph state, and no active leases. The FR-16 harness adds repeatable terminal failure-record API readback through `/api/runs`, `/graph`, `/graph/events`, `/graph/nodes/worker-step-1-task-1`, `/graph/scheduler`, and `/graph/final-blockers`. The final-gate harness adds repeatable explicit `final_gate` readback through `/api/runs`, `/graph`, `/graph/events`, `/graph/nodes/final-gate-s-01-t-01`, `/graph/topology`, `/graph/regions`, `/graph/final-blockers`, and `/graph/scheduler`, including bound check-result input, output record envelope, lifecycle event, region acceptance, and empty blockers. The row-level harness `tests/integration/test_graph_fr17_acceptance.py::test_fr17_less_used_readbacks_survive_projection_rebuild` closes the remaining API/readback gap for less-used families: it proves recovery, review, appeal, pending/approved human gate, patch diagnostics, bound recovery-plan and decision records, scheduler/lease readbacks, region/final blockers, event positions, run-state coherence, and projection/node-detail rebuild consistency through public graph APIs before and after deleting read models. | validated | No remaining FR-17 gap in the current row scope. Future API surfaces or node/readback families require new criteria. |
| FR-18 End-to-end product proof | A dynamic feature scenario completes from planner-created topology through worker -> verifier -> gap planner -> corrective worker -> verifier -> check -> final gate, with blocked completion until evidence exists. | A real or dogfooded product run demonstrates the full behavior using the intended graph runner/workflow, not only a scripted test harness. | `tests/integration/test_graph_dynamic_e2e.py` mirrors the desired path; runtime code in graph driver/controller/dispatch. | Product run `2aa3be3b...` completed through planner -> worker -> verifier -> gap planner -> corrective worker -> verifier -> deterministic hidden-oracle check -> accepted region -> empty blockers -> run `completed`, including recovery after restart. Fresh run `f85e3af1...` shows typed blockers when a new planner shape does not reach completion. Product run `f3501792...` proves blocked completion after verifier success when the deterministic final invariant fails. 2026-06-22 scope decision: current dynamic-feature product runs are check-gated, not explicit-final-gate-gated. The row-level harness `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py::test_fr01_fr18_two_task_bootstrap_completes` closes the harder-than-smoke gap through a two-task routine with two parallel regions running through the full `GraphRunDriver` lifecycle: planner submits an invalid-then-accepted patch, both workers write task-specific artifacts, verifiers grade requirements, auto-verify checks pass for both regions, `/graph/regions` shows both s-01/t-01 and s-01/t-02 as `accepted`, `/graph/final-blockers=[]`, and public run state is `completed`. This is harder than the single-task smoke test because it involves multi-region evidence accumulation, parallel task dispatch, and completion only after both regions pass their invariants. Explicit final-gate/completion-decision product proof is only required if a product routine creates final-gate nodes (2026-06-22 scope decision unchanged). | validated | No remaining FR-18 gap in the current row scope. Future end-to-end scenarios beyond multi-region check-gated completion require new criteria. |
| FR-19 Comparison-oracle admission | Carrier comparison oracles, hidden tests, and S3 admission are measurement harnesses, not product functionality. | Product completion is not blocked by comparison admission. | `docs/dynamic-graph/complete/comparison-s3-active-graph-diagnostics-spec.md`, `scripts/compare_carriers.py`. | Not required for product validation. | out of scope | Keep comparison status separate from typed-work-graph functional completion. |

## Smallest Incomplete Proof Set

Do not start another broad implementation slice, and do not do another
manual-probe-first pass. The next work must install or extend a repeatable FR
acceptance harness, then use bounded product probes only to calibrate the
remaining live-runner evidence. The next work must move these rows:

0. Acceptance harness: create executable row-level acceptance tests for the
   target FR before attempting status promotion. The harness should drive
   narrow embedded routines through the real graph controller/API surfaces
   wherever possible and assert the exact readback evidence the ledger requires:
   event types and positions, accepted output records, callback history,
   scheduler leases, regions, final blockers, and public run state. Product
   probes should then confirm any `codex_server`/runtime behavior that cannot
   be reproduced deterministically inside the harness. Do not mark any row
   `validated` unless the harness covers the whole row or this ledger scopes out
   the missing cases with rationale.
1. FR-02 is now validated by
   `tests/integration/test_graph_fr02_acceptance.py::test_fr02_canonical_taxonomy_nodes_are_created_and_readable`.
   FR-03 is now validated by
   `tests/integration/test_graph_fr03_acceptance.py::test_fr03_less_used_contracts_govern_validation_runtime_and_readbacks`.
2. FR-06 is now validated by
   `tests/integration/test_graph_fr06_acceptance.py::test_fr06_edges_bind_fanout_join_optional_bind_all_and_supersede`
   for broader fan-out, join, optional-edge, `bind_all`, and first-class
   `rebind_on_superseding` edge/binding behavior.
3. FR-07 is now validated by
   `tests/integration/test_graph_fr07_acceptance.py::test_fr07_macro_tools_route_expand_validate_and_read_back_patch_attempts`
   for the broader macro/tool catalog, including joins, gates,
   retire/supersede, malformed macro args, and disallowed tool rejection.
4. FR-09 is now validated by
   `tests/integration/test_graph_fr09_acceptance.py::test_fr09_execution_packets_and_prompt_hydration_are_readable_for_less_used_nodes`
   for less-used summarizer/gap-planner packet dispatch, contract-derived tool
   exposure, prompt-summary runtime-start readback, and prompt hydration
   policy evidence through public graph APIs.
   FR-10 is now validated by
   `tests/integration/test_graph_fr10_acceptance.py::test_fr10_scheduler_readiness_command_precondition_and_retry_readbacks`
   for command/precondition readiness and retry-backoff scheduling readbacks.
5. FR-01/FR-13/FR-18 are now validated by
   `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py::test_fr01_fr18_two_task_bootstrap_completes`
   (multi-region bootstrap, invalid-patch probe, parallel region completion, no-blocker terminal state)
   and
   `tests/integration/test_graph_fr01_fr13_fr18_acceptance.py::test_fr13_partial_region_blockers_and_invalid_patch_in_blocked_state`
   (partial-region blockers, invalid-actor patch in quiescent state, blocker persistence after rejection).
6. FR-15 is now validated by
   `tests/integration/test_graph_fr15_acceptance.py::test_fr15_gatekeeper_cleanup_is_explicit_graph_work_and_readable`
   and
   `tests/integration/test_graph_fr15_acceptance.py::test_fr15_rejected_file_state_revokes_write_lease_and_retries_cleanly`.
   Product probe `961b0f47...` exposed post-cancel patch acceptance;
   regression now rejects `submit_patch` after the graph run is no longer
   active. Product run `7bd58637...` closes the earlier path-scoped
   non-conflicting write proof gap through public graph/API readbacks. FR-08 is
   now validated by
   `tests/integration/test_graph_fr08_acceptance.py::test_fr08_invalid_patch_matrix_rejected_and_readable`
   and
   `tests/integration/test_graph_fr08_acceptance.py::test_fr08_authority_denial_and_rejection_readbacks`
   for invalid-patch diagnostics, hidden-command scrubbing, authority denial,
   and authority rejection; authority revocation is scoped out until a
   first-class revocation command exists. FR-11 is now validated by
   `tests/integration/test_graph_fr11_acceptance.py::test_fr11_scheduler_orders_frontier_and_progresses_deferred_work`
   for deterministic repeated-tick ordering, non-conflicting progress, and
   resource-blocked eventual progress after lease release.
