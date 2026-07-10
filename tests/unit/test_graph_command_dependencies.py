from __future__ import annotations

import ast
from pathlib import Path

import orchestrator.graph as graph
import orchestrator.graph.commands as commands


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


def test_legacy_agent_death_applier_name_is_absent() -> None:
    offenders = [
        str(path)
        for root in (Path("src"), Path("scripts"))
        for path in root.rglob("*.py")
        if "_apply_agent_died" in path.read_text()
    ]
    assert offenders == []
