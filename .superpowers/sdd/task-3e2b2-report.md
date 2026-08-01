# Task 3e2b2 Policy Hardening Report

## Machine-derived closure

The structural compiler closes the unchanged 803-site inventory exactly: 201
query transforms, 80 approved-core physical reads, 152 projection-neutral
operations, 349 reviewed deferred fixture IDs, and 21 generated fixture
operations. Pending and unmatched IDs are empty.

Generated fixture operations are explicit frozen records and derive their
counts from their finite rule IDs: 17 `physical_nested_assignment`, 3
`literal_field_update_mutation`, and 1 `physical_append_extend`.

Neutral rule records derive the exact family counts: 116 `public_graph_call`,
27 `typed_projection_binding`, 6 `typed_projector_binding`, 2
`projector_fixture_flow`, and 1 `derived_value_sink`.

The exact sorted symbol-origin snapshot is:

```text
GraphProjection=1; _commands.GraphProjection=26; accepted_graph_patch_ids=1;
accepted_no_successor_patch_id=1; accepted_no_successor_patch_ids=1;
accepted_output_records=2; accepted_output_records_for_node_port=3;
authority_revision_blocker=2; build_projection=1; callbacks.validate_callback=1;
check_result=3; check_results=4; completion_decision_passed=2; configured_gates=2;
decision_request=2; environment_failure=1; environment_failures=1;
failed_verification_candidate_ids=2; failed_verification_result=4;
failed_verification_results=3; gate_decision=2; initial_projection=1;
invalid_test_block=3; invalid_test_blocks=4; latest_routine_snapshot_record=3;
node_gate_decision=2; node_states=2; node_usage_recorded=3; oversight_decision=2;
passed_verification_candidate_ids=2; passed_verification_result=4;
passed_verification_results=3; patch_validator.validate_patch=1;
planner_generation_budget=1; project_decision_view=1;
project_decision_view_from_projection=1; project_final_invariant_blockers=2;
project_graph_projection_snapshot=1; project_lease_view=2; project_leases=4;
project_node_metadata=2; project_node_states=4; project_ready_nodes=1;
project_run_state=2; project_scheduler_view=3; project_task_states=2;
projection_queries.resource_claims_for_node=1; projection_to_checkpoint=2;
projections.final_invariant_blockers_for_events=2; projections.reduce_event=2;
recovery_nodes=3; recovery_nodes_for_record=4; reduce_event=3;
requirement_revision=1; run_state=3; scheduler.NodeScheduleInfo=1;
support_evidence=1; task_states=2; verifier_verdict=5;
graph_runtime.controller.rebuild_projection=1
```

Every name except `graph_runtime.controller.rebuild_projection` is rooted at
`orchestrator.graph.`; the final name is rooted at `orchestrator.graph_runtime.`.

## Policy evidence

Collector and anchor evidence records the imported origin, exact projection
expression/argument role, and physical field/access/operation facts. Outer
wrappers are re-anchored by collecting descendant physical signatures and
accepting exactly one signature that matches all stored receiver, field,
access-kind, and operation-shape facts. Zero or multiple exact matches refuse
the anchor; no traversal order is policy.

Approved-core entries must be in the exact five-file allowlist and have proven
GraphProjection physical receiver evidence matching a finite read-only shape
set. Generated fixtures are recognized only by the three finite mutation
families above. Unknown, foreign, dynamic, ambiguous, missing, diagnostic-only,
or untyped evidence cannot fall through into either disposition.

## Files changed

- `scripts/graph_projection_inventory.py`
- `scripts/codemods/migrate_graph_projection_queries.py`
- `tests/unit/test_migrate_graph_projection_queries.py`
- `.superpowers/sdd/task-3e2b2-report.md`

## Verification

- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py::test_structural_plan_closes_reviewed_and_public_query_test_sites -v` — passed (1 test, 168.47s).
- `uv run pytest tests/unit/test_migrate_graph_projection_queries.py -v` — 50 passed (178.09s).
- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — 746 files already formatted.
- `uv run pyright` — 0 errors, 0 warnings, 0 informations.
- `uv run pytest` — 5040 passed, 3 skipped, 3 unrelated SQLite deprecation warnings (317.40s).
