from pathlib import Path

import pytest

from scripts.codemods.migrate_graph_projection_queries import (
    AnchorRefusedError,
    DispositionPlan,
    PlannedOperation,
    SourceSnapshot,
    compile_operation_stream,
    plan_reviewed_dispositions,
    shape_summary,
)
from scripts.graph_projection_inventory import (
    DiagnosticCode,
    MigrationDisposition,
    SourceDigest,
    inventory_paths,
    inventory_repository,
    inventory_sources,
    load_manifest,
    load_query_migration_manifest,
    query_migration_skeleton,
    source_digest,
)


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_manifest.yaml"


def test_inventory_sources_matches_filesystem_adapter_for_equivalent_snapshot(
    tmp_path: Path,
) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n'
        ),
    )

    path = tmp_path / source.relative_path
    path.parent.mkdir()
    path.write_text(source.source)

    inventory = inventory_sources((source,), manifest)
    filesystem_inventory = inventory_paths((path,), manifest, root=tmp_path)

    assert inventory == filesystem_inventory


def test_compile_operation_stream_adapts_occurrences_and_diagnostics_once() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n'
            "\n"
            "def again(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n'
        ),
    )
    inventory = inventory_sources((source,), manifest)
    skeleton = query_migration_skeleton(inventory, ROOT)

    stream = compile_operation_stream((source,), inventory, skeleton)

    assert len(stream.sites) == len(inventory.occurrences) + len(inventory.diagnostics)
    assert {site.original_site_id for site in stream.sites} == {
        *[item.occurrence_id for item in inventory.occurrences],
        *[
            item.site_key
            for item in skeleton.unclassified_sites
            if item.diagnostic_code is not None
        ],
    }
    assert {site.parent_shape for site in stream.sites} == {"return"}
    assert {site.operation_shape for site in stream.sites} == {"subscript_read"}


def test_compile_operation_stream_reanchors_after_blank_line_movement() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    original = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n'
        ),
    )
    inventory = inventory_sources((original,), manifest)
    skeleton = query_migration_skeleton(inventory, ROOT)
    moved = original.model_copy(update={"source": "\n" + original.source})

    stream = compile_operation_stream((moved,), inventory, skeleton)

    assert stream.sites[0].original_site_id == inventory.occurrences[0].occurrence_id
    assert stream.sites[0].locator.line == inventory.occurrences[0].line + 1


def test_compile_operation_stream_refuses_stale_digest_and_duplicate_anchor() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    original = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n'
        ),
    )
    inventory = inventory_sources((original,), manifest)
    skeleton = query_migration_skeleton(inventory, ROOT)
    changed = original.model_copy(
        update={"source": original.source.replace("run_state", "node_states")}
    )
    duplicate = original.model_copy(
        update={
            "source": "\n"
            + original.source.replace(
                '    return projection["run_state"]',
                '    return projection["run_state"]\n    return projection["run_state"]',
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match="digest"):
        compile_operation_stream((changed,), inventory, skeleton)
    duplicate_inventory = inventory.model_copy(
        update={
            "source_digests": (
                SourceDigest(
                    relative_path=duplicate.relative_path,
                    digest=source_digest(duplicate.source),
                ),
            )
        }
    )
    with pytest.raises(AnchorRefusedError, match="ambiguous"):
        compile_operation_stream((duplicate,), duplicate_inventory, skeleton)


def test_compile_operation_stream_anchors_diagnostics_from_snapshots_without_repository_source() -> (
    None
):
    manifest = load_manifest(MANIFEST_PATH)
    original = SourceSnapshot(
        relative_path="src/not-present-on-disk.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def compare(projection: GraphProjection) -> bool:\n"
            '    return projection["run_state"] == "active"\n'
        ),
    )
    inventory = inventory_sources((original,), manifest)
    skeleton = query_migration_skeleton(inventory)
    moved = original.model_copy(update={"source": "\n" + original.source})

    stream = compile_operation_stream((moved,), inventory, skeleton)

    diagnostic = next(site for site in stream.sites if site.origin == "diagnostic")
    assert diagnostic.original_site_id in {
        site.site_key for site in skeleton.unclassified_sites if site.diagnostic_code is not None
    }
    assert diagnostic.locator.line == inventory.diagnostics[0].line + 1
    assert diagnostic.normalized_expression == 'return projection["run_state"] == "active"'
    assert diagnostic.anchor.normalized_expression == "projection['run_state'] == 'active'"


def test_compile_operation_stream_refuses_ambiguous_diagnostic_snapshot_anchor() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    original = SourceSnapshot(
        relative_path="src/not-present-on-disk.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def compare(projection: GraphProjection) -> bool:\n"
            '    return projection["run_state"] == "active"\n'
        ),
    )
    inventory = inventory_sources((original,), manifest)
    skeleton = query_migration_skeleton(inventory)
    ambiguous = original.model_copy(
        update={
            "source": original.source.replace(
                '    return projection["run_state"] == "active"',
                '    return projection["run_state"] == "active"\n'
                '    return projection["run_state"] == "active"',
            )
        }
    )
    altered_inventory = inventory.model_copy(
        update={
            "source_digests": (
                SourceDigest(
                    relative_path=ambiguous.relative_path,
                    digest=source_digest(ambiguous.source),
                ),
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match="ambiguous"):
        compile_operation_stream((ambiguous,), altered_inventory, skeleton)


def test_shape_summary_groups_only_structural_shape_key_fields() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def first(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n\n'
            "def second(projection: GraphProjection) -> str:\n"
            '    return projection["run_state"]\n'
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream(
        (source,), inventory, query_migration_skeleton(inventory, ROOT)
    )

    assert shape_summary(stream) == {"literal_subscript_read|run_state|-|return|subscript_read": 2}


def test_operation_shapes_distinguish_direct_map_and_nested_gets() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            '    first = projection.get("run_state")\n'
            '    second = projection["node_states"].get("node")\n'
            "    return first, second\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))

    assert {site.operation_shape for site in stream.sites} >= {"map_get", "nested_get"}


def test_direct_deletion_has_deletion_parent_and_operation_shapes() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def remove(projection: GraphProjection) -> None:\n"
            '    del projection["run_state"]\n'
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))

    assert [(site.parent_shape, site.operation_shape) for site in stream.sites] == [
        ("deletion", "deletion")
    ]


def test_disposition_plan_refuses_overlapping_or_missing_reviewed_sites() -> None:
    with pytest.raises(ValueError, match="nonempty"):
        PlannedOperation(disposition="query_transform", reason="reviewed", consumed_site_ids=())
    with pytest.raises(ValueError, match="overlap"):
        DispositionPlan(
            operations=(
                PlannedOperation(
                    disposition="query_transform",
                    reason="reviewed",
                    consumed_site_ids=("a",),
                    shape_key="shape",
                ),
                PlannedOperation(
                    disposition="query_transform",
                    reason="reviewed",
                    consumed_site_ids=("a",),
                    shape_key="shape",
                ),
            ),
            deferred_site_ids=(),
            pending_site_ids=(),
            disposition_counts=(("query_transform", 2),),
            shape_group_counts=(("shape", 2),),
        )


def test_disposition_plan_direct_validation_refuses_partition_and_count_forgeries() -> None:
    operation = PlannedOperation(
        disposition="query_transform",
        reason="reviewed",
        consumed_site_ids=("a",),
        shape_key="shape",
    )
    valid = {
        "operations": (operation,),
        "deferred_site_ids": ("b",),
        "pending_site_ids": ("c",),
        "disposition_counts": (("query_transform", 1),),
        "shape_group_counts": (("shape", 1),),
    }
    for update, message in (
        ({"deferred_site_ids": ("b", "b")}, "unique"),
        ({"pending_site_ids": ("c", "c")}, "unique"),
        ({"deferred_site_ids": ("a",)}, "overlap"),
        ({"pending_site_ids": ("a",)}, "overlap"),
        ({"pending_site_ids": ("b",)}, "overlap"),
        ({"disposition_counts": (("approved_core", 1),)}, "disposition counts"),
        ({"shape_group_counts": (("other", 1),)}, "shape counts"),
    ):
        with pytest.raises(ValueError, match=message):
            DispositionPlan(**(valid | update))


@pytest.mark.timeout(300)
def test_live_reviewed_ledger_compiles_once_and_defers_only_fixture_sites() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    inventory = inventory_repository(ROOT, manifest)
    tracked_sources = tuple(
        SourceSnapshot(relative_path=path.relative_to(ROOT).as_posix(), source=path.read_text())
        for directory in (ROOT / "src", ROOT / "tests", ROOT / "scripts")
        for path in sorted(directory.rglob("*.py"))
        if "__pycache__" not in path.parts
    )
    ledger = load_query_migration_manifest(
        ROOT / "scripts/codemods/graph_projection_query_migration.yaml"
    )

    stream = compile_operation_stream(
        tracked_sources, inventory, query_migration_skeleton(inventory, ROOT)
    )
    plan = plan_reviewed_dispositions(stream, ledger)

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
            ledger.model_copy(update={"dispositions": tuple(reversed(ledger.dispositions))}),
        )
        == plan
    )


def test_plan_refuses_duplicate_or_stale_anchored_reviewed_identity() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            "    return projection['run_state']\n"
        ),
    )
    manifest = load_manifest(MANIFEST_PATH)
    inventory = inventory_sources((source,), manifest)
    skeleton = query_migration_skeleton(inventory, ROOT)
    stream = compile_operation_stream((source,), inventory, skeleton)
    site = stream.sites[0]
    disposition = MigrationDisposition(
        site_key=site.original_site_id,
        disposition="query_transform",
        relative_path=site.relative_path,
        qualified_function=site.qualified_function,
        normalized_source_pattern=site.normalized_expression,
        reason="reviewed test disposition",
    )
    ledger = load_query_migration_manifest(
        ROOT / "scripts/codemods/graph_projection_query_migration.yaml"
    ).model_copy(update={"dispositions": (disposition,)})

    with pytest.raises(AnchorRefusedError, match="duplicate"):
        plan_reviewed_dispositions(
            stream.model_copy(update={"sites": (stream.sites[0], stream.sites[0])}), ledger
        )
    stale = disposition.model_copy(update={"site_key": "0" * 64})
    with pytest.raises(AnchorRefusedError, match="no anchored"):
        plan_reviewed_dispositions(stream, ledger.model_copy(update={"dispositions": (stale,)}))


@pytest.mark.timeout(120)
def test_live_repository_compilation_includes_every_remaining_fixture_site() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    inventory = inventory_repository(ROOT, manifest)
    tracked_sources = tuple(
        SourceSnapshot(relative_path=path.relative_to(ROOT).as_posix(), source=path.read_text())
        for directory in (ROOT / "src", ROOT / "tests", ROOT / "scripts")
        for path in sorted(directory.rglob("*.py"))
        if "__pycache__" not in path.parts
    )
    skeleton = query_migration_skeleton(inventory, ROOT)
    ledger = load_query_migration_manifest(
        ROOT / "scripts/codemods/graph_projection_query_migration.yaml"
    )

    stream = compile_operation_stream(tracked_sources, inventory, skeleton)

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
