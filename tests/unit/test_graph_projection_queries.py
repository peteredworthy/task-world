"""Public query-boundary and migration-disposition behavior."""

from pathlib import Path

import pytest

from orchestrator.graph import completion_decision_passed, initial_projection, run_state
from scripts.graph_projection_inventory import (
    AccessInventory,
    AccessKind,
    AccessOccurrence,
    IncompleteMigrationDispositionError,
    QueryMigrationManifest,
    classify_lifecycle_domain,
    disposition_site_key,
    query_migration_skeleton,
    validate_query_migration_manifest,
)


def test_lifecycle_queries_preserve_missing_and_default_values() -> None:
    projection = initial_projection()

    assert run_state(projection) is None
    assert completion_decision_passed(projection) is False


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
                occurrence_id="lifecycle-site",
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
                occurrence_id="lifecycle-site",
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
                occurrence_id="node-site",
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
