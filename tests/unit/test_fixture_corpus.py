"""Executable coverage checks for graph scenario fixtures."""

from pathlib import Path
from typing import Any

import yaml

from orchestrator.graph.clock import FakeClock, SequentialIdGenerator
from orchestrator.graph.scenario import run_scenario
from orchestrator.graph.store import InMemoryEventStore

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "graph"


def _fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.yaml"))


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    raw = yaml.safe_load(path.read_text())
    assert isinstance(raw, list), f"{path.name} must contain a list of scenarios"
    for scenario in raw:
        assert isinstance(scenario, dict), f"{path.name} contains a non-mapping scenario"
    return raw


def _all_scenarios() -> list[tuple[Path, dict[str, Any]]]:
    scenarios: list[tuple[Path, dict[str, Any]]] = []
    for path in _fixture_paths():
        scenarios.extend((path, scenario) for scenario in _load_scenarios(path))
    return scenarios


def test_all_fixtures_parse() -> None:
    assert len(_fixture_paths()) >= 8
    for path, scenario in _all_scenarios():
        assert scenario.get("name"), f"{path.name} has a scenario without name"
        assert "given_events" in scenario, f"{scenario.get('name')} lacks given_events"
        assert isinstance(scenario["given_events"], list)


def test_all_fixtures_run_through_harness() -> None:
    for path, scenario in _all_scenarios():
        result = run_scenario(
            scenario,
            InMemoryEventStore(),
            FakeClock(),
            SequentialIdGenerator(),
        )
        assert result.scenario_name == scenario["name"], path.name


def test_coverage_index_complete() -> None:
    rows = [
        line
        for line in (FIXTURE_DIR / "COVERAGE.md").read_text().splitlines()
        if line.startswith("| §")
    ]
    assert len(rows) >= 40


def test_fixture_names_unique() -> None:
    names = [scenario["name"] for _, scenario in _all_scenarios()]
    assert len(names) >= 40
    assert len(names) == len(set(names))
