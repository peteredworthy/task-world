"""Public query-boundary and migration-disposition behavior."""

from datetime import UTC, datetime
from pathlib import Path
from collections import Counter

import pytest
import yaml
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    active_leases,
    bound_record_ids,
    build_projection,
    completion_decision_passed,
    edge_by_id,
    edges_from_node,
    edges_to_node,
    input_binding_for_port,
    input_bindings_for_node,
    initial_projection,
    iter_edges,
    iter_leases,
    lease_by_id,
    lease_generation,
    node_allowed_actions,
    node_attempt,
    node_candidate_id,
    node_command_definition,
    node_creation_position,
    node_exists,
    node_failed_candidate_id,
    node_kind,
    node_last_deferred_reason,
    node_preconditions,
    node_retry_not_before,
    node_role,
    node_state,
    node_task_region,
    resource_claims_for_node,
    run_state,
    task_candidates,
    task_state,
)
from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    AccessOccurrence,
    IncompleteMigrationDispositionError,
    MigrationDisposition,
    QueryMigrationManifest,
    UnclassifiedMigrationSite,
    classify_node_task_edge_binding_and_lease_domains,
    classify_lifecycle_domain,
    disposition_site_key,
    inventory_repository,
    load_manifest,
    load_query_migration_manifest,
    query_migration_skeleton,
    validate_query_migration_manifest,
)
from tests.unit.graph_test_utils import canonical_event_payload
from tests.graph_fr17_fixture import less_used_events


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_manifest.yaml"
QUERY_MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_query_migration.yaml"


def test_lifecycle_queries_preserve_missing_and_default_values() -> None:
    projection = initial_projection()

    assert run_state(projection) is None
    assert completion_decision_passed(projection) is False


def test_lifecycle_queries_read_active_and_completed_event_projections() -> None:
    active = build_projection((_event("active", "run_lifecycle_changed", _lifecycle("active")),))
    completed = build_projection(
        (
            _event("active", "run_lifecycle_changed", _lifecycle("active")),
            _event(
                "decision",
                "output_record_accepted",
                {
                    "record_id": "decision-1",
                    "record_type": "completion_decision",
                    "producer_node_id": "gate-final",
                    "port": "completion_decision",
                    "value": {"status": "passed"},
                },
            ),
            _event("completed", "run_lifecycle_changed", _lifecycle("completed")),
        )
    )

    assert run_state(active) == "active"
    assert run_state(completed) == "completed"
    assert completion_decision_passed(completed) is True


def test_node_and_task_queries_preserve_missing_values() -> None:
    projection = initial_projection()

    assert node_exists(projection, "missing") is False
    assert node_kind(projection, "missing") is None
    assert node_role(projection, "missing") is None
    assert node_creation_position(projection, "missing") is None
    assert node_task_region(projection, "missing") is None
    assert node_state(projection, "missing") is None
    assert node_attempt(projection, "missing") is None
    assert node_candidate_id(projection, "missing") is None
    assert node_failed_candidate_id(projection, "missing") is None
    assert node_allowed_actions(projection, "missing") == ()
    assert node_preconditions(projection, "missing") == ()
    assert node_command_definition(projection, "missing") is None
    assert node_last_deferred_reason(projection, "missing") is None
    assert node_retry_not_before(projection, "missing") is None
    assert resource_claims_for_node(projection, "missing") == ()
    assert task_state(projection, "missing") is None
    assert task_candidates(projection, "missing") == ()


def test_topology_and_lease_queries_preserve_fixture_order_and_selection() -> None:
    projection = build_projection(less_used_events("query-fixture"))

    assert node_exists(projection, "worker-source") is True
    assert node_kind(projection, "worker-source") == "worker"
    assert node_role(projection, "worker-source") == "builder"
    assert node_task_region(projection, "worker-source") == "task-fr17"
    assert node_state(projection, "recovery-1") == "completed"
    assert node_last_deferred_reason(projection, "review-1") == "merge_conflicts"
    assert node_allowed_actions(projection, "worker-source") == (
        "submit_records",
        "raise_appeal",
    )
    assert node_preconditions(projection, "recovery-1") == ("failure_record_bound",)
    assert node_command_definition(projection, "recovery-1") is not None
    assert tuple(edge.edge_id for edge in iter_edges(projection)) == (
        "edge-failure-recovery",
        "edge-recovery-consumer",
        "edge-decision-consumer",
    )
    assert edge_by_id(projection, "edge-failure-recovery") is not None
    assert tuple(edge.edge_id for edge in edges_from_node(projection, "recovery-1")) == (
        "edge-recovery-consumer",
    )
    assert tuple(edge.edge_id for edge in edges_to_node(projection, "consumer-1")) == (
        "edge-recovery-consumer",
        "edge-decision-consumer",
    )
    assert bound_record_ids(projection, "recovery-1", "failure_record") == ("failure-record-1",)
    assert input_binding_for_port(projection, "recovery-1", "failure_record") is not None
    assert tuple(
        binding.to_port for binding in input_bindings_for_node(projection, "consumer-1")
    ) == ("outstanding_failures",)
    assert lease_by_id(projection, "lease-recovery") is not None
    assert lease_generation(projection, "lease-recovery") == 1
    assert tuple(lease.lease_id for lease in iter_leases(projection)) == ("lease-recovery",)
    assert active_leases(projection) == ()


def test_disposition_site_key_is_stable_without_source_position() -> None:
    first = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state']",
        diagnostic_code=None,
    )
    second = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state']",
        diagnostic_code=None,
    )

    assert first == second


def test_diagnostic_site_keys_distinguish_repeated_identical_patterns() -> None:
    first = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state'].values()",
        diagnostic_code="unsupported_call",
        same_pattern_ordinal=0,
    )
    second = disposition_site_key(
        baseline_revision="baseline",
        relative_path="src/example.py",
        qualified_function="read",
        normalized_source_pattern="projection['run_state'].values()",
        diagnostic_code="unsupported_call",
        same_pattern_ordinal=1,
    )

    assert first != second


def test_partial_manifest_reports_exact_unclassified_inventory_counts() -> None:
    manifest = QueryMigrationManifest(
        baseline_revision="baseline",
        dispositions=(),
    )
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="a" * 64,
                relative_path="src/example.py",
                qualified_function="read",
                normalized_expression="projection['run_state']",
                same_expression_ordinal=0,
                old_field_name="run_state",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="not_applicable",
            ),
        ),
        diagnostics=(),
    )

    with pytest.raises(IncompleteMigrationDispositionError) as raised:
        validate_query_migration_manifest(manifest, inventory, Path.cwd())

    assert raised.value.remaining_counts == {"lifecycle": 1}


def test_lifecycle_classification_covers_its_complete_generated_domain() -> None:
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="c" * 64,
                relative_path="src/example.py",
                qualified_function="read",
                normalized_expression="projection['run_state']",
                same_expression_ordinal=0,
                old_field_name="run_state",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="not_applicable",
            ),
            AccessOccurrence(
                occurrence_id="b" * 64,
                relative_path="src/example.py",
                qualified_function="read",
                normalized_expression="projection['node_states']",
                same_expression_ordinal=0,
                old_field_name="node_states",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=2,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
        ),
        diagnostics=(),
    )

    manifest = classify_lifecycle_domain(query_migration_skeleton(inventory, Path.cwd()))

    assert validate_query_migration_manifest(
        manifest, inventory, Path.cwd(), domain="lifecycle"
    ) == {"lifecycle": 1}


def test_node_and_lease_classification_covers_their_generated_domains() -> None:
    inventory = AccessInventory(
        baseline_revision="baseline",
        occurrences=(
            AccessOccurrence(
                occurrence_id="d" * 64,
                relative_path="src/example.py",
                qualified_function="read_node",
                normalized_expression='projection["node_states"]',
                same_expression_ordinal=0,
                old_field_name="node_states",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=1,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
            AccessOccurrence(
                occurrence_id="e" * 64,
                relative_path="src/orchestrator/graph_runtime/dispatch.py",
                qualified_function="read_lease",
                normalized_expression='projection["leases"]',
                same_expression_ordinal=0,
                old_field_name="leases",
                kind=AccessKind.LITERAL_SUBSCRIPT_READ,
                line=2,
                column=0,
                ordering_sensitivity_disposition="insensitive",
            ),
        ),
        diagnostics=(),
    )

    manifest = classify_node_task_edge_binding_and_lease_domains(
        query_migration_skeleton(inventory, Path.cwd())
    )

    assert validate_query_migration_manifest(
        manifest, inventory, Path.cwd(), domain="node_task_edge_binding"
    ) == {"node_task_edge_binding": 1}
    assert validate_query_migration_manifest(manifest, inventory, Path.cwd(), domain="lease") == {
        "lease": 1
    }


@pytest.mark.timeout(120)
def test_checked_query_ledger_matches_the_fresh_repository_inventory() -> None:
    inventory = inventory_repository(ROOT, load_manifest(MANIFEST_PATH))
    ledger = load_query_migration_manifest(QUERY_MANIFEST_PATH)
    skeleton = query_migration_skeleton(inventory, ROOT)

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
    target_domains = {"node_task_edge_binding", "lease"}
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
    assert Counter(site.domain for site in ledger.unclassified_sites) == {
        "cleanup_callback": 14,
        "governance_requirements": 11,
        "planning_session": 16,
        "record_file_state": 11,
        "test_fixture": 198,
        "verification_recovery": 150,
    }
    assert validate_query_migration_manifest(ledger, inventory, ROOT, domain="lifecycle") == {
        "lifecycle": len(lifecycle_keys)
    }


def test_manifest_load_canonicalizes_yaml_key_chunks_and_rejects_key_aliases(
    tmp_path: Path,
) -> None:
    key = "a" * 64
    payload = {
        "baseline_revision": "baseline",
        "dispositions": [
            {
                "site_key": ["a" * 8] * 8,
                "disposition": "query_transform",
                "relative_path": "src/example.py",
                "qualified_function": "read",
                "normalized_source_pattern": "projection['run_state']",
                "diagnostic_code": None,
                "reason": "Use a lifecycle query.",
            }
        ],
        "unclassified_sites": [
            {
                "site_key": key,
                "relative_path": "src/example.py",
                "qualified_function": "read",
                "normalized_source_pattern": "projection['node_states']",
                "diagnostic_code": None,
                "domain": "node_task_edge_binding",
            }
        ],
    }
    path = tmp_path / "ledger.yaml"
    path.write_text(yaml.safe_dump(payload))

    with pytest.raises(ValidationError, match="duplicate migration disposition site key"):
        load_query_migration_manifest(path)
    with pytest.raises(ValidationError):
        MigrationDisposition.model_validate(payload["dispositions"][0])


def test_manifest_load_rejects_malformed_canonical_key_chunks(tmp_path: Path) -> None:
    path = tmp_path / "ledger.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "baseline_revision": "baseline",
                "dispositions": [],
                "unclassified_sites": [
                    {
                        "site_key": ["a" * 8] * 7,
                        "relative_path": "src/example.py",
                        "qualified_function": "read",
                        "normalized_source_pattern": "projection['run_state']",
                        "diagnostic_code": None,
                        "domain": "lifecycle",
                    }
                ],
            }
        )
    )

    with pytest.raises(ValueError, match="eight lowercase hex groups"):
        load_query_migration_manifest(path)


@pytest.mark.parametrize(
    "field_name",
    ("relative_path", "qualified_function", "normalized_source_pattern", "reason"),
)
def test_disposition_rejects_blank_required_text(field_name: str) -> None:
    values = {
        "site_key": "a" * 64,
        "disposition": "query_transform",
        "relative_path": "src/example.py",
        "qualified_function": "read",
        "normalized_source_pattern": "projection['run_state']",
        "diagnostic_code": None,
        "reason": "Use a lifecycle query.",
    }
    values[field_name] = " \t"

    with pytest.raises(ValidationError, match="must not be blank"):
        MigrationDisposition.model_validate(values)


def test_manifest_rejects_blank_baseline_and_unclassified_domain() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        QueryMigrationManifest(baseline_revision=" ", dispositions=())
    with pytest.raises(ValidationError, match="must not be blank"):
        UnclassifiedMigrationSite(
            site_key="a" * 64,
            relative_path="src/example.py",
            qualified_function="read",
            normalized_source_pattern="projection['run_state']",
            domain="\n",
        )


def _event(event_id: str, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id="run-1",
        position={"active": 0, "decision": 1, "completed": 2}[event_id],
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def _lifecycle(to_state: str) -> dict[str, object]:
    return {
        "command_type": "run_lifecycle",
        "from_state": "queued" if to_state == "active" else "active",
        "to_state": to_state,
        "trigger": "test",
    }
