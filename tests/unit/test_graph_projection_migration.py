from collections import Counter
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from scripts.codemods.migrate_graph_projection_queries import (
    DispositionPlan,
    OperationStream,
    SourceSnapshot,
    compile_operation_stream,
    compile_query_composition_plan,
    compile_query_replacement_plan,
    plan_reviewed_dispositions,
    plan_structural_dispositions,
)
from scripts.graph_projection_inventory import (
    AccessInventory,
    DiagnosticCode,
    ProjectionMigrationManifest,
    QueryMigrationManifest,
    diagnostic_artifact,
    inventory_repository,
    load_manifest,
    load_query_migration_manifest,
    query_migration_skeleton,
)


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_manifest.yaml"
QUERY_MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_query_migration.yaml"

pytestmark = [pytest.mark.slow, pytest.mark.graph_projection_migration]


class LiveMigrationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ProjectionMigrationManifest
    inventory: AccessInventory
    sources: tuple[SourceSnapshot, ...]
    skeleton: QueryMigrationManifest
    ledger: QueryMigrationManifest
    stream: OperationStream
    reviewed_plan: DispositionPlan
    structural_plan: DispositionPlan


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
    reviewed_plan = plan_reviewed_dispositions(stream, ledger)
    structural_plan = plan_structural_dispositions(stream, ledger)
    return LiveMigrationContext(
        manifest=manifest,
        inventory=inventory,
        sources=sources,
        skeleton=skeleton,
        ledger=ledger,
        stream=stream,
        reviewed_plan=reviewed_plan,
        structural_plan=structural_plan,
    )


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
    assert (
        diagnostic_artifact(live_migration_context.inventory)
        == (ROOT / "docs/graph-projection-inventory-diagnostics.md").read_text()
    )


def test_checked_query_ledger_matches_the_fresh_repository_inventory(
    live_migration_context: LiveMigrationContext,
) -> None:
    ledger = live_migration_context.ledger
    skeleton = live_migration_context.skeleton

    current_keys = {site.site_key for site in skeleton.unclassified_sites}
    reviewed_keys = {item.site_key for item in ledger.dispositions}
    deferred_keys = {item.site_key for item in ledger.unclassified_sites}

    assert reviewed_keys <= current_keys
    assert deferred_keys <= current_keys
    assert not reviewed_keys & deferred_keys
    assert Counter(item.disposition for item in ledger.dispositions) == {
        "approved_core": 80,
        "projection_neutral": 65,
    }
    assert Counter(site.domain for site in ledger.unclassified_sites) == {}
    assert not any(item.disposition == "query_transform" for item in ledger.dispositions)
    assert {
        disposition.disposition
        for disposition in ledger.dispositions
        if disposition.relative_path == "src/orchestrator/graph/projection_queries.py"
    } == {"approved_core"}
    core_keys = {
        site.site_key for site in skeleton.unclassified_sites if site.domain == "approved_core"
    }
    reviewed_core_keys = {
        disposition.site_key
        for disposition in ledger.dispositions
        if disposition.disposition == "approved_core"
    }
    assert reviewed_core_keys < core_keys
    generated_core_keys = core_keys - reviewed_core_keys
    assert len(generated_core_keys) == 56
    assert {
        site.relative_path
        for site in skeleton.unclassified_sites
        if site.site_key in generated_core_keys
    } == {"src/orchestrator/graph/projection_queries.py"}
    assert not {site.site_key for site in ledger.unclassified_sites} & core_keys
    assert len(current_keys - reviewed_keys - deferred_keys) == 609


def test_live_reviewed_ledger_compiles_once_and_defers_only_fixture_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    stream = live_migration_context.stream
    ledger = live_migration_context.ledger
    plan = live_migration_context.reviewed_plan

    assert len(plan.operations) == len(ledger.dispositions)
    assert len(plan.consumed_site_ids) == len(ledger.dispositions)
    assert len(plan.deferred_site_ids) == 0
    assert len(plan.pending_site_ids) == 609
    assert plan.consumed_site_ids | set(plan.deferred_site_ids) | set(plan.pending_site_ids) == {
        site.original_site_id for site in stream.sites
    }
    assert plan.disposition_counts == (
        ("approved_core", 80),
        ("projection_neutral", 65),
    )
    assert plan.shape_group_counts == tuple(sorted(plan.shape_group_counts))
    assert all(operation.reason for operation in plan.operations)
    assert tuple(operation.consumed_site_ids[0] for operation in plan.operations) == tuple(
        sorted(operation.consumed_site_ids[0] for operation in plan.operations)
    )
    assert plan.deferred_site_ids == tuple(sorted(plan.deferred_site_ids))
    assert plan.pending_site_ids == tuple(sorted(plan.pending_site_ids))
    assert not any(operation.disposition == "query_transform" for operation in plan.operations)
    reasons = {item.site_key: (item.disposition, item.reason) for item in ledger.dispositions}
    assert {
        (item.consumed_site_ids[0], item.disposition, item.reason) for item in plan.operations
    } == {(site_id, disposition, reason) for site_id, (disposition, reason) in reasons.items()}
    assert (
        plan_reviewed_dispositions(
            stream.model_copy(update={"sites": tuple(reversed(stream.sites))}),
            ledger.model_copy(
                update={
                    "dispositions": tuple(reversed(ledger.dispositions)),
                    "unclassified_sites": tuple(reversed(ledger.unclassified_sites)),
                }
            ),
        )
        == plan
    )
    assert ledger.unclassified_sites == ()


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
    assert len(raw_fixture_site_ids) == 317
    assert len(deferred_fixture_site_ids) == 0
    assert deferred_fixture_site_ids <= raw_fixture_site_ids
    assert all(compiled_site_ids.count(site_id) == 1 for site_id in raw_fixture_site_ids)
    assert all(compiled_site_ids.count(site_id) == 1 for site_id in deferred_fixture_site_ids)
    assert all(
        site.diagnostic_code is None or site.diagnostic_code in DiagnosticCode
        for site in stream.sites
    )


def test_structural_plan_closes_reviewed_and_public_query_test_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    plan = live_migration_context.structural_plan
    stream = live_migration_context.stream
    ledger = live_migration_context.ledger

    assert plan.pending_site_ids == ()
    assert len(plan.operations) == 754
    assert len(plan.deferred_site_ids) == 0
    assert plan.disposition_counts == (
        ("approved_core", 136),
        ("projection_neutral", 618),
    )
    assert plan.rule_family_counts == (
        ("fixture_mutation_helper", 1),
        ("fixture_projection_argument", 265),
        ("fixture_projection_keyword", 25),
        ("handled_projection_comparison", 10),
        ("projection_cast", 9),
        ("projector_fixture_flow", 6),
        ("public_graph_call", 265),
        ("typed_projection_binding", 33),
        ("typed_projection_field_constructor", 1),
        ("typed_projection_return", 2),
        ("typed_projector_binding", 1),
    )
    assert plan.generated_fixture_family_counts == ()
    assert len(plan.reviewed_deferred_site_ids) == 0
    assert len(plan.generated_fixture_operations) == 0
    assert sum(count for _, count in plan.symbol_origin_counts) == 618
    assert plan == plan_structural_dispositions(
        stream.model_copy(update={"sites": tuple(reversed(stream.sites))}),
        ledger.model_copy(
            update={
                "dispositions": tuple(reversed(ledger.dispositions)),
                "unclassified_sites": tuple(reversed(ledger.unclassified_sites)),
            }
        ),
    )


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
