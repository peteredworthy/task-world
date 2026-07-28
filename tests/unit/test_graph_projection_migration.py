from collections import Counter
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from scripts.codemods.migrate_graph_projection_queries import (
    AnchorRefusedError,
    DispositionPlan,
    OperationStream,
    SourceSnapshot,
    compile_operation_stream,
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
    validate_query_migration_manifest,
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


def test_repository_inventory_includes_controller_rebuild_dispatch_reads(
    live_migration_context: LiveMigrationContext,
) -> None:
    inventory = live_migration_context.inventory
    dispatch_diagnostics = {
        (item.qualified_function, item.line)
        for item in inventory.diagnostics
        if item.relative_path == "src/orchestrator/graph_runtime/dispatch.py"
    }

    assert ("GraphDispatchExecutor._dispatch_snapshot_cleanup", 810) in dispatch_diagnostics
    assert ("_requirements_for_node", 966) in dispatch_diagnostics
    source_lines = (ROOT / "src/orchestrator/graph_runtime/dispatch.py").read_text().splitlines()
    assert (
        source_lines[809].strip()
        == 'compromised_record = projection["file_state_records"].get(record_id)'
    )
    assert source_lines[965].strip() == (
        'for port, binding in projection["input_bindings"].get(node_id, {}).items():'
    )


def test_repository_inventory_keeps_representative_task_3c_physical_reads(
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
        relative_path: (ROOT / relative_path).read_text().splitlines()
        for relative_path in (
            "src/orchestrator/graph_runtime/dispatch.py",
            "src/orchestrator/graph_runtime/prompts.py",
            "src/orchestrator/graph/callbacks.py",
            "src/orchestrator/graph/patch_validator.py",
        )
    }

    assert source_lines["src/orchestrator/graph_runtime/dispatch.py"][809].strip() == (
        'compromised_record = projection["file_state_records"].get(record_id)'
    )
    assert source_lines["src/orchestrator/graph_runtime/prompts.py"][551].strip() == (
        'ready_nodes = sorted(projection["ready_nodes"])'
    )
    assert source_lines["src/orchestrator/graph/callbacks.py"][68].strip() == (
        'lease = projection["leases"].get(request.lease_id)'
    )
    assert source_lines["src/orchestrator/graph/patch_validator.py"][145].strip() == (
        'and projection["node_kinds"].get(node_id) in {"worker", "verifier", "check"}'
    )
    assert {
        (
            "src/orchestrator/graph_runtime/dispatch.py",
            "GraphDispatchExecutor._dispatch_snapshot_cleanup",
            'compromised_record = projection["file_state_records"].get(record_id)',
            "record_file_state",
        ),
        (
            "src/orchestrator/graph_runtime/prompts.py",
            "_planner_outstanding_failures",
            'for region_id, failure in projection["environment_failures"].items():',
            "planning_session",
        ),
        (
            "src/orchestrator/graph/callbacks.py",
            "validate_callback",
            'lease = projection["leases"].get(request.lease_id)',
            "cleanup_callback",
        ),
        (
            "src/orchestrator/graph/patch_validator.py",
            "validate_patch",
            'and projection["node_kinds"].get(node_id) in {"worker", "verifier", "check"}',
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
            "projection['passed_verification_candidate_ids']",
            "verification_recovery",
        ),
        (
            "src/orchestrator/graph_runtime/recovery.py",
            "recover",
            "projection = rebuild_projection(events)",
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
    inventory = live_migration_context.inventory
    ledger = live_migration_context.ledger
    skeleton = live_migration_context.skeleton

    lifecycle_keys = {
        site.site_key for site in skeleton.unclassified_sites if site.domain == "lifecycle"
    }
    classified_keys = {
        disposition.site_key
        for disposition in ledger.dispositions
        if disposition.site_key in lifecycle_keys
    }

    assert classified_keys == lifecycle_keys
    assert not {site.site_key for site in ledger.unclassified_sites} & lifecycle_keys
    assert {
        disposition.disposition
        for disposition in ledger.dispositions
        if disposition.relative_path == "src/orchestrator/graph/projection_queries.py"
    } == {"approved_core"}
    core_keys = {
        site.site_key for site in skeleton.unclassified_sites if site.domain == "approved_core"
    }
    assert {
        disposition.site_key
        for disposition in ledger.dispositions
        if disposition.disposition == "approved_core"
    } == core_keys
    assert not {site.site_key for site in ledger.unclassified_sites} & core_keys
    assert validate_query_migration_manifest(ledger, inventory, ROOT, domain="approved_core") == {
        "approved_core": len(core_keys)
    }
    lifecycle_dispositions = [
        disposition for disposition in ledger.dispositions if disposition.site_key in lifecycle_keys
    ]
    assert all(
        disposition.disposition == "query_transform"
        for disposition in lifecycle_dispositions
        if 'projection["' in disposition.normalized_source_pattern
    )
    assert all(
        disposition.disposition == "projection_neutral"
        for disposition in lifecycle_dispositions
        if 'projection["' not in disposition.normalized_source_pattern
        and disposition.diagnostic_code is not None
    )
    target_domains = {
        "cleanup_callback",
        "governance_requirements",
        "lease",
        "node_task_edge_binding",
        "planning_session",
        "record_file_state",
    }
    for domain in target_domains:
        domain_keys = {
            site.site_key for site in skeleton.unclassified_sites if site.domain == domain
        }
        assert {
            disposition.site_key
            for disposition in ledger.dispositions
            if disposition.site_key in domain_keys
        } == domain_keys
        assert not {site.site_key for site in ledger.unclassified_sites} & domain_keys
        assert validate_query_migration_manifest(ledger, inventory, ROOT, domain=domain) == {
            domain: len(domain_keys)
        }
    assert Counter(site.domain for site in ledger.unclassified_sites) == {"test_fixture": 349}
    verification_recovery_keys = {
        site.site_key
        for site in skeleton.unclassified_sites
        if site.domain == "verification_recovery"
    }
    assert {
        disposition.site_key
        for disposition in ledger.dispositions
        if disposition.site_key in verification_recovery_keys
    } == verification_recovery_keys
    assert not {site.site_key for site in ledger.unclassified_sites} & verification_recovery_keys
    assert validate_query_migration_manifest(
        ledger, inventory, ROOT, domain="verification_recovery"
    ) == {"verification_recovery": 151}
    assert validate_query_migration_manifest(ledger, inventory, ROOT, domain="lifecycle") == {
        "lifecycle": len(lifecycle_keys)
    }


def test_live_reviewed_ledger_compiles_once_and_defers_only_fixture_sites(
    live_migration_context: LiveMigrationContext,
) -> None:
    stream = live_migration_context.stream
    ledger = live_migration_context.ledger
    plan = live_migration_context.reviewed_plan

    assert len(plan.operations) == len(ledger.dispositions)
    assert len(plan.consumed_site_ids) == len(ledger.dispositions)
    assert len(plan.deferred_site_ids) == 349
    assert len(plan.pending_site_ids) == 100
    assert plan.consumed_site_ids | set(plan.deferred_site_ids) | set(plan.pending_site_ids) == {
        site.original_site_id for site in stream.sites
    }
    assert plan.disposition_counts == (
        ("approved_core", 80),
        ("projection_neutral", 73),
        ("query_transform", 201),
    )
    assert plan.shape_group_counts == tuple(sorted(plan.shape_group_counts))
    assert all(operation.reason for operation in plan.operations)
    assert tuple(operation.consumed_site_ids[0] for operation in plan.operations) == tuple(
        sorted(operation.consumed_site_ids[0] for operation in plan.operations)
    )
    assert plan.deferred_site_ids == tuple(sorted(plan.deferred_site_ids))
    assert plan.pending_site_ids == tuple(sorted(plan.pending_site_ids))
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
    deferred = ledger.unclassified_sites[0]
    with pytest.raises(AnchorRefusedError, match="deferred fixture"):
        plan_reviewed_dispositions(
            stream,
            ledger.model_copy(
                update={
                    "unclassified_sites": (
                        deferred.model_copy(update={"domain": "post_ledger"}),
                        *ledger.unclassified_sites[1:],
                    )
                }
            ),
        )
    without_fixture = plan_reviewed_dispositions(
        stream,
        ledger.model_copy(update={"unclassified_sites": ledger.unclassified_sites[1:]}),
    )
    assert deferred.site_key in without_fixture.pending_site_ids


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
    assert len(raw_fixture_site_ids) == 449
    assert len(deferred_fixture_site_ids) == 349
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
    assert len(plan.operations) == 433
    assert len(plan.deferred_site_ids) == 370
    assert plan.disposition_counts == (
        ("approved_core", 80),
        ("projection_neutral", 152),
        ("query_transform", 201),
    )
    assert plan.rule_family_counts == (
        ("derived_value_sink", 1),
        ("projector_fixture_flow", 2),
        ("public_graph_call", 116),
        ("typed_projection_binding", 27),
        ("typed_projector_binding", 6),
    )
    assert plan.generated_fixture_family_counts == (
        ("literal_field_update_mutation", 3),
        ("physical_append_extend", 1),
        ("physical_nested_assignment", 17),
    )
    assert len(plan.reviewed_deferred_site_ids) == 349
    assert len(plan.generated_fixture_operations) == 21
    assert sum(count for _, count in plan.symbol_origin_counts) == 152
    assert dict(plan.symbol_origin_counts)["orchestrator.graph.scheduler.NodeScheduleInfo"] == 1
    assert plan == plan_structural_dispositions(
        stream.model_copy(update={"sites": tuple(reversed(stream.sites))}),
        ledger.model_copy(
            update={
                "dispositions": tuple(reversed(ledger.dispositions)),
                "unclassified_sites": tuple(reversed(ledger.unclassified_sites)),
            }
        ),
    )
