"""Generate deterministic behavior oracles for the graph projection migration."""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import sys
from dataclasses import asdict
from itertools import islice
from pathlib import Path
from typing import Any

import yaml
from httpx import ASGITransport, AsyncClient

from orchestrator.api import (
    build_final_invariant_blockers_response,
    build_graph_patch_attempts_response,
    build_graph_regions_response,
    build_graph_topology_response,
    build_scheduler_view_response,
    create_app,
)
from orchestrator.db import init_db
from orchestrator.graph import (
    FakeClock,
    GraphCommandContext,
    InMemoryEventStore,
    PatchCommandContext,
    SequentialIdGenerator,
    active_requirement_versions_view,
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
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    run_scenario,
    support_evidence_view,
)

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GRAPH_FIXTURES = ROOT / "tests" / "fixtures" / "graph"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "graph_projection_migration"
REPLAY_GOLDENS = GOLDEN_DIR / "replay_goldens.json"
PUBLIC_VIEW_GOLDENS = GOLDEN_DIR / "public_view_goldens.json"
FR17_GOLDEN_RUN_ID = "fr17-public-golden"
JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


def canonical_json(value: JsonValue) -> str:
    """Return the sole checked-in JSON representation for graph goldens."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def check_canonical_json(path: Path, value: JsonValue) -> str | None:
    """Return a bounded byte-exact diff when *path* is not canonical *value*."""
    expected_bytes = canonical_json(value).encode("utf-8")
    actual_bytes = path.read_bytes() if path.exists() else b""
    if actual_bytes == expected_bytes:
        return None
    actual = actual_bytes.decode("utf-8")
    expected = expected_bytes.decode("utf-8")
    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=str(path),
        tofile=f"expected/{path.name}",
        n=3,
    )
    rendered = "".join(islice(diff, 80))
    if actual and not actual.endswith("\n"):
        rendered += "\\ No newline at end of file\n"
    return rendered


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
    active_versions = active_requirement_versions_view(replay)
    support_freshness: dict[str, JsonValue] = {}
    for support_id, support in sorted(support_evidence_view(replay).items()):
        stale_reason = support.stale_reason
        if support.status != "active":
            stale_reason = stale_reason or f"support edge status is {support.status}"
        elif active_versions.get(support.requirement_id) is None:
            stale_reason = "requirement has no active version"
        elif support.requirement_version_id != active_versions[support.requirement_id]:
            stale_reason = "support edge targets a superseded requirement version"
        support_freshness[support_id] = {
            "support_id": support_id,
            "evidence_id": support.evidence_id,
            "requirement_id": support.requirement_id,
            "requirement_version_id": support.requirement_version_id,
            "status": support.status,
            "freshness": "fresh" if stale_reason is None else "stale",
            "stale_reason": stale_reason,
        }
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
            "support_evidence": support_freshness,
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
    """Capture the complete public FR-17 HTTP readback contract."""
    return asyncio.run(_build_public_view_goldens())


async def _build_public_view_goldens() -> dict[str, JsonValue]:
    from tests.graph_fr17_fixture import create_graph_run, seed_less_used_readback_graph

    app = create_app(db_path=":memory:", routine_dirs=[])
    await init_db(app.state.engine)
    try:
        await create_graph_run(app.state.session_factory, FR17_GOLDEN_RUN_ID)
        await seed_less_used_readback_graph(app.state.session_factory, FR17_GOLDEN_RUN_ID)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            surfaces = await _read_complete_fr17_surfaces(client)
        return {"fr17_complete": _normalize_volatile_run_transport_fields(surfaces)}
    finally:
        await app.state.engine.dispose()


async def _read_complete_fr17_surfaces(client: AsyncClient) -> dict[str, JsonValue]:
    run = FR17_GOLDEN_RUN_ID
    return {
        "run": await _get_json(client, f"/api/runs/{run}"),
        "graph": await _get_json(client, f"/api/runs/{run}/graph"),
        "events": await _get_json(client, f"/api/runs/{run}/graph/events?payload_mode=full"),
        "topology": await _get_json(client, f"/api/runs/{run}/graph/topology"),
        "scheduler": await _get_json(client, f"/api/runs/{run}/graph/scheduler"),
        "decisions": await _get_json(client, f"/api/runs/{run}/graph/decisions"),
        "patches": await _get_json(client, f"/api/runs/{run}/graph/patches"),
        "regions": await _get_json(client, f"/api/runs/{run}/graph/regions"),
        "final_blockers": await _get_json(client, f"/api/runs/{run}/graph/final-blockers"),
        "recovery_node": await _get_json(
            client, f"/api/runs/{run}/graph/nodes/recovery-1?payload_mode=full"
        ),
        "review_node": await _get_json(client, f"/api/runs/{run}/graph/nodes/review-1"),
    }


async def _get_json(client: AsyncClient, path: str) -> JsonValue:
    response = await client.get(path)
    response.raise_for_status()
    return response.json()


def _normalize_volatile_run_transport_fields(
    surfaces: dict[str, JsonValue],
) -> dict[str, JsonValue]:
    """Stabilize the run response's generated IDs and wall-clock timestamps.

    These four fields originate in the run persistence/transport layer rather
    than the deterministic FR-17 graph event stream.  Normalize only after the
    router has constructed its real response body.
    """
    run = dict(surfaces["run"])
    steps = run["steps"]
    assert isinstance(steps, list)
    run["created_at"] = "<volatile-created-at>"
    run["updated_at"] = "<volatile-updated-at>"
    run["steps"] = [
        {
            **step,
            "id": "<volatile-step-id>",
            "tasks": [{**task, "id": "<volatile-task-id>"} for task in step["tasks"]],
        }
        for step in steps
    ]
    return {**surfaces, "run": run}


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
    path.write_bytes(canonical_json(value).encode("utf-8"))


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
    mismatches = [
        (path, mismatch)
        for path, value in generated.items()
        if (mismatch := check_canonical_json(path, value)) is not None
    ]
    for path, mismatch in mismatches:
        print(f"golden mismatch: {path}")
        print(mismatch, end="" if mismatch.endswith("\n") else "\n")
    return int(bool(mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
