"""Generate deterministic behavior oracles for the graph projection migration."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from orchestrator.api import (
    build_final_invariant_blockers_response,
    build_graph_patch_attempts_response,
    build_graph_regions_response,
    build_graph_topology_response,
    build_scheduler_view_response,
)
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    FakeClock,
    GraphCommandContext,
    InMemoryEventStore,
    PatchCommandContext,
    SequentialIdGenerator,
    build_projection,
    initial_projection,
    project_decision_view,
    project_gatekeeper_report,
    project_graph_outcome,
    project_graph_projection_snapshot,
    project_node_metadata,
    project_planner_chain,
    project_planner_freshness_packet,
    project_planner_session,
    project_requirement_freshness_facts,
    project_residue_report,
    project_support_evidence_freshness,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    run_scenario,
)
from orchestrator.graph_runtime import GraphEventStore

ROOT = Path(__file__).resolve().parent.parent
GRAPH_FIXTURES = ROOT / "tests" / "fixtures" / "graph"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "graph_projection_migration"
REPLAY_GOLDENS = GOLDEN_DIR / "replay_goldens.json"
PUBLIC_VIEW_GOLDENS = GOLDEN_DIR / "public_view_goldens.json"
JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def _scenarios() -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for path in sorted(GRAPH_FIXTURES.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        assert isinstance(raw, list), path
        scenarios.extend(raw)
    return sorted(scenarios, key=lambda scenario: str(scenario["name"]))


def _context(scenario: dict[str, Any]) -> GraphCommandContext:
    run_id = str(scenario.get("run_id", "run-1"))
    position = len(scenario.get("given_events", [])) if scenario.get("when_command") else -1
    command = scenario.get("when_command")
    if isinstance(command, dict) and "submit_patch" in command:
        return PatchCommandContext.model_validate(
            {"run_id": run_id, "current_graph_position": position, **scenario["command_context"]}
        )
    return GraphCommandContext(run_id=run_id, current_graph_position=position)


def _events(scenario: dict[str, Any]) -> list[Any]:
    result = run_scenario(
        scenario,
        _context(scenario),
        InMemoryEventStore(),
        FakeClock(),
        SequentialIdGenerator(),
    )
    assert result.passed, f"{scenario['name']}: {result.failures}"
    return [
        event.model_copy(update={"position": position})
        for position, event in enumerate(result.events_produced, 1)
    ]


def _replay_views(events: list[Any]) -> dict[str, JsonValue]:
    replay = build_projection(events)
    incremental = initial_projection()
    for event in events:
        incremental = reduce_event(incremental, event)
    checkpoint = projection_to_checkpoint(replay)
    return {
        "full_replay": checkpoint,
        "incremental_replay": projection_to_checkpoint(incremental),
        "checkpoint_round_trip": projection_to_checkpoint(projection_from_checkpoint(checkpoint)),
        "topology": build_graph_topology_response("golden-run", events).model_dump(mode="json"),
        "scheduler": build_scheduler_view_response("golden-run", events).model_dump(mode="json"),
        "node_detail": project_node_metadata(events),
        "planner": {
            "chain": project_planner_chain(events),
            "session": project_planner_session(events),
            "freshness": project_planner_freshness_packet(events),
        },
        "verification": {
            "requirements": project_requirement_freshness_facts(events),
            "support_evidence": project_support_evidence_freshness(events),
        },
        "governance": project_decision_view(events),
        "recovery": {
            "outcome": asdict(
                project_graph_outcome(
                    "golden-run", project_graph_projection_snapshot(events, projection=replay)
                )
            ),
            "blockers": build_final_invariant_blockers_response("golden-run", events).model_dump(
                mode="json"
            ),
        },
        "records": {
            "residue": project_residue_report(events),
            "gatekeeper": project_gatekeeper_report(events),
        },
    }


def build_replay_goldens() -> dict[str, JsonValue]:
    """Capture pure replay behavior across every checked-in YAML scenario."""
    return {str(scenario["name"]): _replay_views(_events(scenario)) for scenario in _scenarios()}


def build_public_view_goldens() -> dict[str, JsonValue]:
    """Capture public presenter bodies for representative corpus scenarios."""
    return asyncio.run(_build_public_view_goldens())


async def _build_public_view_goldens() -> dict[str, JsonValue]:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            store = GraphEventStore(session)
            goldens: dict[str, JsonValue] = {}
            selected = [
                scenario for scenario in _scenarios() if scenario["name"].startswith("invariant_")
            ]
            for index, scenario in enumerate(selected, start=1):
                run_id = f"public-golden-{index}"
                events = [
                    event.model_copy(update={"run_id": run_id}) for event in _events(scenario)
                ]
                await store.append_events(run_id, 0, events)
                goldens[str(scenario["name"])] = public_view_bodies(
                    await store.read_run_summary_rebuild(run_id)
                )
            return goldens
    finally:
        await engine.dispose()


def public_view_bodies(events: list[Any], *, run_id: str = "golden-run") -> dict[str, JsonValue]:
    """Serialize the public graph presenter contract for an event stream."""
    events = _storage_positioned_events(events)
    return {
        "topology": build_graph_topology_response(run_id, events).model_dump(mode="json"),
        "scheduler": build_scheduler_view_response(run_id, events).model_dump(mode="json"),
        "patches": build_graph_patch_attempts_response(run_id, events).model_dump(mode="json"),
        "regions": build_graph_regions_response(run_id, events).model_dump(mode="json"),
        "final_blockers": build_final_invariant_blockers_response(run_id, events).model_dump(
            mode="json"
        ),
    }


def _storage_positioned_events(events: list[Any]) -> list[Any]:
    """Mirror the durable store's authoritative input-binding positions."""
    positioned: list[Any] = []
    for event in events:
        if event.event_type != "input_bound":
            positioned.append(event)
            continue
        payload = {**event.payload, "bound_at_position": event.position}
        positioned.append(event.model_copy(update={"payload": payload}))
    return positioned


def _write_json(path: Path, value: dict[str, JsonValue]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true")
    action.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = {
        REPLAY_GOLDENS: build_replay_goldens(),
        PUBLIC_VIEW_GOLDENS: build_public_view_goldens(),
    }
    if args.write:
        for path, value in generated.items():
            _write_json(path, value)
        return 0
    return (
        0
        if all(
            path.exists() and json.loads(path.read_text()) == value
            for path, value in generated.items()
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
