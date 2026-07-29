from collections import Counter
import json
from pathlib import Path
import subprocess

import pytest

from scripts.codemods.migrate_graph_projection_queries import (
    AnchorRefusedError,
    CstAnchorEvidence,
    DispositionPlan,
    FixtureMutationPlan,
    QueryMigrationReport,
    MigrationSite,
    OperationStream,
    PlannedOperation,
    QueryCompositionGroup,
    QueryCompositionPlan,
    QueryMutationHandoff,
    QueryReplacementPlan,
    QueryReplacementRecipe,
    QuerySourceApplyPlan,
    SourceSnapshot,
    SourceLocator,
    compile_operation_stream,
    compile_fixture_mutation_plan,
    compile_query_migration_report,
    compile_query_composition_plan,
    compile_query_replacement_plan,
    apply_query_replacement_plan,
    apply_fixture_mutation_plan,
    plan_reviewed_dispositions,
    require_complete_receiver_physical_context,
    shape_summary,
    load_git_python_sources,
    main as migration_main,
    query_migration_report_json,
    run_query_migration_mode,
    write_query_source_apply_plan,
    write_fixture_source_apply_plan,
    write_query_migration_report,
    _generated_fixture_rule,
    _generated_query_rule,
    _neutral_rule,
)
from scripts.graph_projection_inventory import (
    AccessKind,
    DiagnosticCode,
    MigrationDisposition,
    SourceDigest,
    ProjectionCallContext,
    inventory_paths,
    inventory_sources,
    load_manifest,
    load_query_migration_manifest,
    query_migration_skeleton,
    source_digest,
)


ROOT = Path(__file__).parents[2]
MANIFEST_PATH = ROOT / "scripts/codemods/graph_projection_manifest.yaml"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args),
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _historical_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    source = repo / "tests" / "fixture.py"
    source.parent.mkdir()
    source.write_text(
        "from orchestrator.graph import GraphProjection\n\n"
        "def read(projection: GraphProjection) -> object:\n"
        "    return projection['run_state']\n"
    )
    (repo / "README.md").write_text("ignored\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "baseline")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_load_git_python_sources_reads_only_tracked_baseline_python(tmp_path: Path) -> None:
    repo, revision = _historical_repo(tmp_path)
    (repo / "tests" / "fixture.py").write_text("changed\n")
    (repo / "tests" / "untracked.py").write_text("untracked\n")

    sources = load_git_python_sources(repo, revision)

    assert tuple(source.relative_path for source in sources) == ("tests/fixture.py",)
    assert "projection['run_state']" in sources[0].source


def test_query_migration_report_links_every_baseline_site_deterministically() -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )
    manifest = load_manifest(MANIFEST_PATH)

    report = compile_query_migration_report((source,), manifest)
    encoded = query_migration_report_json(report)

    assert isinstance(report, QueryMigrationReport)
    assert len(report.sites) == report.baseline_site_count
    assert {site.disposition for site in report.sites} == {"transformed"}
    transformed = next(site for site in report.sites if site.disposition == "transformed")
    assert transformed.before_normalized_form == "projection['run_state']"
    assert transformed.replacement == "run_state(projection)"
    assert transformed.after_form == transformed.replacement
    assert encoded == query_migration_report_json(report)
    assert encoded.endswith(b"\n")
    assert json.loads(encoded)["baseline_site_count"] == len(report.sites)


def test_query_migration_report_links_nested_physical_diagnostic_to_outer_recipe() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "from orchestrator.graph.scheduler import NodeScheduleInfo\n\n"
            "def read(projection: GraphProjection, node_id: str) -> object:\n"
            "    return NodeScheduleInfo(kind=projection['node_kinds'].get(node_id, 'worker'))\n"
        ),
    )

    report = compile_query_migration_report((source,), load_manifest(MANIFEST_PATH))

    transformed = [site for site in report.sites if site.disposition == "transformed"]
    assert len(transformed) == 2
    assert {site.replacement for site in transformed} == {
        "NodeScheduleInfo(kind=node_kinds_view(projection).get(node_id, 'worker'))"
    }
    assert {site.rule_id for site in transformed} == {
        "physical_literal_subscript_read",
        "physical_wrapper:mapping_snapshot",
    }


def test_query_migration_report_transforms_physical_mapping_update_diagnostic() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> dict[str, str]:\n"
            "    snapshot: dict[str, str] = {}\n"
            "    snapshot.update(projection['node_states'])\n"
            "    return snapshot\n"
        ),
    )

    report = compile_query_migration_report((source,), load_manifest(MANIFEST_PATH))

    transformed = [site for site in report.sites if site.disposition == "transformed"]
    assert len(transformed) == 1
    assert transformed[0].replacement == "snapshot.update(node_states_view(projection))"
    assert transformed[0].rule_id == "physical_literal_subscript_read"


def test_query_migration_modes_check_apply_and_assert_clean_use_atomic_report(
    tmp_path: Path,
) -> None:
    repo, revision = _historical_repo(tmp_path)
    current = repo / "tests" / "fixture.py"
    current.write_text(
        "from orchestrator.graph import GraphProjection, run_state\n\n"
        "def read(projection: GraphProjection) -> object:\n"
        "    return run_state(projection)\n"
    )
    manifest = load_manifest(MANIFEST_PATH).model_copy(update={"baseline_revision": revision})
    report_path = repo / "tests" / "fixtures" / "query_migration_report.json"

    checked = run_query_migration_mode(repo, manifest, "check", report_path=report_path)
    assert isinstance(checked, QueryMigrationReport)
    assert not report_path.exists()

    applied = run_query_migration_mode(repo, manifest, "apply", report_path=report_path)
    assert report_path.read_bytes() == query_migration_report_json(applied)
    assert (
        run_query_migration_mode(repo, manifest, "assert-clean", report_path=report_path)
        == applied.current_closure
    )

    report_path.write_text("{}\n")
    with pytest.raises(AnchorRefusedError, match="report"):
        run_query_migration_mode(repo, manifest, "assert-clean", report_path=report_path)


def test_write_query_migration_report_refuses_stale_expected_bytes(tmp_path: Path) -> None:
    report = compile_query_migration_report(
        (
            SourceSnapshot(
                relative_path="tests/fixture.py",
                source=(
                    "from orchestrator.graph import GraphProjection\n\n"
                    "def read(projection: GraphProjection) -> object:\n"
                    "    return projection['run_state']\n"
                ),
            ),
        ),
        load_manifest(MANIFEST_PATH),
    )
    target = tmp_path / "report.json"
    target.write_text("stale\n")

    with pytest.raises(AnchorRefusedError, match="changed before atomic apply"):
        write_query_migration_report(target, report, expected_bytes=b"other\n")

    assert target.read_text() == "stale\n"


def test_query_migration_report_refuses_unknown_fixture_key_shape() -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def seed(projection: GraphProjection) -> None:\n"
            "    projection['node_states'][0] = 'ready'\n"
        ),
    )

    with pytest.raises(AnchorRefusedError, match="string literal"):
        compile_query_migration_report((source,), load_manifest(MANIFEST_PATH))


def test_query_migration_report_classifies_structural_projection_cast() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from typing import Any, cast\n"
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    projection_data = cast(dict[str, Any], projection)\n"
            "    return projection_data\n"
        ),
    )

    report = compile_query_migration_report((source,), load_manifest(MANIFEST_PATH))

    assert {site.rule_id for site in report.sites} == {"projection_cast"}
    assert {site.disposition for site in report.sites} == {"projection_neutral"}


def test_query_migration_cli_requires_exactly_one_mode() -> None:
    with pytest.raises(SystemExit):
        migration_main(())
    with pytest.raises(SystemExit):
        migration_main(("--check", "--apply"))


def _compile_occurrence_composition(
    source: SourceSnapshot,
) -> tuple[QueryCompositionPlan, OperationStream, DispositionPlan]:
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    stream = compile_operation_stream(
        (source,), inventory, query_migration_skeleton(inventory, ROOT)
    )
    selected = tuple(site for site in stream.sites if site.origin == "occurrence")
    operations = tuple(
        PlannedOperation(
            disposition="query_transform",
            reason="synthetic composition contract",
            consumed_site_ids=(site.original_site_id,),
            shape_key=site.shape_key,
        )
        for site in sorted(selected, key=lambda item: item.original_site_id)
    )
    disposition = DispositionPlan(
        operations=operations,
        reviewed_deferred_site_ids=(),
        generated_fixture_operations=(),
        pending_site_ids=(),
        disposition_counts=(("query_transform", len(operations)),),
        shape_group_counts=tuple(sorted(Counter(item.shape_key for item in operations).items())),
        rule_family_counts=(),
        symbol_origin_counts=(),
        generated_fixture_family_counts=(),
    )
    return compile_query_composition_plan((source,), stream, disposition), stream, disposition


def _compile_physical_replacements(
    source: SourceSnapshot,
) -> QueryReplacementPlan:
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    stream = compile_operation_stream(
        (source,), inventory, query_migration_skeleton(inventory, ROOT)
    )
    selected = tuple(
        site
        for site in stream.sites
        if site.origin == "occurrence"
        and site.anchor.context is not None
        and site.anchor.context.physical_access_kind is not None
    )
    operations = tuple(
        PlannedOperation(
            disposition="query_transform",
            reason="synthetic replacement contract",
            consumed_site_ids=(site.original_site_id,),
            shape_key=site.shape_key,
        )
        for site in sorted(selected, key=lambda item: item.original_site_id)
    )
    disposition = DispositionPlan(
        operations=operations,
        reviewed_deferred_site_ids=(),
        generated_fixture_operations=(),
        pending_site_ids=(),
        disposition_counts=(("query_transform", len(operations)),),
        shape_group_counts=tuple(sorted(Counter(item.shape_key for item in operations).items())),
        rule_family_counts=(),
        symbol_origin_counts=(),
        generated_fixture_family_counts=(),
    )
    composition = compile_query_composition_plan((source,), stream, disposition)
    return compile_query_replacement_plan((source,), stream, disposition, composition)


def _merge_replacement_plans(*plans: QueryReplacementPlan) -> QueryReplacementPlan:
    recipes = tuple(
        sorted(
            (recipe for plan in plans for recipe in plan.recipes),
            key=lambda item: (item.relative_path, item.source_span, item.consumed_site_ids),
        )
    )
    handoffs = tuple(
        sorted(
            (handoff for plan in plans for handoff in plan.mutation_handoffs),
            key=lambda item: (item.relative_path, item.source_span, item.consumed_site_ids),
        )
    )
    return QueryReplacementPlan(
        recipes=recipes,
        mutation_handoffs=handoffs,
        unmatched_family_counts=(),
        rule_family_counts=tuple(
            sorted(Counter(rule for recipe in recipes for rule in recipe.rule_ids).items())
        ),
        query_import_counts=tuple(
            sorted(Counter(name for recipe in recipes for name in recipe.query_imports).items())
        ),
    )


def _compile_fixture_mutations(source: SourceSnapshot) -> FixtureMutationPlan:
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    stream = compile_operation_stream(
        (source,), inventory, query_migration_skeleton(inventory, ROOT)
    )
    operations = tuple(
        operation
        for site in stream.sites
        if (operation := _generated_fixture_rule(site)) is not None
    )
    return compile_fixture_mutation_plan((source,), stream, operations)


def test_fixture_mutation_plan_compiles_four_helpers_and_literal_extend() -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def seed(projection: GraphProjection, node_id: str) -> GraphProjection:\n"
            "    projection['run_state'] = 'active'\n"
            "    projection['node_states'][node_id] = 'ready'\n"
            "    projection['node_roles'].update({'node-1': 'builder'})\n"
            "    projection['ready_nodes'].append(node_id)\n"
            "    projection['ready_nodes'].extend(('node-2', 'node-3'))\n"
            "    return projection\n"
        ),
    )

    plan = _compile_fixture_mutations(source)
    applied = apply_fixture_mutation_plan((source,), plan)
    transformed = applied.updates[0].transformed_source

    assert len(plan.recipes) == 5
    assert "from tests.unit.graph_test_utils import " in transformed
    assert "projection_fixture_replace" in transformed
    assert "projection_fixture_set" in transformed
    assert "projection_fixture_update" in transformed
    assert "projection_fixture_append" in transformed
    assert (
        "projection = projection_fixture_replace(projection, 'run_state', 'active')" in transformed
    )
    assert (
        "projection = projection_fixture_set(projection, 'node_states', (node_id,), 'ready')"
        in transformed
    )
    assert "projection = projection_fixture_update(" in transformed
    assert transformed.count("projection_fixture_append(") == 3
    assert applied.consumed_site_ids == plan.consumed_site_ids


@pytest.mark.parametrize(
    "statement",
    [
        "context.graph_projection['run_state'] = 'active'",
        "projection['node_states'][0] = 'active'",
        "projection['node_states'].update(values, extra=True)",
        "projection['ready_nodes'].extend(values)",
    ],
)
def test_fixture_mutation_plan_fails_closed_for_unproved_shapes(statement: str) -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphDispatchContext, GraphProjection\n\n"
            "def seed(projection: GraphProjection, context: GraphDispatchContext, "
            "values: object) -> None:\n"
            f"    {statement}\n"
        ),
    )
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    stream = compile_operation_stream(
        (source,), inventory, query_migration_skeleton(inventory, ROOT)
    )
    operations = tuple(
        operation
        for site in stream.sites
        if (operation := _generated_fixture_rule(site)) is not None
    )

    with pytest.raises(AnchorRefusedError):
        compile_fixture_mutation_plan((source,), stream, operations)


def test_fixture_mutation_apply_aliases_collision_and_requires_fresh_idempotent_plan() -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def seed(projection: GraphProjection) -> GraphProjection:\n"
            "    projection_fixture_replace = None\n"
            "    projection['run_state'] = 'active'\n"
            "    return projection\n"
        ),
    )
    plan = _compile_fixture_mutations(source)

    first = apply_fixture_mutation_plan((source,), plan)
    transformed = SourceSnapshot(
        relative_path=source.relative_path, source=first.updates[0].transformed_source
    )
    with pytest.raises(AnchorRefusedError, match="exact statement"):
        apply_fixture_mutation_plan((transformed,), plan)
    fresh_plan = _compile_fixture_mutations(transformed)
    second = apply_fixture_mutation_plan((transformed,), fresh_plan)

    assert "projection_fixture_replace as fixture_projection_fixture_replace" in transformed.source
    assert "projection = fixture_projection_fixture_replace(" in transformed.source
    assert fresh_plan.recipes == ()
    assert second.updates == ()


def test_fixture_mutation_atomic_write_validates_every_original_before_writing(
    tmp_path: Path,
) -> None:
    first = SourceSnapshot(
        relative_path="tests/first.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def seed(projection: GraphProjection) -> None:\n"
            "    projection['run_state'] = 'active'\n"
        ),
    )
    second = first.model_copy(update={"relative_path": "tests/second.py"})
    first_plan = _compile_fixture_mutations(first)
    second_plan = _compile_fixture_mutations(second)
    plan = FixtureMutationPlan(
        recipes=tuple(
            sorted(
                (*first_plan.recipes, *second_plan.recipes),
                key=lambda item: (item.relative_path, item.source_span),
            )
        )
    )
    applied = apply_fixture_mutation_plan((first, second), plan)
    for source in (first, second):
        path = tmp_path / source.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.source)
    second_path = tmp_path / second.relative_path
    second_path.write_text("stale\n")

    with pytest.raises(AnchorRefusedError, match="changed before atomic apply"):
        write_fixture_source_apply_plan(tmp_path, applied)

    assert (tmp_path / first.relative_path).read_text() == first.source


def test_fixture_reads_and_mutations_use_structural_rules() -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def use(projection: GraphProjection) -> object:\n"
            "    value = projection['run_state']\n"
            "    projection['node_states']['node'] = 'active'\n"
            "    return value\n"
        ),
    )
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    skeleton = query_migration_skeleton(inventory)
    stream = compile_operation_stream((source,), inventory, skeleton)
    read = next(site for site in stream.sites if site.old_field_name == "run_state")
    mutation = next(site for site in stream.sites if site.old_field_name == "node_states")

    assert _generated_query_rule(read) is not None
    assert _generated_fixture_rule(mutation) is not None


def test_fixture_mutation_helper_rebinding_is_a_finite_neutral_flow() -> None:
    expression = "projection = projection_fixture_replace(projection, 'run_state', 'active')"
    helper_site = MigrationSite(
        origin="diagnostic",
        original_site_id="helper-site",
        relative_path="tests/fixture.py",
        qualified_function="seed",
        access_kind=None,
        old_field_name=None,
        diagnostic_code=DiagnosticCode.UNSUPPORTED_BINDING,
        normalized_expression=expression,
        domain="test_fixture",
        ordinal=0,
        source_digest="0" * 64,
        locator=SourceLocator(line=1, column=0),
        anchor=CstAnchorEvidence(
            node_type="Assign",
            normalized_expression=expression,
            same_expression_ordinal=0,
        ),
        parent_shape="bare_expression",
        operation_shape="typed_pass_through",
    )

    assert _neutral_rule(helper_site) == (
        "fixture_mutation_helper",
        "tests.unit.graph_test_utils.projection_fixture_replace",
    )


def test_structural_plan_rejects_nonfixture_mutation_as_fixture_handoff() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def use(projection: GraphProjection) -> None:\n"
            "    projection['run_state'] = 'active'\n"
        ),
    )
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    skeleton = query_migration_skeleton(inventory)
    stream = compile_operation_stream((source,), inventory, skeleton)
    assert _generated_fixture_rule(stream.sites[0]) is None


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


def test_complete_receiver_physical_context_refuses_a_stripped_transform_occurrence() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            "    return projection['run_state']\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))
    occurrence = stream.sites[0]

    require_complete_receiver_physical_context(occurrence)

    stripped = occurrence.model_copy(
        update={"anchor": occurrence.anchor.model_copy(update={"context": None})}
    )
    with pytest.raises(AnchorRefusedError, match="complete receiver physical context"):
        require_complete_receiver_physical_context(stripped)


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


def test_compile_operation_stream_excludes_comparison_children_from_occurrence_matches() -> None:
    source = SourceSnapshot(
        relative_path="src/not-present-on-disk.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    if projection['run_state'] is not None:\n"
            "        return projection['run_state']\n"
            "    return None\n"
        ),
    )
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))

    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))

    assert len([site for site in stream.sites if site.origin == "occurrence"]) == 1


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


def test_compile_operation_stream_reanchors_direct_call_deletion_and_fieldless_physical_sites() -> (
    None
):
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/physical.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def access(projection: GraphProjection) -> None:\n"
            "    projection['run_state']\n"
            "    projection.get('node_states')\n"
            "    projection.keys()\n"
            "    projection.values()\n"
            "    projection.items()\n"
            "    del projection['run_state']\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)

    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))

    assert [site.operation_shape for site in stream.sites] == [
        "subscript_read",
        "map_get",
        "keys_iteration",
        "values_iteration",
        "items_iteration",
        "deletion",
    ]


@pytest.mark.parametrize(
    ("context_update", "message"),
    [
        ({"projection_expression": "other"}, "projection expression"),
        ({"physical_old_field_name": "node_states"}, "physical context"),
        (
            {
                "physical_access_kind": "get",
                "physical_operation_shape": "get",
            },
            "access kind",
        ),
        ({"physical_operation_shape": "get"}, "operation shape"),
    ],
)
def test_compile_operation_stream_refuses_exact_physical_evidence_mismatches(
    context_update: dict[str, object], message: str
) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/physical.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def access(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    occurrence = inventory.occurrences[0]
    invalid = inventory.model_copy(
        update={
            "occurrences": (
                occurrence.model_copy(
                    update={"context": occurrence.context.model_copy(update=context_update)}
                ),
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match=message):
        compile_operation_stream((source,), invalid, query_migration_skeleton(invalid))


def test_compile_operation_stream_refuses_nested_unrelated_diagnostic_field_evidence() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/nested.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def access(projection: GraphProjection) -> None:\n"
            "    projection['run_state']['unrelated'].update({})\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    diagnostic = next(item for item in inventory.diagnostics if item.context is not None)
    assert diagnostic.context.physical_old_field_name == "run_state"
    assert compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))
    invalid = inventory.model_copy(
        update={
            "diagnostics": (
                diagnostic.model_copy(
                    update={
                        "context": diagnostic.context.model_copy(
                            update={"physical_old_field_name": "unrelated"}
                        )
                    }
                ),
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match="physical context"):
        compile_operation_stream((source,), invalid, query_migration_skeleton(invalid))


@pytest.mark.parametrize(
    ("source_body", "context_update"),
    [
        ("run_state(*projection)", {"argument_star": "**"}),
        ("run_state(**projection)", {"argument_star": "*"}),
        (
            "run_state(*projection)",
            {"argument_star": None, "preceding_star": "*"},
        ),
        (
            "run_state(*values, projection)",
            {"argument_star": "*", "preceding_star": None},
        ),
        ("run_state(*projection)", {"projection_expression": "other"}),
    ],
)
def test_compile_operation_stream_refuses_mutated_ambiguous_star_evidence(
    source_body: str, context_update: dict[str, object]
) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/stars.py",
        source=(
            "from orchestrator.graph import GraphProjection, run_state\n\n"
            "def call(projection: GraphProjection, values: tuple[object, ...]) -> None:\n"
            f"    {source_body}\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    diagnostic = inventory.diagnostics[0]
    invalid = inventory.model_copy(
        update={
            "diagnostics": (
                diagnostic.model_copy(
                    update={"context": diagnostic.context.model_copy(update=context_update)}
                ),
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match="ambiguous context"):
        compile_operation_stream((source,), invalid, query_migration_skeleton(invalid))


@pytest.mark.parametrize(
    ("statement", "anchor_origin", "context_update", "message"),
    [
        (
            "projection.get('run_state')",
            "occurrence",
            {"projection_expression": "other"},
            "projection expression",
        ),
        (
            "projection.get('run_state')",
            "occurrence",
            {"physical_old_field_name": "node_states"},
            "physical context",
        ),
        (
            "projection.get('run_state')",
            "occurrence",
            {"physical_access_kind": "delete_pop", "physical_operation_shape": "delete_pop"},
            "access kind",
        ),
        (
            "projection.get('run_state')",
            "occurrence",
            {"physical_operation_shape": "keys"},
            "operation shape",
        ),
        (
            "projection.keys()",
            "occurrence",
            {"projection_expression": "other"},
            "projection expression",
        ),
        (
            "projection.keys()",
            "occurrence",
            {"physical_old_field_name": "run_state"},
            "physical context",
        ),
        (
            "projection.keys()",
            "occurrence",
            {"physical_access_kind": "get", "physical_operation_shape": "get"},
            "access kind",
        ),
        (
            "projection.keys()",
            "occurrence",
            {"physical_operation_shape": "values"},
            "operation shape",
        ),
        (
            "del projection['run_state']",
            "occurrence",
            {"projection_expression": "other"},
            "projection expression",
        ),
        (
            "del projection['run_state']",
            "occurrence",
            {"physical_old_field_name": "node_states"},
            "physical context",
        ),
        (
            "del projection['run_state']",
            "occurrence",
            {"physical_access_kind": "get", "physical_operation_shape": "get"},
            "access kind",
        ),
        (
            "del projection['run_state']",
            "occurrence",
            {"physical_operation_shape": "get"},
            "operation shape",
        ),
        (
            "projection['run_state'].update({})",
            "diagnostic",
            {"projection_expression": "other"},
            "projection expression",
        ),
        (
            "projection['run_state'].update({})",
            "diagnostic",
            {"physical_old_field_name": "node_states"},
            "physical context",
        ),
        (
            "projection['run_state'].update({})",
            "diagnostic",
            {"physical_access_kind": "get", "physical_operation_shape": "get"},
            "access kind",
        ),
        (
            "projection['run_state'].update({})",
            "diagnostic",
            {"physical_operation_shape": "get"},
            "operation shape",
        ),
    ],
)
def test_compile_operation_stream_refuses_mutated_physical_anchor_evidence(
    statement: str,
    anchor_origin: str,
    context_update: dict[str, object],
    message: str,
) -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/physical.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def access(projection: GraphProjection) -> None:\n"
            f"    {statement}\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    records = inventory.occurrences if anchor_origin == "occurrence" else inventory.diagnostics
    record = records[0]
    invalid = inventory.model_copy(
        update={
            f"{anchor_origin}s": (
                record.model_copy(
                    update={"context": record.context.model_copy(update=context_update)}
                ),
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match=message):
        compile_operation_stream((source,), invalid, query_migration_skeleton(invalid))


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
            reviewed_deferred_site_ids=(),
            generated_fixture_operations=(),
            pending_site_ids=(),
            disposition_counts=(("query_transform", 2),),
            shape_group_counts=(("shape", 2),),
            rule_family_counts=(),
            symbol_origin_counts=(),
            generated_fixture_family_counts=(),
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
        "reviewed_deferred_site_ids": ("b",),
        "generated_fixture_operations": (),
        "pending_site_ids": ("c",),
        "disposition_counts": (("query_transform", 1),),
        "shape_group_counts": (("shape", 1),),
        "rule_family_counts": (),
        "symbol_origin_counts": (),
        "generated_fixture_family_counts": (),
    }
    for update, message in (
        ({"reviewed_deferred_site_ids": ("b", "b")}, "unique"),
        ({"pending_site_ids": ("c", "c")}, "unique"),
        ({"reviewed_deferred_site_ids": ("a",)}, "overlap"),
        ({"pending_site_ids": ("a",)}, "overlap"),
        ({"pending_site_ids": ("b",)}, "overlap"),
        ({"disposition_counts": (("approved_core", 1),)}, "disposition counts"),
        ({"shape_group_counts": (("other", 1),)}, "shape counts"),
    ):
        with pytest.raises(ValueError, match=message):
            DispositionPlan(**(valid | update))


def test_disposition_plan_derives_generated_fixture_counts_from_frozen_operations() -> None:
    operation = PlannedOperation(
        disposition="query_transform",
        reason="reviewed",
        consumed_site_ids=("query",),
        shape_key="shape",
    )
    plan = DispositionPlan(
        operations=(operation,),
        reviewed_deferred_site_ids=("reviewed-fixture",),
        generated_fixture_operations=(
            {
                "site_id": "generated-fixture",
                "rule_id": "physical_nested_assignment",
                "shape_key": "nested",
                "evidence": (("access_kind", "nested_assignment"),),
            },
        ),
        pending_site_ids=(),
        disposition_counts=(("query_transform", 1),),
        shape_group_counts=(("shape", 1),),
        rule_family_counts=(),
        symbol_origin_counts=(),
        generated_fixture_family_counts=(("physical_nested_assignment", 1),),
    )

    assert plan.deferred_site_ids == ("generated-fixture", "reviewed-fixture")
    assert plan.fixture_site_ids == frozenset({"generated-fixture", "reviewed-fixture"})
    assert plan.generated_fixture_family_counts == (("physical_nested_assignment", 1),)
    with pytest.raises(ValueError, match="generated fixture family counts"):
        DispositionPlan(
            **(
                plan.model_dump()
                | {"generated_fixture_family_counts": (("physical_nested_assignment", 2),)}
            )
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


def test_anchor_evidence_copies_exact_collector_context_for_reanchored_calls() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection, initial_projection, run_state as state\n"
            "from foreign import run_state\n\n"
            "def good() -> None:\n"
            "    projection = initial_projection()\n"
            "    state(projection)\n\n"
            "def shadow(state: object, projection: GraphProjection) -> None:\n"
            "    state(projection)\n\n"
            "def wrong(projection: GraphProjection) -> None:\n"
            "    state('wrong', projection)\n\n"
            "def dynamic(projection: GraphProjection) -> None:\n"
            "    getattr(state, 'call')(projection)\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))
    calls = {
        site.qualified_function: site for site in stream.sites if site.anchor.node_type == "Call"
    }

    assert calls["good"].anchor.context.model_dump(exclude_none=True) == {
        "callee_origin": "orchestrator.graph.run_state",
        "projection_role": "positional",
        "positional_index": 0,
        "projection_expression": "projection",
    }
    assert calls["shadow"].anchor.context.model_dump(exclude_none=True) == {
        "projection_role": "positional",
        "positional_index": 0,
        "projection_expression": "projection",
    }
    assert calls["wrong"].anchor.context.model_dump(exclude_none=True) == {
        "callee_origin": "orchestrator.graph.run_state",
        "projection_role": "positional",
        "positional_index": 1,
        "projection_expression": "projection",
    }
    assert calls["dynamic"].anchor.context.model_dump(exclude_none=True) == {
        "projection_role": "positional",
        "positional_index": 0,
        "projection_expression": "projection",
    }


def test_anchor_evidence_copies_collector_context_for_positional_and_keyword_arguments() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection, initial_projection, run_state\n\n"
            "def positional() -> None:\n"
            "    projection = initial_projection()\n"
            "    run_state(projection)\n\n"
            "def keyword(projection: GraphProjection) -> None:\n"
            "    run_state(projection=projection)\n\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))
    calls = {
        site.qualified_function: site
        for site in stream.sites
        if site.anchor.node_type == "Call" and site.anchor.context is not None
    }

    assert calls["positional"].anchor.context.model_dump(exclude_none=True) == {
        "callee_origin": "orchestrator.graph.run_state",
        "projection_role": "positional",
        "positional_index": 0,
        "projection_expression": "projection",
    }
    assert calls["keyword"].anchor.context.model_dump(exclude_none=True) == {
        "callee_origin": "orchestrator.graph.run_state",
        "projection_role": "keyword",
        "keyword_name": "projection",
        "projection_expression": "projection",
    }


def test_compile_operation_stream_refuses_mismatched_inventory_context() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> str:\n"
            "    return projection['run_state']\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    occurrence = inventory.occurrences[0]
    invalid = inventory.model_copy(
        update={
            "occurrences": (
                occurrence.model_copy(
                    update={
                        "context": occurrence.context.model_copy(
                            update={"projection_role": "positional", "positional_index": 0}
                        )
                    }
                ),
            )
        }
    )

    with pytest.raises(AnchorRefusedError, match="context does not match"):
        compile_operation_stream((source,), invalid, query_migration_skeleton(invalid))


def test_compile_operation_stream_refuses_selected_expression_and_physical_context_mismatches() -> (
    None
):
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection, run_state\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    run_state(projection)\n"
            "    return projection['run_state']\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    diagnostic = next(item for item in inventory.diagnostics if item.context is not None)
    occurrence = inventory.occurrences[0]
    invalid = inventory.model_copy(
        update={
            "diagnostics": (
                diagnostic.model_copy(
                    update={
                        "context": diagnostic.context.model_copy(
                            update={"projection_expression": "other"}
                        )
                    }
                ),
            ),
            "occurrences": (
                occurrence.model_copy(
                    update={
                        "context": occurrence.context.model_copy(
                            update={"physical_old_field_name": "node_states"}
                        )
                    }
                ),
            ),
        }
    )

    with pytest.raises(AnchorRefusedError, match="context does not match"):
        compile_operation_stream((source,), invalid, query_migration_skeleton(invalid))


def test_projection_call_context_refuses_negative_positional_index() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        ProjectionCallContext(
            callee_origin="orchestrator.graph.run_state",
            projection_role="positional",
            positional_index=-1,
            projection_expression="projection",
        )


def test_compile_operation_stream_round_trips_exact_ambiguous_star_forms() -> None:
    manifest = load_manifest(MANIFEST_PATH)
    source = SourceSnapshot(
        relative_path="src/stars.py",
        source=(
            "from orchestrator.graph import GraphProjection, run_state\n\n"
            "def calls(projection: GraphProjection, values: tuple[object, ...]) -> None:\n"
            "    run_state(*projection)\n"
            "    run_state(**projection)\n"
            "    run_state(*values, projection)\n"
        ),
    )
    inventory = inventory_sources((source,), manifest)
    stream = compile_operation_stream((source,), inventory, query_migration_skeleton(inventory))
    contexts = [
        site.anchor.context.model_dump(exclude_none=True)
        for site in stream.sites
        if site.anchor.context is not None
    ]
    assert contexts == [
        {
            "callee_origin": "orchestrator.graph.run_state",
            "projection_role": "ambiguous",
            "projection_expression": "projection",
            "argument_star": "*",
        },
        {
            "callee_origin": "orchestrator.graph.run_state",
            "projection_role": "ambiguous",
            "projection_expression": "projection",
            "argument_star": "**",
        },
        {
            "callee_origin": "orchestrator.graph.run_state",
            "projection_role": "ambiguous",
            "projection_expression": "projection",
            "preceding_star": "*",
        },
    ]


def test_projection_call_context_refuses_contradictory_ambiguous_star_facts() -> None:
    for argument_star, preceding_star in ((None, None), ("*", "**")):
        with pytest.raises(ValueError, match="exactly one star"):
            ProjectionCallContext(
                callee_origin="orchestrator.graph.run_state",
                projection_role="ambiguous",
                projection_expression="projection",
                argument_star=argument_star,
                preceding_star=preceding_star,
            )


def test_query_composition_group_reanchors_outer_expression() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return bool(projection['run_state'])\n"
        ),
    )
    context = ProjectionCallContext(
        projection_role="receiver",
        projection_expression="projection",
        physical_old_field_name="run_state",
        physical_access_kind=AccessKind.LITERAL_SUBSCRIPT_READ,
        physical_operation_shape="literal_subscript_read",
    )
    site = MigrationSite(
        origin="occurrence",
        original_site_id="site",
        relative_path=source.relative_path,
        qualified_function="read",
        access_kind=AccessKind.LITERAL_SUBSCRIPT_READ,
        old_field_name="run_state",
        diagnostic_code=None,
        normalized_expression="projection['run_state']",
        domain="lifecycle",
        ordinal=0,
        source_digest=source_digest(source.source),
        locator=SourceLocator(line=4, column=16),
        anchor=CstAnchorEvidence(
            node_type="Subscript",
            normalized_expression="projection['run_state']",
            same_expression_ordinal=0,
            context=context,
        ),
        parent_shape="return",
        operation_shape="subscript_read",
    )
    disposition = DispositionPlan(
        operations=(
            PlannedOperation(
                disposition="query_transform",
                reason="test",
                consumed_site_ids=("site",),
                shape_key="literal_subscript_read|run_state|-|return|subscript_read",
            ),
        ),
        reviewed_deferred_site_ids=(),
        generated_fixture_operations=(),
        pending_site_ids=(),
        disposition_counts=(("query_transform", 1),),
        shape_group_counts=(("literal_subscript_read|run_state|-|return|subscript_read", 1),),
        rule_family_counts=(),
        symbol_origin_counts=(),
        generated_fixture_family_counts=(),
    )

    plan = compile_query_composition_plan((source,), OperationStream(sites=(site,)), disposition)

    assert isinstance(plan, QueryCompositionPlan)
    group = plan.groups[0]
    assert group.source_span == (4, 11, 4, 40)
    assert group.original_outer_expression == "bool(projection['run_state'])"
    assert group.consumed_site_ids == ("site",)
    assert group.owner_site_id is None
    assert group.anchor_relations == ()


@pytest.mark.parametrize(
    ("expression", "expected_outer_type"),
    [
        (
            "(projection['run_state'], projection['task_states'])",
            "Tuple",
        ),
        (
            "[projection['run_state'], projection['task_states']]",
            "List",
        ),
    ],
)
def test_query_composition_groups_sibling_anchors_under_one_synthetic_owner(
    expression: str, expected_outer_type: str
) -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection, node: str) -> object:\n"
            f"    return {expression}\n"
        ),
    )

    plan, stream, disposition = _compile_occurrence_composition(source)
    shuffled = compile_query_composition_plan(
        (source,),
        stream.model_copy(update={"sites": tuple(reversed(stream.sites))}),
        disposition.model_copy(update={"operations": tuple(reversed(disposition.operations))}),
    )

    assert plan == shuffled
    assert len(plan.groups) == 1
    group = plan.groups[0]
    assert len(group.consumed_site_ids) == 2
    assert group.owner_site_id is None
    assert group.owner_anchor.node_type == expected_outer_type
    assert group.anchor_relations == ()


def test_query_composition_records_site_owned_outer_action() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )

    plan, _, _ = _compile_occurrence_composition(source)

    assert len(plan.groups) == 1
    group = plan.groups[0]
    assert group.owner_site_id is not None
    assert group.consumed_site_ids == (group.owner_site_id,)
    assert group.anchor_relations == ()


def test_query_composition_models_refuse_invalid_direct_construction() -> None:
    """Composition records are a closed immutable proof boundary, not loose DTOs."""
    anchor = CstAnchorEvidence(
        node_type="Call",
        normalized_expression="read(projection['run_state'])",
        same_expression_ordinal=0,
    )
    with pytest.raises(ValueError, match="nonblank"):
        QueryCompositionGroup(
            relative_path=" ",
            source_span=(1, 0, 1, 1),
            outer_action_id="outer:src/example.py:1:0:1:1",
            owner_site_id=None,
            owner_anchor=anchor,
            original_outer_expression="read(projection['run_state'])",
            consumed_site_ids=("site",),
            anchor_relations=(),
        )
    group = QueryCompositionGroup(
        relative_path="src/example.py",
        source_span=(1, 0, 1, 36),
        outer_action_id="outer:src/example.py:1:0:1:36",
        owner_site_id=None,
        owner_anchor=anchor,
        original_outer_expression="read(projection['run_state'])",
        consumed_site_ids=("left", "right"),
        anchor_relations=(),
    )
    with pytest.raises(ValueError, match="overlap"):
        QueryCompositionPlan(groups=(group, group))
    with pytest.raises(ValueError, match="path and span"):
        QueryCompositionGroup(**(group.model_dump() | {"outer_action_id": "outer:wrong"}))
    with pytest.raises(ValueError, match="acyclic"):
        QueryCompositionGroup(
            **(
                group.model_dump()
                | {
                    "consumed_site_ids": ("left", "middle", "right"),
                    "anchor_relations": (
                        ("left", "middle"),
                        ("middle", "right"),
                        ("right", "left"),
                    ),
                }
            )
        )


def test_query_replacements_preserve_outer_cst_and_exact_collection_operations() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "from orchestrator.graph.scheduler import NodeScheduleInfo\n\n"
            "def read(projection: GraphProjection, node_id: str) -> object:\n"
            "    return NodeScheduleInfo(\n"
            "        state=projection['node_states'].get(node_id, ''),\n"
            "        required_edges=node_id in projection['node_states'],\n"
            "        resource_claims=sorted(projection['node_states'].items()),\n"
            "        priority=projection['run_state'],\n"
            "    )\n"
        ),
    )

    plan = _compile_physical_replacements(source)

    assert len(plan.recipes) == 1
    replacement = plan.recipes[0].replacement_outer_expression
    assert "node_states_view(projection).get(node_id, '')" in replacement
    assert "node_id in node_states_view(projection)" in replacement
    assert "sorted(node_states_view(projection).items())" in replacement
    assert "priority=run_state(projection)" in replacement
    assert plan.mutation_handoffs == ()
    assert plan.unmatched_family_counts == ()
    assert plan.rule_family_counts == (
        ("mapping_snapshot", 3),
        ("scalar_read", 1),
    )
    assert plan.query_import_counts == (("node_states_view", 1), ("run_state", 1))


def test_query_replacements_preserve_nested_node_port_lookup_and_independent_defaults() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "from orchestrator.graph.scheduler import NodeScheduleInfo\n\n"
            "def read(projection: GraphProjection, node_id: str, port: str) -> object:\n"
            "    return NodeScheduleInfo(\n"
            "        required_edges=projection['input_bindings'].get(node_id, {}).get(port)\n"
            "    )\n"
        ),
    )

    plan = _compile_physical_replacements(source)

    assert len(plan.recipes) == 1
    assert "input_bindings_view(projection).get(node_id, {}).get(port)" in (
        plan.recipes[0].replacement_outer_expression
    )
    assert plan.recipes[0].query_imports == ("input_bindings_view",)


def test_query_replacements_preserve_comprehension_structure() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "from orchestrator.graph.scheduler import NodeScheduleInfo\n\n"
            "def read(projection: GraphProjection, node_ids: list[str]) -> object:\n"
            "    return NodeScheduleInfo(upstream_states={\n"
            "        node_id: projection['node_states'][node_id]\n"
            "        for node_id in node_ids\n"
            "        if node_id in projection['node_states']\n"
            "    })\n"
        ),
    )

    plan = _compile_physical_replacements(source)

    assert sum(len(item.consumed_site_ids) for item in plan.recipes) == 2
    assert all(
        "projection['node_states']" not in item.replacement_outer_expression
        for item in plan.recipes
    )


def test_query_replacements_handoff_structural_mutations_without_inventing_a_query() -> None:
    source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def seed(projection: GraphProjection) -> None:\n"
            "    projection['run_state'] = 'active'\n"
        ),
    )

    plan = _compile_physical_replacements(source)

    assert plan.recipes == ()
    assert len(plan.mutation_handoffs) == 1
    handoff = plan.mutation_handoffs[0]
    assert handoff.effective_old_field == "run_state"
    assert handoff.access_kind == "direct_assignment"
    assert handoff.rule_id == "fixture_direct_assignment"
    assert plan.consumed_site_ids == frozenset(handoff.consumed_site_ids)


def test_query_replacement_plan_is_deterministic_and_refuses_unknown_structural_family() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )
    inventory = inventory_sources((source,), load_manifest(MANIFEST_PATH))
    stream = compile_operation_stream(
        (source,), inventory, query_migration_skeleton(inventory, ROOT)
    )
    plan, _, disposition = _compile_occurrence_composition(source)

    first = compile_query_replacement_plan((source,), stream, disposition, plan)
    shuffled = compile_query_replacement_plan(
        (source,),
        stream.model_copy(update={"sites": tuple(reversed(stream.sites))}),
        disposition.model_copy(update={"operations": tuple(reversed(disposition.operations))}),
        plan,
    )
    assert first == shuffled

    unmatched_source = SourceSnapshot(
        relative_path="src/unmatched.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['node_candidates']\n"
        ),
    )
    with pytest.raises(AnchorRefusedError, match="unmatched query replacement structural families"):
        _compile_physical_replacements(unmatched_source)


def test_query_replacement_models_refuse_overlapping_spans_and_blank_handoffs() -> None:
    first = QueryReplacementRecipe(
        relative_path="src/example.py",
        source_span=(1, 0, 1, 23),
        original_outer_expression="projection['run_state']",
        replacement_outer_expression="run_state(projection)",
        consumed_site_ids=("first",),
        query_imports=("run_state",),
        rule_ids=("scalar_read",),
    )
    second = first.model_copy(update={"consumed_site_ids": ("second",)})
    with pytest.raises(ValueError, match="overlap"):
        QueryReplacementPlan(
            recipes=(first, second),
            mutation_handoffs=(),
            unmatched_family_counts=(),
            rule_family_counts=(("scalar_read", 2),),
            query_import_counts=(("run_state", 2),),
        )
    with pytest.raises(ValueError, match="nonblank"):
        QueryMutationHandoff(
            relative_path=" ",
            source_span=(1, 0, 1, 23),
            original_outer_expression="projection['run_state']",
            consumed_site_ids=("mutation",),
            effective_old_field="run_state",
            access_kind="direct_assignment",
            operation_shape="direct_assignment",
            rule_id="fixture_direct_assignment",
        )


def test_query_source_apply_replaces_exact_outer_and_routes_merged_imports() -> None:
    external = SourceSnapshot(
        relative_path="src/orchestrator/graph_runtime/example.py",
        source=(
            "from orchestrator.graph import GraphProjection, run_state\n\n"
            "def read(projection: GraphProjection, node_id: str) -> object:\n"
            "    return projection['node_states'][node_id], projection['run_state']\n"
        ),
    )
    internal = SourceSnapshot(
        relative_path="src/orchestrator/graph/example.py",
        source=(
            "from orchestrator.graph.projection_queries import node_kind\n\n"
            "from orchestrator.graph.projections import GraphProjection\n\n"
            "def read(projection: GraphProjection, node_id: str) -> object:\n"
            "    return projection['node_states'][node_id]\n"
        ),
    )
    plan = _merge_replacement_plans(
        _compile_physical_replacements(external),
        _compile_physical_replacements(internal),
    )

    applied = apply_query_replacement_plan((external, internal), plan)

    assert isinstance(applied, QuerySourceApplyPlan)
    by_path = {item.relative_path: item.transformed_source for item in applied.updates}
    assert (
        "from orchestrator.graph import node_states_view, GraphProjection, run_state"
        in by_path[external.relative_path]
    )
    assert "node_states_view" in by_path[external.relative_path]
    assert "run_state" in by_path[external.relative_path]
    assert (
        "from orchestrator.graph.projection_queries import node_states_view, node_kind"
        in by_path[internal.relative_path]
    )
    assert "projection['node_states']" not in by_path[external.relative_path]
    assert "projection['run_state']" not in by_path[external.relative_path]
    assert applied.consumed_site_ids == plan.consumed_site_ids


def test_query_source_apply_is_idempotent_and_leaves_mutation_handoff_unchanged() -> None:
    read_source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )
    mutation_source = SourceSnapshot(
        relative_path="tests/fixture.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def seed(projection: GraphProjection) -> None:\n"
            "    projection['run_state'] = 'active'\n"
        ),
    )
    plan = _merge_replacement_plans(
        _compile_physical_replacements(read_source),
        _compile_physical_replacements(mutation_source),
    )

    first = apply_query_replacement_plan((read_source, mutation_source), plan)
    transformed = tuple(
        SourceSnapshot(relative_path=item.relative_path, source=item.transformed_source)
        for item in first.updates
    ) + (mutation_source,)
    second = apply_query_replacement_plan(transformed, plan)

    assert tuple(item.transformed_source for item in second.updates) == tuple(
        item.transformed_source for item in first.updates
    )
    assert mutation_source.relative_path not in {item.relative_path for item in first.updates}
    assert len(plan.mutation_handoffs) == 1


def test_query_source_apply_refuses_stale_expression_before_producing_updates() -> None:
    source = SourceSnapshot(
        relative_path="src/example.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )
    plan = _compile_physical_replacements(source)
    stale = source.model_copy(
        update={"source": source.source.replace("run_state']", "run_state' ]")}
    )

    with pytest.raises(AnchorRefusedError, match="exact outer expression"):
        apply_query_replacement_plan((stale,), plan)


def test_query_source_apply_aliases_query_import_that_conflicts_with_a_local_binding() -> None:
    source = SourceSnapshot(
        relative_path="src/orchestrator/graph/example.py",
        source=(
            "from orchestrator.graph.projections import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    run_state = projection['run_state']\n"
            "    return run_state\n"
        ),
    )
    plan = _compile_physical_replacements(source)

    applied = apply_query_replacement_plan((source,), plan)
    transformed = applied.updates[0].transformed_source

    assert (
        "from orchestrator.graph.projection_queries import run_state as query_run_state"
        in transformed
    )
    assert "run_state = query_run_state(projection)" in transformed


def test_query_source_atomic_write_validates_every_original_before_writing(tmp_path: Path) -> None:
    first = SourceSnapshot(
        relative_path="src/first.py",
        source=(
            "from orchestrator.graph import GraphProjection\n\n"
            "def read(projection: GraphProjection) -> object:\n"
            "    return projection['run_state']\n"
        ),
    )
    second = first.model_copy(update={"relative_path": "src/second.py"})
    plan = _merge_replacement_plans(
        _compile_physical_replacements(first),
        _compile_physical_replacements(second),
    )
    applied = apply_query_replacement_plan((first, second), plan)
    for source in (first, second):
        path = tmp_path / source.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.source)
    second_path = tmp_path / second.relative_path
    second_path.write_text("stale\n")

    with pytest.raises(AnchorRefusedError, match="changed before atomic apply"):
        write_query_source_apply_plan(tmp_path, applied)

    assert (tmp_path / first.relative_path).read_text() == first.source
    assert second_path.read_text() == "stale\n"
