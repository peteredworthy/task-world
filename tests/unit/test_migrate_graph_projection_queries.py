from pathlib import Path

import pytest

from scripts.codemods.migrate_graph_projection_queries import (
    AnchorRefusedError,
    SourceSnapshot,
    compile_operation_stream,
    shape_summary,
)
from scripts.graph_projection_inventory import (
    DiagnosticCode,
    SourceDigest,
    inventory_paths,
    inventory_repository,
    inventory_sources,
    load_manifest,
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

    stream = compile_operation_stream(tracked_sources, inventory, skeleton)

    assert len(stream.sites) == len(inventory.occurrences) + len(inventory.diagnostics)
    fixture_site_ids = {
        site.site_key for site in skeleton.unclassified_sites if site.domain == "test_fixture"
    }
    compiled_site_ids = [site.original_site_id for site in stream.sites]
    assert fixture_site_ids
    assert {
        site_id for site_id in compiled_site_ids if site_id in fixture_site_ids
    } == fixture_site_ids
    assert all(compiled_site_ids.count(site_id) == 1 for site_id in fixture_site_ids)
    assert all(
        site.diagnostic_code is None or site.diagnostic_code in DiagnosticCode
        for site in stream.sites
    )
