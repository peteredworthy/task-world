"""Unit tests for pure graph scheduler helpers."""

from orchestrator.graph import (
    InputEdgeInfo,
    NodeScheduleInfo,
    claims_conflict,
    evaluate_readiness,
    schedule,
)
from orchestrator.graph.scheduler import ResourceClaim


def _repo_claim(
    mode: str,
    paths: list[str] | None = None,
    *,
    snapshot_id: str | None = None,
) -> ResourceClaim:
    return ResourceClaim(mode=mode, scope="repo", paths=paths or [], snapshot_id=snapshot_id)


def _node(
    node_id: str,
    *,
    state: str = "ready",
    priority: int = 0,
    region_order: int = 0,
    creation_position: int = 0,
    claims: list[ResourceClaim] | None = None,
    kind: str = "worker",
    required_edges: list[InputEdgeInfo] | None = None,
    satisfied_input_ports: set[str] | None = None,
    upstream_states: dict[str, str] | None = None,
    upstream_kinds: dict[str, str] | None = None,
    upstream_pending_appeals: set[str] | None = None,
    gate_decisions: dict[str, bool] | None = None,
    failed_candidate_id: str | None = None,
    preconditions: list[str] | None = None,
    command_definition_present: bool = False,
) -> NodeScheduleInfo:
    return NodeScheduleInfo(
        node_id=node_id,
        kind=kind,
        state=state,
        priority=priority,
        region_order=region_order,
        creation_position=creation_position,
        resource_claims=claims or [],
        required_edges=required_edges or [],
        satisfied_input_ports=satisfied_input_ports or set(),
        upstream_states=upstream_states or {},
        upstream_kinds=upstream_kinds or {},
        upstream_pending_appeals=upstream_pending_appeals or set(),
        gate_decisions=gate_decisions or {},
        failed_candidate_id=failed_candidate_id,
        preconditions=preconditions or [],
        command_definition_present=command_definition_present,
    )


def _edge(
    from_node_id: str,
    to_port: str,
    *,
    required: bool = True,
    dependency_type: str = "input_binding",
) -> InputEdgeInfo:
    return InputEdgeInfo(
        from_node_id=from_node_id,
        from_port="out",
        to_node_id="n1",
        to_port=to_port,
        required=required,
        dependency_type=dependency_type,
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


def test_evaluate_readiness_missing_required_input() -> None:
    node = _node("n1", state="planned", required_edges=[_edge("producer-1", "candidate")])

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "missing_required_input:candidate"


def test_evaluate_readiness_optional_input_does_not_block() -> None:
    node = _node(
        "n1", state="planned", required_edges=[_edge("producer-1", "notes", required=False)]
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_state_dependency_waits_for_upstream_completion() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[
            _edge("producer-1", "prior_step_completion", dependency_type="state_dependency")
        ],
        upstream_states={"producer-1": "running"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "upstream_pending:producer-1"


def test_evaluate_readiness_state_dependency_does_not_require_input_binding() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[
            _edge("producer-1", "prior_step_completion", dependency_type="state_dependency")
        ],
        upstream_states={"producer-1": "completed"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_failed_upstream_blocks() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("producer-1", "candidate")],
        satisfied_input_ports={"candidate"},
        upstream_states={"producer-1": "failed"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "upstream_failed:producer-1"


def test_evaluate_readiness_pending_upstream_appeal_blocks() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("producer-1", "candidate")],
        satisfied_input_ports={"candidate"},
        upstream_states={"producer-1": "completed"},
        upstream_pending_appeals={"producer-1"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "upstream_failed:producer-1"


def test_evaluate_readiness_recovery_can_consume_failed_upstream() -> None:
    node = _node(
        "n1",
        kind="recovery",
        state="planned",
        required_edges=[_edge("producer-1", "failure")],
        satisfied_input_ports={"failure"},
        upstream_states={"producer-1": "failed"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_revision_can_consume_failed_verification() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("verify-1", "failed_verification")],
        satisfied_input_ports={"failed_verification"},
        upstream_states={"verify-1": "failed"},
        failed_candidate_id="candidate-1",
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_gate_input_must_be_approved() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("gate-1", "approval")],
        satisfied_input_ports={"approval"},
        upstream_states={"gate-1": "completed"},
        upstream_kinds={"gate-1": "gate"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "gate_not_approved:gate-1"


def test_evaluate_readiness_approved_gate_input_passes() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("gate-1", "approval")],
        satisfied_input_ports={"approval"},
        upstream_states={"gate-1": "completed"},
        upstream_kinds={"gate-1": "gate"},
        gate_decisions={"gate-1": True},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_authority_request_input_must_be_granted() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("authority-1", "authority")],
        satisfied_input_ports={"authority"},
        upstream_states={"authority-1": "completed"},
        upstream_kinds={"authority-1": "authority_request"},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "authority_not_granted:authority-1"


def test_evaluate_readiness_granted_authority_request_input_passes() -> None:
    node = _node(
        "n1",
        state="planned",
        required_edges=[_edge("authority-1", "authority")],
        satisfied_input_ports={"authority"},
        upstream_states={"authority-1": "completed"},
        upstream_kinds={"authority-1": "authority_request"},
        gate_decisions={"authority-1": True},
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_precondition_unmet_blocks_with_exact_reason() -> None:
    node = _node(
        "check-1",
        kind="check",
        state="planned",
        preconditions=["has_command_definition"],
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "precondition_failed:has_command_definition"


def test_evaluate_readiness_precondition_met_passes() -> None:
    node = _node(
        "check-1",
        kind="check",
        state="planned",
        preconditions=["has_command_definition"],
        command_definition_present=True,
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_no_preconditions_unaffected() -> None:
    ready, reason = evaluate_readiness(_node("worker-1", state="planned"), "active", [], [])

    assert ready is True
    assert reason == ""


def test_evaluate_readiness_external_claim_missing_key_invalid() -> None:
    node = _node(
        "external-1",
        state="planned",
        claims=[ResourceClaim("external", "external")],
    )

    ready, reason = evaluate_readiness(node, "active", [], [])

    assert ready is False
    assert reason == "invalid_claim:external_missing_key"


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


def test_schedule_tie_break_creation_position_before_node_id() -> None:
    nodes = [
        _node("node-a", region_order=1, creation_position=3),
        _node("node-b", region_order=1, creation_position=1),
        _node("node-c", region_order=1, creation_position=2),
    ]

    decision = schedule(nodes, "active", [], projection_position=1)

    assert decision.candidates == ["node-b", "node-c", "node-a"]
    assert decision.selected == ["node-b", "node-c", "node-a"]


def test_schedule_tie_break_controller_and_deterministic_nodes_before_agents() -> None:
    nodes = [
        _node("worker-1", kind="worker", creation_position=1),
        _node("verifier-1", kind="verifier", creation_position=2),
        _node("check-1", kind="check", creation_position=3),
        _node("join-1", kind="join", creation_position=4),
        _node("final-gate-1", kind="final_gate", creation_position=5),
    ]

    decision = schedule(nodes, "active", [], projection_position=1)

    assert decision.candidates == [
        "check-1",
        "join-1",
        "final-gate-1",
        "worker-1",
        "verifier-1",
    ]
    assert decision.selected == decision.candidates


def test_schedule_excludes_gate_nodes_from_leases() -> None:
    decision = schedule([_node("gate-1", kind="gate")], "active", [], projection_position=1)

    assert decision.candidates == []
    assert decision.selected == []


def test_resource_conflict_matrix_cells() -> None:
    read = _repo_claim("read", ["src/a.py"])
    write = _repo_claim("write", ["src/a.py"])
    graph_write = ResourceClaim("graph_write", "graph")
    review_write = _repo_claim("review_write", ["src/a.py"])
    external = ResourceClaim("external", "external", external_resource_key="github:repo")
    cases = [
        ("read", read, "read", read, False),
        ("read", read, "write", write, True),
        ("read", read, "graph_write", graph_write, False),
        ("read", read, "review_write", review_write, True),
        ("read", read, "external", external, False),
        ("write", write, "read", read, True),
        ("write", write, "write", write, True),
        ("write", write, "graph_write", graph_write, False),
        ("write", write, "review_write", review_write, True),
        ("write", write, "external", external, False),
        ("graph_write", graph_write, "read", read, False),
        ("graph_write", graph_write, "write", write, False),
        ("graph_write", graph_write, "graph_write", graph_write, True),
        ("graph_write", graph_write, "review_write", review_write, False),
        ("graph_write", graph_write, "external", external, False),
        ("review_write", review_write, "read", read, True),
        ("review_write", review_write, "write", write, True),
        ("review_write", review_write, "graph_write", graph_write, False),
        ("review_write", review_write, "review_write", review_write, True),
        ("review_write", review_write, "external", external, False),
        ("external", external, "read", read, False),
        ("external", external, "write", write, False),
        ("external", external, "graph_write", graph_write, False),
        ("external", external, "review_write", review_write, False),
        ("external", external, "external", external, False),
    ]

    for existing_name, existing, requested_name, requested, expected in cases:
        assert claims_conflict(existing, requested) is expected, (
            f"{existing_name} x {requested_name}"
        )


def test_claims_read_write_conflict() -> None:
    assert claims_conflict(_repo_claim("read", ["src/a.py"]), _repo_claim("write", ["src/a.py"]))
    assert claims_conflict(_repo_claim("read"), _repo_claim("write", ["src/a.py"]))
    assert not claims_conflict(
        _repo_claim("read", ["src/a.py"]), _repo_claim("write", ["src/b.py"])
    )


def test_glob_path_overlap_detects_file_under_recursive_glob() -> None:
    assert claims_conflict(_repo_claim("read", ["src/**"]), _repo_claim("write", ["src/foo.py"]))


def test_glob_path_overlap_distinguishes_disjoint_roots() -> None:
    assert not claims_conflict(_repo_claim("read", ["src/**"]), _repo_claim("write", ["docs/**"]))


def test_path_normalization_resolves_dot_dot_inside_repo() -> None:
    assert claims_conflict(
        _repo_claim("read", ["src/../src/a.py"]),
        _repo_claim("write", ["src/a.py"]),
    )


def test_path_escape_is_treated_as_conflicting() -> None:
    assert claims_conflict(_repo_claim("read", ["../secret"]), _repo_claim("write", ["docs/a.md"]))


def test_directory_claim_matches_recursively() -> None:
    assert claims_conflict(_repo_claim("read", ["src"]), _repo_claim("write", ["src/foo.py"]))


def test_empty_paths_mean_whole_repo() -> None:
    assert claims_conflict(_repo_claim("read"), _repo_claim("write", ["docs/a.md"]))


def test_snapshot_read_during_write_is_compatible_both_directions() -> None:
    snapshot_read = _repo_claim("read", ["src/a.py"], snapshot_id="S0")
    write = _repo_claim("write", ["src/a.py"])

    assert not claims_conflict(snapshot_read, write)
    assert not claims_conflict(write, snapshot_read)


def test_live_read_during_write_is_deferred_both_directions() -> None:
    live_read = _repo_claim("read", ["src/a.py"])
    write = _repo_claim("write", ["src/a.py"])

    assert claims_conflict(live_read, write)
    assert claims_conflict(write, live_read)


def test_external_exclusive_conflicts_both_directions() -> None:
    exclusive_external = ResourceClaim(
        "external",
        "external",
        external_resource_key="github:repo",
        exclusive=True,
    )
    read = _repo_claim("read", ["src/a.py"])

    assert claims_conflict(exclusive_external, read)
    assert claims_conflict(read, exclusive_external)


def test_external_missing_key_conflicts_conservatively() -> None:
    missing_key = ResourceClaim("external", "external")
    keyed = ResourceClaim("external", "external", external_resource_key="github:repo")
    read = _repo_claim("read", ["src/a.py"])

    assert claims_conflict(missing_key, keyed)
    assert claims_conflict(keyed, missing_key)
    assert claims_conflict(missing_key, read)
    assert claims_conflict(read, missing_key)


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
