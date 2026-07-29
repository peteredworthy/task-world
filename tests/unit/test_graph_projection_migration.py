from pathlib import Path
import subprocess

import pytest
from pydantic import BaseModel, ConfigDict

from scripts.codemods.migrate_graph_projection_queries import (
    DispositionPlan,
    OperationStream,
    QueryMigrationReport,
    SourceSnapshot,
    compile_current_tree_closure,
    compile_operation_stream,
    compile_query_composition_plan,
    compile_query_replacement_plan,
    plan_structural_dispositions,
)
from scripts.graph_projection_inventory import (
    AccessInventory,
    CurrentClosureSite,
    DiagnosticCode,
    ProjectionMigrationManifest,
    QueryMigrationManifest,
    inventory_repository,
    current_closure_identity,
    load_manifest,
    load_query_migration_manifest,
    query_migration_skeleton,
)


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_manifest.yaml"
QUERY_MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_query_migration.yaml"
QUERY_REPORT_PATH = ROOT / "tests/fixtures/graph_projection_migration/query_migration_report.json"

_APPROVED_CORE_READ_SHAPES = frozenset(
    {
        "subscript_read",
        "literal_subscript_read",
        "map_get",
        "keys_iteration",
        "values_iteration",
        "items_iteration",
        "membership",
        "nested_get",
        "items",
        "values",
    }
)
_APPROVED_CORE_POLICY = {
    path: _APPROVED_CORE_READ_SHAPES
    for path in (
        "src/orchestrator/graph/projection_models.py",
        "src/orchestrator/graph/projection_collections.py",
        "src/orchestrator/graph/projection_queries.py",
        "src/orchestrator/graph/projection_codec.py",
        "src/orchestrator/graph/projections.py",
    )
}
_GRAPH_PROJECTION_ORIGINS = frozenset(
    {
        "orchestrator.graph.GraphProjection",
        "orchestrator.graph._commands.GraphProjection",
        "orchestrator.graph.projections.GraphProjection",
    }
)
_PROJECTION_FACTORIES = frozenset(
    {
        "orchestrator.graph.initial_projection",
        "orchestrator.graph.build_projection",
        "orchestrator.graph.reduce_event",
        "orchestrator.graph.projection_from_checkpoint",
        "orchestrator.graph_runtime.controller.rebuild_projection",
        "orchestrator.graph.projections.reduce_event",
    }
)
_NEUTRAL_RULE_IDS = frozenset(
    {
        "projection_cast",
        "fixture_mutation_helper",
        "typed_projection_return",
        "handled_projection_comparison",
        "typed_projection_binding",
        "typed_projector_binding",
        "typed_projection_field_constructor",
        "fixture_projection_keyword",
        "fixture_projection_argument",
        "derived_value_sink",
        "fixture_public_graph_call",
        "public_graph_call",
        "projector_fixture_flow",
    }
)
_PUBLIC_GRAPH_POSITION_ZERO_CALLS = frozenset(
    {
        "orchestrator.graph.apply_command",
        "orchestrator.graph.commands.apply_command",
        "orchestrator.graph.edges_view",
        "orchestrator.graph.environment_failures_view",
        "orchestrator.graph.file_state_records_view",
        "orchestrator.graph.input_bindings_view",
        "orchestrator.graph.leases_view",
        "orchestrator.graph.node_kinds_view",
        "orchestrator.graph.node_states_view",
        "orchestrator.graph.node_task_regions_view",
        "orchestrator.graph.planner_generation_budget",
        "orchestrator.graph.planner_generations_view",
        "orchestrator.graph.planner_session_carryovers_view",
        "orchestrator.graph.planner_sessions_view",
        "orchestrator.graph.project_decision_view_from_projection",
        "orchestrator.graph.projection_queries.accepted_graph_patches_by_node_view",
        "orchestrator.graph.projection_queries.accepted_no_successor_patches_by_node_view",
        "orchestrator.graph.projection_queries.accepted_output_records_by_node_port_view",
        "orchestrator.graph.projection_queries.accepted_record_summaries_by_id_view",
        "orchestrator.graph.projection_queries.active_requirement_versions_view",
        "orchestrator.graph.projection_queries.callback_idempotency_events_view",
        "orchestrator.graph.projection_queries.check_results_view",
        "orchestrator.graph.projection_queries.cleanup_applied_ids_view",
        "orchestrator.graph.projection_queries.cleanup_requested_events_view",
        "orchestrator.graph.projection_queries.completion_decision_passed",
        "orchestrator.graph.projection_queries.edges_view",
        "orchestrator.graph.projection_queries.failed_verification_candidate_ids_view",
        "orchestrator.graph.projection_queries.failed_verification_results_by_record_id_view",
        "orchestrator.graph.projection_queries.file_state_records_view",
        "orchestrator.graph.projection_queries.input_bindings_view",
        "orchestrator.graph.projection_queries.last_deferred_reasons_view",
        "orchestrator.graph.projection_queries.latest_routine_snapshot_record",
        "orchestrator.graph.projection_queries.leases_view",
        "orchestrator.graph.projection_queries.node_attempts_view",
        "orchestrator.graph.projection_queries.node_command_definitions_view",
        "orchestrator.graph.projection_queries.node_creation_positions_view",
        "orchestrator.graph.projection_queries.node_failed_candidates_view",
        "orchestrator.graph.projection_queries.node_gate_decisions_view",
        "orchestrator.graph.projection_queries.node_kinds_view",
        "orchestrator.graph.projection_queries.node_pending_appeals_view",
        "orchestrator.graph.projection_queries.node_preconditions_view",
        "orchestrator.graph.projection_queries.node_resource_claims_view",
        "orchestrator.graph.projection_queries.node_roles_view",
        "orchestrator.graph.projection_queries.node_states_view",
        "orchestrator.graph.projection_queries.node_task_regions_view",
        "orchestrator.graph.projection_queries.output_records_by_node_port_view",
        "orchestrator.graph.projection_queries.passed_verification_candidate_ids_view",
        "orchestrator.graph.projection_queries.passed_verification_results_by_record_id_view",
        "orchestrator.graph.projection_queries.planner_generation_budget",
        "orchestrator.graph.projection_queries.planner_generations_view",
        "orchestrator.graph.projection_queries.planner_sessions_view",
        "orchestrator.graph.projection_queries.ready_nodes_view",
        "orchestrator.graph.projection_queries.recorded_node_usage_keys_view",
        "orchestrator.graph.projection_queries.recovery_nodes_by_record_id_view",
        "orchestrator.graph.projection_queries.resource_claims_for_node",
        "orchestrator.graph.projection_queries.retry_not_before_by_node_view",
        "orchestrator.graph.projection_queries.run_state",
        "orchestrator.graph.projection_queries.task_candidates_view",
        "orchestrator.graph.projection_queries.task_states_view",
        "orchestrator.graph.projection_queries.verifier_verdicts_view",
        "orchestrator.graph.projection_to_checkpoint",
        "orchestrator.graph.ready_nodes_view",
        "orchestrator.graph.run_state",
        "orchestrator.graph.task_states_view",
    }
)
_PUBLIC_GRAPH_KEYWORD_CALLS = frozenset(
    {
        "orchestrator.graph.project_decision_view",
        "orchestrator.graph.project_final_invariant_blockers",
        "orchestrator.graph.project_graph_projection_snapshot",
        "orchestrator.graph.project_lease_view",
        "orchestrator.graph.project_leases",
        "orchestrator.graph.project_node_metadata",
        "orchestrator.graph.project_node_states",
        "orchestrator.graph.project_ready_nodes",
        "orchestrator.graph.project_run_state",
        "orchestrator.graph.project_scheduler_view",
        "orchestrator.graph.project_task_states",
    }
)
_PUBLIC_GRAPH_CALL_POLICY = {
    **{
        origin: frozenset({("positional", 0, None)}) for origin in _PUBLIC_GRAPH_POSITION_ZERO_CALLS
    },
    **{
        origin: frozenset({("keyword", None, "projection")})
        for origin in _PUBLIC_GRAPH_KEYWORD_CALLS
    },
    "orchestrator.graph.callbacks.validate_callback": frozenset({("positional", 1, None)}),
    "orchestrator.graph.patch_validator.validate_patch": frozenset({("positional", 3, None)}),
    "orchestrator.graph.projections.final_invariant_blockers_for_events": frozenset(
        {("positional", 1, None)}
    ),
    "orchestrator.graph_runtime.store.GraphEventStore.persist_projection_snapshot": frozenset(
        {("positional", 1, None)}
    ),
}

pytestmark = [pytest.mark.slow, pytest.mark.graph_projection_migration]


class LiveMigrationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ProjectionMigrationManifest
    inventory: AccessInventory
    sources: tuple[SourceSnapshot, ...]
    skeleton: QueryMigrationManifest
    ledger: QueryMigrationManifest
    stream: OperationStream
    structural_plan: DispositionPlan
    report: QueryMigrationReport


@pytest.fixture(scope="module")
def live_migration_context() -> LiveMigrationContext:
    manifest = load_manifest(MANIFEST_PATH)
    inventory = inventory_repository(ROOT, manifest)
    sources = tuple(
        SourceSnapshot(relative_path=path.relative_to(ROOT).as_posix(), source=path.read_text())
        for directory in (ROOT / "src", ROOT / "tests", ROOT / "scripts")
        for path in sorted(directory.rglob("*.py"))
        if "__pycache__" not in path.parts
    )
    skeleton = query_migration_skeleton(inventory, ROOT)
    ledger = load_query_migration_manifest(QUERY_MANIFEST_PATH)
    stream = compile_operation_stream(sources, inventory, skeleton)
    structural_plan = plan_structural_dispositions(
        stream, ledger.model_copy(update={"dispositions": (), "unclassified_sites": ()})
    )
    report = QueryMigrationReport.model_validate_json(QUERY_REPORT_PATH.read_text())
    return LiveMigrationContext(
        manifest=manifest,
        inventory=inventory,
        sources=sources,
        skeleton=skeleton,
        ledger=ledger,
        stream=stream,
        structural_plan=structural_plan,
        report=report,
    )


def _assert_independent_semantic_policy(stream: OperationStream, plan: DispositionPlan) -> None:
    sites = {site.original_site_id: site for site in stream.sites}
    neutral = {item.site_id: item for item in plan.neutral_rule_operations}
    for operation in plan.operations:
        assert len(operation.consumed_site_ids) == 1
        site = sites[operation.consumed_site_ids[0]]
        context = site.anchor.context
        if operation.disposition == "approved_core":
            assert site.relative_path in _APPROVED_CORE_POLICY
            assert context is not None
            assert context.projection_role == "receiver"
            assert context.receiver_type_origin in _GRAPH_PROJECTION_ORIGINS
            access_kind = context.physical_access_kind
            assert access_kind is not None
            assert context.physical_operation_shape == access_kind.value
            assert context.physical_operation_shape in _APPROVED_CORE_POLICY[site.relative_path]
            assert site.parent_shape not in {"assignment", "deletion", "mutation"}
            continue
        if operation.disposition != "projection_neutral":
            continue
        evidence = neutral[site.original_site_id]
        assert evidence.rule_id in _NEUTRAL_RULE_IDS
        assert context is None or context.physical_access_kind is None
        if evidence.rule_id == "projection_cast":
            assert site.diagnostic_code is DiagnosticCode.UNSUPPORTED_CALL
            assert context is not None
            assert (context.callee_origin, context.projection_role, context.positional_index) == (
                "typing.cast",
                "positional",
                1,
            )
            assert evidence.origin == context.callee_origin
        elif evidence.rule_id == "fixture_mutation_helper":
            assert site.domain == "test_fixture"
            assert site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
            assert evidence.origin in {
                "tests.unit.graph_test_utils.projection_fixture_append",
                "tests.unit.graph_test_utils.projection_fixture_replace",
                "tests.unit.graph_test_utils.projection_fixture_set",
                "tests.unit.graph_test_utils.projection_fixture_update",
            }
        elif evidence.rule_id == "typed_projection_return":
            assert site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
            assert (site.parent_shape, site.operation_shape, evidence.origin) == (
                "return",
                "typed_pass_through",
                "collector",
            )
        elif evidence.rule_id == "handled_projection_comparison":
            assert site.diagnostic_code is DiagnosticCode.UNSUPPORTED_COMPARISON
            assert context is None
            assert (site.operation_shape, evidence.origin) == ("comparison", "collector")
        elif evidence.rule_id == "typed_projection_binding":
            assert site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING
            assert context is not None
            assert context.receiver_type_origin in _GRAPH_PROJECTION_ORIGINS
            assert evidence.origin == context.receiver_type_origin
        elif evidence.rule_id == "typed_projector_binding":
            assert context is not None
            assert context.callee_origin in _PROJECTION_FACTORIES
            assert evidence.origin == context.callee_origin
            assert site.diagnostic_code is DiagnosticCode.UNSUPPORTED_BINDING or (
                context.projection_role == "receiver"
            )
        elif evidence.rule_id == "typed_projection_field_constructor":
            assert context is not None
            assert context.receiver_type_origin == evidence.origin
            assert context.projection_role == "keyword"
            assert context.keyword_name is not None
        elif evidence.rule_id == "fixture_projection_keyword":
            assert site.domain == "test_fixture"
            assert context is not None
            assert context.projection_role == "keyword"
            assert context.keyword_name in {"projection", "graph_projection"}
            assert evidence.origin == (context.callee_origin or "collector")
        elif evidence.rule_id == "fixture_projection_argument":
            assert site.domain == "test_fixture"
            assert context is not None
            assert context.projection_role == "positional"
            assert context.positional_index is not None
            assert evidence.origin == (context.callee_origin or "collector")
        elif evidence.rule_id == "derived_value_sink":
            assert context is not None
            assert context.projection_role == "derived_value"
            assert context.callee_origin == "orchestrator.graph.scheduler.NodeScheduleInfo"
            assert evidence.origin == context.callee_origin
        elif evidence.rule_id == "fixture_public_graph_call":
            assert site.domain == "test_fixture"
            assert context is not None
            assert context.callee_origin == evidence.origin
            assert context.callee_origin is not None
            assert context.callee_origin.startswith("orchestrator.graph.")
            assert (context.projection_role, context.positional_index, context.keyword_name) in {
                ("positional", 0, None),
                ("keyword", None, "projection"),
            }
        elif evidence.rule_id == "public_graph_call":
            assert context is not None
            assert context.callee_origin == evidence.origin
            assert evidence.origin in _PUBLIC_GRAPH_CALL_POLICY
            assert (context.projection_role, context.positional_index, context.keyword_name) in (
                _PUBLIC_GRAPH_CALL_POLICY[evidence.origin]
            )
            assert site.operation_shape == "call"
        else:
            assert evidence.rule_id == "projector_fixture_flow"
            assert context is not None
            assert context.callee_origin in _PROJECTION_FACTORIES
            assert evidence.origin == context.callee_origin


def test_default_tracked_provider_reports_real_prompt_dispatch_recovery_and_store_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    inventory = live_migration_context.inventory

    diagnosed_paths = {item.relative_path for item in inventory.diagnostics}
    assert {
        "src/orchestrator/graph_runtime/prompts.py",
        "src/orchestrator/graph_runtime/dispatch.py",
        "src/orchestrator/graph_runtime/recovery.py",
        "src/orchestrator/graph_runtime/store.py",
    } <= diagnosed_paths
    assert all("worktrees/" not in path and "vendor/" not in path for path in diagnosed_paths)


def test_repository_inventory_includes_controller_rebuild_dispatch_queries(
    live_migration_context: LiveMigrationContext,
) -> None:
    inventory = live_migration_context.inventory
    dispatch_diagnostics = {
        item.qualified_function
        for item in inventory.diagnostics
        if item.relative_path == "src/orchestrator/graph_runtime/dispatch.py"
    }

    assert "GraphDispatchExecutor._dispatch_snapshot_cleanup" in dispatch_diagnostics
    assert "_requirements_for_node" in dispatch_diagnostics
    source = (ROOT / "src/orchestrator/graph_runtime/dispatch.py").read_text()
    assert "compromised_record = file_state_records_view(projection).get(record_id)" in source
    assert (
        "for port, binding in input_bindings_view(projection).get(node_id, {}).items():" in source
    )


def test_repository_inventory_keeps_representative_task_3c_query_flows(
    live_migration_context: LiveMigrationContext,
) -> None:
    sites = {
        (
            site.relative_path,
            site.qualified_function,
            site.normalized_source_pattern,
            site.domain,
        )
        for site in live_migration_context.skeleton.unclassified_sites
    }
    source_lines = {
        relative_path: (ROOT / relative_path).read_text()
        for relative_path in (
            "src/orchestrator/graph_runtime/dispatch.py",
            "src/orchestrator/graph_runtime/prompts.py",
            "src/orchestrator/graph/callbacks.py",
            "src/orchestrator/graph/patch_validator.py",
        )
    }

    assert (
        "compromised_record = file_state_records_view(projection).get(record_id)"
        in source_lines["src/orchestrator/graph_runtime/dispatch.py"]
    )
    assert (
        "ready_nodes = sorted(ready_nodes_view(projection))"
        in source_lines["src/orchestrator/graph_runtime/prompts.py"]
    )
    assert (
        "lease = leases_view(projection).get(request.lease_id)"
        in source_lines["src/orchestrator/graph/callbacks.py"]
    )
    assert (
        'and node_kinds_view(projection).get(node_id) in {"worker", "verifier", "check"}'
        in (source_lines["src/orchestrator/graph/patch_validator.py"])
    )
    assert {
        (
            "src/orchestrator/graph_runtime/dispatch.py",
            "GraphDispatchExecutor._dispatch_snapshot_cleanup",
            "compromised_record = file_state_records_view(projection).get(record_id)",
            "record_file_state",
        ),
        (
            "src/orchestrator/graph_runtime/prompts.py",
            "_planner_outstanding_failures",
            "for region_id, failure in environment_failures_view(projection).items():",
            "planning_session",
        ),
        (
            "src/orchestrator/graph/callbacks.py",
            "validate_callback",
            "lease = leases_view(projection).get(request.lease_id)",
            "cleanup_callback",
        ),
        (
            "src/orchestrator/graph/patch_validator.py",
            "validate_patch",
            'and node_kinds_view(projection).get(node_id) in {"worker", "verifier", "check"}',
            "governance_requirements",
        ),
    } <= sites


def test_repository_inventory_keeps_verification_recovery_provenance(
    live_migration_context: LiveMigrationContext,
) -> None:
    sites = {
        (site.relative_path, site.qualified_function, site.normalized_source_pattern, site.domain)
        for site in live_migration_context.skeleton.unclassified_sites
    }

    assert {
        (
            "src/orchestrator/graph/_commands.py",
            "_current_failed_verification_results",
            "passed_candidates = passed_verification_candidate_ids_view(projection)",
            "verification_recovery",
        ),
    } <= sites


def test_checked_in_diagnostic_artifact_exactly_matches_full_repository_report(
    live_migration_context: LiveMigrationContext,
) -> None:
    artifact_path = "docs/graph-projection-inventory-diagnostics.md"
    artifact_revision = subprocess.run(
        ("git", "log", "-1", "--format=%H", "--", artifact_path),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    historical_artifact = subprocess.run(
        (
            "git",
            "show",
            f"{artifact_revision}:{artifact_path}",
        ),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert (ROOT / artifact_path).read_text() == historical_artifact


def test_checked_query_ledger_has_unique_reviewed_records_and_finite_policy(
    live_migration_context: LiveMigrationContext,
) -> None:
    ledger = live_migration_context.ledger
    reviewed_keys = [item.site_key for item in ledger.dispositions]
    deferred_keys = {item.site_key for item in ledger.unclassified_sites}

    assert len(reviewed_keys) == len(set(reviewed_keys))
    assert not set(reviewed_keys) & deferred_keys
    assert not ledger.unclassified_sites
    assert all(
        item.disposition != "query_transform" and item.reason.strip()
        for item in ledger.dispositions
    )
    assert {
        disposition.disposition
        for disposition in ledger.dispositions
        if disposition.relative_path == "src/orchestrator/graph/projection_queries.py"
    } == {"approved_core"}


def test_live_reviewed_ledger_compiles_once_and_defers_only_fixture_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    stream = live_migration_context.stream
    plan = live_migration_context.structural_plan

    stream_ids = {site.original_site_id for site in stream.sites}
    consumed_ids = [
        site_id for operation in plan.operations for site_id in operation.consumed_site_ids
    ]
    consumed = set(consumed_ids)
    deferred = set(plan.deferred_site_ids)
    pending = set(plan.pending_site_ids)
    assert len(consumed_ids) == len(consumed)
    assert consumed <= stream_ids
    assert not (consumed & deferred or consumed & pending or deferred & pending)
    assert consumed | deferred | pending == stream_ids
    assert all(operation.reason.startswith("structural:") for operation in plan.operations)
    assert tuple(operation.consumed_site_ids[0] for operation in plan.operations) == tuple(
        sorted(operation.consumed_site_ids[0] for operation in plan.operations)
    )
    assert plan.deferred_site_ids == tuple(sorted(plan.deferred_site_ids))
    assert plan.pending_site_ids == tuple(sorted(plan.pending_site_ids))
    assert plan.pending_site_ids == ()
    assert plan.deferred_site_ids == ()
    assert plan.generated_fixture_operations == ()
    assert not any(operation.disposition == "query_transform" for operation in plan.operations)


def test_live_repository_compilation_includes_every_remaining_fixture_site(
    live_migration_context: LiveMigrationContext,
) -> None:
    inventory = live_migration_context.inventory
    skeleton = live_migration_context.skeleton
    ledger = live_migration_context.ledger
    stream = live_migration_context.stream

    assert len(stream.sites) == len(inventory.occurrences) + len(inventory.diagnostics)
    raw_fixture_site_ids = {
        site.site_key for site in skeleton.unclassified_sites if site.domain == "test_fixture"
    }
    deferred_fixture_site_ids = {
        site.site_key for site in ledger.unclassified_sites if site.domain == "test_fixture"
    }
    compiled_site_ids = [site.original_site_id for site in stream.sites]
    assert deferred_fixture_site_ids <= raw_fixture_site_ids
    assert len(compiled_site_ids) == len(set(compiled_site_ids))
    assert raw_fixture_site_ids <= set(compiled_site_ids)
    assert all(
        site.diagnostic_code is None or site.diagnostic_code in DiagnosticCode
        for site in stream.sites
    )


def test_structural_plan_closes_reviewed_and_public_query_test_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    plan = live_migration_context.structural_plan
    stream = live_migration_context.stream

    assert plan.pending_site_ids == ()
    assert len(plan.deferred_site_ids) == 0
    assert plan.generated_fixture_family_counts == ()
    assert len(plan.reviewed_deferred_site_ids) == 0
    assert len(plan.generated_fixture_operations) == 0
    assert not any(operation.disposition == "query_transform" for operation in plan.operations)
    assert all(operation.reason.startswith("structural:") for operation in plan.operations)
    operations_by_id = {
        site_id: operation
        for operation in plan.operations
        for site_id in operation.consumed_site_ids
    }
    consumed_ids = [
        site_id for operation in plan.operations for site_id in operation.consumed_site_ids
    ]
    stream_by_id = {site.original_site_id: site for site in stream.sites}
    assert len(consumed_ids) == len(operations_by_id)
    assert set(operations_by_id) == set(stream_by_id)
    _assert_independent_semantic_policy(stream, plan)
    neutral_rules = {item.site_id: item.rule_id for item in plan.neutral_rule_operations}
    assert all(
        neutral_rules[site_id].strip()
        for site_id, operation in operations_by_id.items()
        if operation.disposition == "projection_neutral"
    )
    closure_evidence = tuple(
        CurrentClosureSite(
            site_id=site.original_site_id,
            origin=site.origin,
            relative_path=site.relative_path,
            qualified_function=site.qualified_function,
            disposition=operations_by_id[site.original_site_id].disposition,
            rule_id=(
                "approved_core"
                if operations_by_id[site.original_site_id].disposition == "approved_core"
                else neutral_rules[site.original_site_id]
            ),
        )
        for site in stream.sites
    )
    expected_identity = current_closure_identity(live_migration_context.inventory, closure_evidence)
    closure = compile_current_tree_closure(
        live_migration_context.sources, live_migration_context.manifest
    )
    assert closure.identity == expected_identity
    assert live_migration_context.report.current_closure == closure
    assert plan == plan_structural_dispositions(
        stream.model_copy(update={"sites": tuple(reversed(stream.sites))}),
        live_migration_context.ledger.model_copy(
            update={"dispositions": (), "unclassified_sites": ()}
        ),
    )


def test_independent_semantic_policy_rejects_operation_and_allowed_policy_drift(
    live_migration_context: LiveMigrationContext,
) -> None:
    plan = live_migration_context.structural_plan
    sites_by_id = {site.original_site_id: site for site in live_migration_context.stream.sites}
    public_evidence = next(
        item
        for item in plan.neutral_rule_operations
        if item.rule_id == "public_graph_call"
        and (context := sites_by_id[item.site_id].anchor.context) is not None
        and context.projection_role == "keyword"
    )
    wrong_rule_plan = plan.model_copy(
        update={
            "neutral_rule_operations": tuple(
                item.model_copy(update={"rule_id": "typed_projection_return"})
                if item.site_id == public_evidence.site_id
                else item
                for item in plan.neutral_rule_operations
            )
        }
    )
    with pytest.raises(AssertionError):
        _assert_independent_semantic_policy(live_migration_context.stream, wrong_rule_plan)

    wrong_origin = "orchestrator.graph.apply_command"
    public_context = sites_by_id[public_evidence.site_id].anchor.context
    assert public_context is not None
    wrong_origin_plan = plan.model_copy(
        update={
            "neutral_rule_operations": tuple(
                item.model_copy(update={"origin": wrong_origin})
                if item.site_id == public_evidence.site_id
                else item
                for item in plan.neutral_rule_operations
            )
        }
    )
    wrong_origin_stream = live_migration_context.stream.model_copy(
        update={
            "sites": tuple(
                site.model_copy(
                    update={
                        "anchor": site.anchor.model_copy(
                            update={
                                "context": public_context.model_copy(
                                    update={"callee_origin": wrong_origin}
                                )
                            }
                        )
                    }
                )
                if site.original_site_id == public_evidence.site_id
                else site
                for site in live_migration_context.stream.sites
            )
        }
    )
    with pytest.raises(AssertionError):
        _assert_independent_semantic_policy(wrong_origin_stream, wrong_origin_plan)

    first, second = plan.operations[:2]
    grouped_plan = plan.model_copy(
        update={
            "operations": (
                first.model_copy(
                    update={
                        "consumed_site_ids": (*first.consumed_site_ids, *second.consumed_site_ids)
                    }
                ),
                *plan.operations[1:],
            )
        }
    )
    with pytest.raises(AssertionError):
        _assert_independent_semantic_policy(live_migration_context.stream, grouped_plan)


def test_live_query_composition_plan_has_no_remaining_query_transform_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    plan = compile_query_composition_plan(
        live_migration_context.sources,
        live_migration_context.stream,
        live_migration_context.structural_plan,
    )

    assert plan.groups == ()
    assert plan.consumed_site_ids == frozenset()


def test_live_query_replacement_plan_is_empty_after_atomic_source_apply(
    live_migration_context: LiveMigrationContext,
) -> None:
    composition = compile_query_composition_plan(
        live_migration_context.sources,
        live_migration_context.stream,
        live_migration_context.structural_plan,
    )
    plan = compile_query_replacement_plan(
        live_migration_context.sources,
        live_migration_context.stream,
        live_migration_context.structural_plan,
        composition,
    )
    assert plan.recipes == ()
    assert plan.mutation_handoffs == ()
    assert plan.rule_family_counts == ()
    assert plan.query_import_counts == ()
    assert plan.unmatched_family_counts == ()
