# Dynamic Graph P1 Resolution Ledger

This ledger is the checklist for claiming P1 completion. An item is not closed
by prose, nearby cleanup, or green unrelated tests. It is closed only when the
invariant has an executable reproduction or regression test, an implementation
change, and a recorded verification command.

## P1 Items

| # | P1 item | Required invariant | Status | Evidence |
| --- | --- | --- | --- | --- |
| 3 | Cross-region task-state supersession | A corrective-region pass must supersede the origin region's `needs_revision`, or corrective candidates must be forced into the origin region. | Fixed | `tests/unit/test_graph_projections.py::test_corrective_region_pass_supersedes_origin_needs_revision`. The projection stores `supersedes_task_region_id(s)` on task candidates and accepted corrective regions clear origin regions currently in `needs_revision`. |
| 4 | Late-callback acceptance for expired-but-uncontested leases | A callback for an expired lease is accepted when execution identity still matches and no competing redispatch has claimed the node. | Fixed | `tests/unit/test_callbacks.py::test_expired_uncontested_lease_with_matching_execution_accepted` and `tests/unit/test_callbacks.py::test_expired_redispatched_lease_rejected_as_contested`. Expired callbacks require recorded expiry, matching execution identity, and no replacement active lease. |
| 5 | Node-expectation redesign | Evidence requirements cannot be poisoned by one brittle node identity when producer-class evidence satisfies the intent. | Fixed | `tests/unit/test_graph_commands.py::test_callback_binds_required_input_by_wildcard_producer_class_edge`. Main uses explicit wildcard producer-class edges (`from_node_id: "*"`, `from_node_kind`, `from_node_role`) rather than another node-id special case. |
| 6 | Kernel dead-input detection | If a required edge source is terminally failed with no viable retry/successor, the kernel emits explicit unsatisfiable/dead-input state instead of generic `graph_blocked`. | Fixed | `tests/unit/test_graph_projections.py::test_final_blockers_report_dead_required_input_from_terminal_source`, `tests/unit/test_scheduler.py::test_evaluate_readiness_dead_required_input_from_failed_source`, and `tests/unit/test_graph_commands.py::test_schedule_tick_marks_dead_required_input_when_required_source_failed_unbound`. |
| 7 | Projection parity coverage for task-state fields | Summary/light reads cannot drift from full projection task-state semantics. | Fixed | `tests/integration/test_graph_read_models.py::test_projection_read_model_preserves_task_state_matrix` covers accepted, accepted-with-gate, needs-revision, blocked-invalid-test, blocked-environment, in-progress, and pending task states across full events, compact projection events, stored snapshots, and rebuilt snapshots. `tests/integration/test_graph_read_models.py::test_projection_read_model_preserves_corrective_supersession_task_states` covers corrective supersession parity. Compact graph payload fields include task-state decision fields and `supersedes_task_region_id(s)`. |
| 8 | Patch-validator embedded revision nodes | Nodes embedded in `create_revision_attempt` patches are registered for same-patch follow-up edges. | Fixed | `tests/unit/test_patch_validator.py::test_create_edge_accepts_revision_attempt_embedded_nodes_in_same_patch` and `tests/unit/test_graph_commands.py::test_submit_patch_accepts_edge_between_revision_attempt_embedded_nodes`. |
| 9 | `claude_sdk` graph submit fix | `claude_sdk` can submit graph callbacks through the same path as the reliable graph runner, or is explicitly gated off with a reproduction-backed reason. | Fixed | `tests/unit/test_claude_sdk_agent.py::TestBuildOrchestratorMcpServer::test_submit_graph_patch_accepts_object_patch_through_mcp_handler`. The SDK MCP tool uses explicit JSON Schema accepting object patches and preserving JSON-string fallback. |

## Closure Rule

Before any future response claims "P1 complete", verify this checklist against
fresh test output. If any row loses its executable regression coverage, the
correct status is "P1 remains partially complete".
