"""Production graph-controller journal configuration boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


_PRODUCTION_ROOT = Path(__file__).parents[2] / "src" / "orchestrator"


def test_every_production_graph_controller_construction_supplies_journal_max_bytes() -> None:
    missing: list[str] = []
    for path in _PRODUCTION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Name) or function.id != "GraphController":
                continue
            if not any(keyword.arg == "journal_max_bytes" for keyword in node.keywords):
                missing.append(f"{path.relative_to(_PRODUCTION_ROOT)}:{node.lineno}")

    assert missing == []
