from __future__ import annotations

import ast
from pathlib import Path

import orchestrator.graph as graph
import orchestrator.graph.commands as commands
from scripts.codemods.remove_graph_command_effects import transform
from scripts.check_graph_payload_architecture import check_paths


def test_legacy_future_effect_factory_is_not_public() -> None:
    assert not hasattr(commands, "future_command_effects")
    assert not hasattr(graph, "future_command_effects")
    assert "future_command_effects" not in commands.__all__
    assert "future_command_effects" not in graph.__all__


def test_production_modules_do_not_call_legacy_future_effect_factory() -> None:
    offenders: list[str] = []
    for path in Path("src/orchestrator").rglob("*.py"):
        if path == Path("src/orchestrator/graph/composition.py"):
            continue
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "future_command_effects"
            for node in ast.walk(tree)
        ):
            offenders.append(str(path))
    assert offenders == []


def test_production_composition_is_catalog_only() -> None:
    catalog = graph.build_graph_catalog()
    dependencies = graph.build_graph_command_dependencies(catalog)

    assert dependencies.catalog is catalog
    assert not hasattr(dependencies, "future_effects")
    assert not hasattr(graph, "GraphCommandEffects")


def test_legacy_agent_death_applier_name_is_absent() -> None:
    offenders = [
        str(path)
        for root in (Path("src"), Path("scripts"))
        for path in root.rglob("*.py")
        if "_apply_agent_died" in path.read_text()
    ]
    assert offenders == []


def test_lifecycle_handlers_own_typed_effects_without_legacy_injection() -> None:
    retired_names = {
        "cancel_active_lease_events",
        "lifecycle_completion_decision_event",
        "failure_record_payload",
        "recovery_plan_record_payload",
    }
    legacy_tree = ast.parse(Path("src/orchestrator/graph/_commands.py").read_text())
    lifecycle_source = Path("src/orchestrator/graph/commands/lifecycle.py").read_text()

    legacy_definitions = {
        node.name for node in ast.walk(legacy_tree) if isinstance(node, ast.FunctionDef)
    }
    assert not {f"_{name}" for name in retired_names}.intersection(legacy_definitions)
    assert "GraphCommandEffects" not in lifecycle_source


def test_callback_handlers_own_typed_effects_without_legacy_injection() -> None:
    retired_names = {
        "accepted_output_record_events",
        "file_state_authority_conflict",
        "file_state_rejected_conflict",
        "file_state_rejected_events",
        "lease_node_id",
        "output_record_contract_conflict",
        "output_record_provenance_conflict",
        "planner_session_state_event",
        "required_output_record_conflict",
        "verification_record_conflict",
    }
    legacy_tree = ast.parse(Path("src/orchestrator/graph/_commands.py").read_text())
    composition_source = Path("src/orchestrator/graph/composition.py").read_text()
    callbacks_source = Path("src/orchestrator/graph/commands/callbacks.py").read_text()

    legacy_definitions = {
        node.name for node in ast.walk(legacy_tree) if isinstance(node, ast.FunctionDef)
    }
    assert not {f"_{name}" for name in retired_names}.intersection(legacy_definitions)
    assert not {name for name in legacy_definitions if "callback" in name and "obsolete" in name}
    assert not {
        target.id
        for node in legacy_tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
        if isinstance(target, ast.Name) and target.id.startswith("callback_")
    }
    assert all(name not in composition_source for name in retired_names)
    assert all(f"effects.{name}" not in callbacks_source for name in retired_names)


def test_callbacks_do_not_depend_on_raw_or_legacy_command_event_creation() -> None:
    callbacks_path = Path("src/orchestrator/graph/commands/callbacks.py")
    callbacks_source = callbacks_path.read_text()
    callbacks_tree = ast.parse(callbacks_source)

    legacy_imports = [
        node
        for node in ast.walk(callbacks_tree)
        if isinstance(node, ast.ImportFrom) and node.module == "orchestrator.graph._commands"
    ]

    assert legacy_imports == []
    assert "typed_topology_event" not in callbacks_source
    assert "event_factory" not in callbacks_source
    assert "Callable[[str, dict" not in callbacks_source


def test_reconcile_handler_owns_typed_effects_without_raw_creator_bridge() -> None:
    legacy_tree = ast.parse(Path("src/orchestrator/graph/_commands.py").read_text())
    schedule_source = Path("src/orchestrator/graph/commands/schedule.py").read_text()

    legacy_definitions = {
        node.name for node in ast.walk(legacy_tree) if isinstance(node, ast.FunctionDef)
    }
    schedule_tree = ast.parse(schedule_source)
    reconcile_handler = next(
        node
        for node in schedule_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_typed_reconcile"
    )
    reconcile_calls = {
        node.func.id
        for node in ast.walk(reconcile_handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_apply_reconcile" not in legacy_definitions
    assert "apply_reconcile" not in Path("src/orchestrator/graph/_commands.py").read_text()
    assert "handle_reconcile" not in schedule_source
    assert "event_factory" not in reconcile_calls
    assert "TypedEventCreator" in reconcile_calls


def test_schedule_tick_handler_owns_typed_effects_without_raw_creator_bridge() -> None:
    legacy_source = Path("src/orchestrator/graph/_commands.py").read_text()
    schedule_source = Path("src/orchestrator/graph/commands/schedule.py").read_text()

    assert "schedule_tick_effects" not in legacy_source
    assert "schedule_tick_effects" not in schedule_source
    assert "_execute_schedule_tick" not in schedule_source
    assert "handle_schedule_tick" not in schedule_source
    assert "event_factory" not in schedule_source
    assert ".model_dump(" not in schedule_source
    assert "Callable[[str, dict" not in schedule_source
    assert "TypedEventCreator" in schedule_source


def test_payload_architecture_guard_rejects_effect_bundles_and_raw_creator_bridges(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "effects.py"
    candidate.write_text(
        "class GraphCommandEffects:\n"
        "    source_repair_events: Callable[[str, dict[str, object]], dict[str, object]]\n\n"
        "def typed_lease_event_payload(event_type: str, payload: dict[str, object]) -> dict[str, object]:\n"
        "    return payload\n"
    )

    diagnostics = check_paths((candidate,))

    assert [diagnostic.category for diagnostic in diagnostics] == [
        "callable-field effect bundle",
        "raw event creator bridge",
    ]


def test_payload_architecture_guard_rejects_source_repair_raw_creator_bridges(
    tmp_path: Path,
) -> None:
    source_repair = tmp_path / "source_repair.py"
    source_repair.write_text(
        "from orchestrator.graph._commands import failed_check_recovery_events\n\n"
        "def repair(creator):\n"
        "    return creator.create_named('node_created', {})\n"
    )

    diagnostics = check_paths((source_repair,))

    assert {diagnostic.category for diagnostic in diagnostics} == {
        "source repair raw creator",
        "source repair legacy command import",
    }


def test_command_effect_codemod_matches_golden_output_and_is_idempotent() -> None:
    source = """\
context = CommandExecutionContext(
    run_id=run_id,
    future_effects=build_graph_command_dependencies(catalog).future_effects,
    catalog=catalog,
)
controller = GraphController(catalog=catalog, future_effects=effects)
"""

    first, changes = transform(source)
    second, second_changes = transform(first)

    assert changes == 2
    assert (
        first
        == """\
context = CommandExecutionContext(
    run_id=run_id,
    catalog=catalog)
controller = GraphController(catalog=catalog)
"""
    )
    assert first == second
    assert second_changes == 0


def test_command_effect_codemod_skips_parsing_without_future_effects() -> None:
    source = "not valid Python !!!\n"

    transformed, changes = transform(source)

    assert transformed == source
    assert changes == 0
