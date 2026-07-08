"""Executable coverage checks for graph scenario fixtures."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph.clock import FakeClock, SequentialIdGenerator
from orchestrator.graph.models import EventEnvelope
from orchestrator.graph.projections import build_projection, projection_to_checkpoint
from orchestrator.graph.scenario import run_scenario
from orchestrator.graph.store import InMemoryEventStore
from orchestrator.graph_runtime.store import GraphEventStore, graph_aggregate_id

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
        assert result.passed, f"{path.name}::{scenario['name']}: {result.failures}"


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


def test_all_fixtures_assert_nonempty_projection() -> None:
    for path, scenario in _all_scenarios():
        then_projection = scenario.get("then_projection")
        assert isinstance(then_projection, dict), f"{path.name}::{scenario['name']}"
        assert then_projection, f"{path.name}::{scenario['name']} has empty then_projection"


def test_pure_projection_fixtures_do_not_echo_events() -> None:
    for path, scenario in _all_scenarios():
        if scenario.get("when_command") is not None:
            continue
        assert not scenario.get("then_events"), (
            f"{path.name}::{scenario['name']} has echo-style then_events"
        )


@pytest.mark.asyncio
async def test_fixture_corpus_replay_matches_checkpoint_and_compact_projection() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            await _assert_fixture_corpus_replay_parity(session)
    finally:
        await engine.dispose()


async def _assert_fixture_corpus_replay_parity(session: AsyncSession) -> None:
    store = GraphEventStore(session)
    for index, (path, scenario) in enumerate(_all_scenarios(), start=1):
        result = run_scenario(
            scenario,
            InMemoryEventStore(),
            FakeClock(),
            SequentialIdGenerator(),
        )
        assert result.passed, f"{path.name}::{scenario['name']}: {result.failures}"

        run_id = f"fixture-corpus-{index}"
        stored_events = _stored_events(run_id, result.events_produced)
        session.add_all(
            EventV2Model(
                aggregate_id=graph_aggregate_id(run_id),
                version=event.position,
                event_type=event.event_type,
                payload=event.model_dump_json(),
                timestamp=event.timestamp.isoformat(),
            )
            for event in stored_events
        )
        await session.flush()

        full_projection_checkpoint = projection_to_checkpoint(build_projection(stored_events))

        await store.rebuild_read_models(run_id)
        checkpoint = await store.read_projection_checkpoint(run_id)
        assert checkpoint is not None, f"{path.name}::{scenario['name']} lacks checkpoint"
        assert projection_to_checkpoint(checkpoint.projection) == full_projection_checkpoint, (
            f"{path.name}::{scenario['name']} checkpoint replay diverged"
        )

        compact_events = await store.read_run_summary_rebuild(run_id)
        compact_projection_checkpoint = projection_to_checkpoint(build_projection(compact_events))
        assert compact_projection_checkpoint == full_projection_checkpoint, (
            f"{path.name}::{scenario['name']} compact projection replay diverged"
        )


def _stored_events(run_id: str, events: list[EventEnvelope]) -> list[EventEnvelope]:
    return [
        event.model_copy(update={"run_id": run_id, "position": position})
        for position, event in enumerate(events, start=1)
    ]
