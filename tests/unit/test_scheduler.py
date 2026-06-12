"""Unit tests for pure graph scheduler helpers."""

from orchestrator.graph import (
    NodeScheduleInfo,
    claims_conflict,
    evaluate_readiness,
    schedule,
)
from orchestrator.graph.scheduler import ResourceClaim


def _repo_claim(mode: str, paths: list[str] | None = None) -> ResourceClaim:
    return ResourceClaim(mode=mode, scope="repo", paths=paths or [])


def _node(
    node_id: str,
    *,
    state: str = "ready",
    priority: int = 0,
    region_order: int = 0,
    creation_position: int = 0,
    claims: list[ResourceClaim] | None = None,
) -> NodeScheduleInfo:
    return NodeScheduleInfo(
        node_id=node_id,
        kind="worker",
        state=state,
        priority=priority,
        region_order=region_order,
        creation_position=creation_position,
        resource_claims=claims or [],
    )


def test_evaluate_readiness_basic() -> None:
    ready, reason = evaluate_readiness(_node("n1", state="planned"), "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_run_not_active() -> None:
    ready, reason = evaluate_readiness(_node("n1", state="planned"), "paused", [], [])

    assert ready is False
    assert reason == "run_not_active"


def test_evaluate_readiness_already_leased() -> None:
    ready, reason = evaluate_readiness(_node("n1", state="blocked"), "active", ["n1"], [])

    assert ready is False
    assert reason == "node_already_leased"


def test_evaluate_readiness_resource_conflict() -> None:
    node = _node("n1", state="planned", claims=[_repo_claim("write", ["src/a.py"])])

    ready, reason = evaluate_readiness(node, "active", [], [_repo_claim("read", ["src/a.py"])])

    assert ready is False
    assert reason == "resource_conflict"


def test_evaluate_readiness_read_read_compatible() -> None:
    node = _node("n1", state="planned", claims=[_repo_claim("read", ["src/a.py"])])

    ready, reason = evaluate_readiness(node, "active", [], [_repo_claim("read", ["src/a.py"])])

    assert ready is True
    assert reason == ""


def test_schedule_empty() -> None:
    decision = schedule([], "active", [], projection_position=42)

    assert decision.projection_position == 42
    assert decision.candidates == []
    assert decision.selected == []
    assert decision.deferred == []
    assert decision.deferred_reasons == {}


def test_schedule_tie_break_priority() -> None:
    nodes = [_node("low", priority=1), _node("high", priority=9), _node("mid", priority=4)]

    decision = schedule(nodes, "active", [], projection_position=1)

    assert decision.candidates == ["high", "mid", "low"]
    assert decision.selected == ["high", "mid", "low"]


def test_schedule_tie_break_node_id() -> None:
    nodes = [
        _node("node-c", region_order=1, creation_position=1),
        _node("node-a", region_order=1, creation_position=1),
        _node("node-b", region_order=1, creation_position=1),
    ]

    decision = schedule(nodes, "active", [], projection_position=1)

    assert decision.candidates == ["node-a", "node-b", "node-c"]


def test_claims_write_write_conflict() -> None:
    assert claims_conflict(_repo_claim("write", ["src/a.py"]), _repo_claim("write", ["src/b.py"]))
    assert claims_conflict(
        ResourceClaim("graph_write", "graph"), ResourceClaim("graph_write", "graph")
    )
    assert claims_conflict(
        ResourceClaim("review_write", "review"), _repo_claim("read", ["src/a.py"])
    )
    assert claims_conflict(
        ResourceClaim("external", "external", external_resource_key="github:repo", exclusive=True),
        ResourceClaim("external", "external", external_resource_key="github:repo"),
    )
    assert not claims_conflict(
        ResourceClaim("external", "external", external_resource_key="github:repo"),
        ResourceClaim("external", "external", external_resource_key="mcp:server"),
    )


def test_claims_read_write_conflict() -> None:
    assert claims_conflict(_repo_claim("read", ["src/a.py"]), _repo_claim("write", ["src/a.py"]))
    assert claims_conflict(_repo_claim("read"), _repo_claim("write", ["src/a.py"]))
    assert not claims_conflict(
        _repo_claim("read", ["src/a.py"]), _repo_claim("write", ["src/b.py"])
    )


def test_claims_read_read_compatible() -> None:
    assert not claims_conflict(_repo_claim("read", ["src/a.py"]), _repo_claim("read", ["src/a.py"]))


def test_schedule_decision_has_deferred_reasons() -> None:
    nodes = [
        _node("writer-a", claims=[_repo_claim("write", ["src/a.py"])]),
        _node("writer-b", claims=[_repo_claim("write", ["src/a.py"])]),
        _node("writer-c", claims=[_repo_claim("write", ["src/c.py"])]),
    ]

    decision = schedule(nodes, "active", [], projection_position=7, max_grants=2)

    assert decision.selected == ["writer-a"]
    assert decision.deferred == ["writer-b", "writer-c"]
    assert set(decision.deferred_reasons) == set(decision.deferred)
    assert decision.deferred_reasons["writer-b"] == "resource_conflict:write:write"
    assert decision.deferred_reasons["writer-c"] == "resource_conflict:write:write"
