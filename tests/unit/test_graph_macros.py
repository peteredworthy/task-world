from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    EventEnvelope,
    FakeClock,
    PatchEnvelope,
    PatchOp,
    apply_command,
    expand_patch_macros,
    initial_projection,
    reduce_event,
    validate_patch,
)


def _patch(payload: dict[str, Any]) -> PatchEnvelope:
    expanded = expand_patch_macros(payload)
    return PatchEnvelope(
        patch_id=str(expanded["patch_id"]),
        proposed_by_node_id=str(expanded.get("proposed_by_node_id", "planner-1")),
        base_graph_position=int(expanded["base_graph_position"]),
        ops=[PatchOp(**op) for op in expanded["ops"]],
    )


def test_create_work_region_macro_expands_to_valid_patch() -> None:
    patch = _patch(
        {
            "patch_id": "macro-work",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {
                        "region_id": "feature-region",
                        "worker_id": "worker-feature",
                        "verifier_id": "verifier-feature",
                        "candidate_id": "candidate-feature",
                    },
                }
            ],
        }
    )

    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert result.accepted is True
    assert [op.op for op in patch.ops] == ["create_node", "create_node", "create_edge"]


def test_gap_planner_corrective_region_macro_expands_to_valid_patch() -> None:
    projection = initial_projection()
    projection["node_kinds"]["planner-gap"] = "planner"
    projection["node_roles"]["planner-gap"] = "gap_planner"
    projection["node_states"]["planner-gap"] = "running"
    patch = _patch(
        {
            "patch_id": "macro-corrective",
            "proposed_by_node_id": "planner-gap",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_corrective_region",
                    "args": {
                        "region_id": "corrective_work_region",
                        "worker_id": "worker-fix",
                        "verifier_id": "verifier-fix",
                        "candidate_id": "candidate-fix",
                    },
                }
            ],
        }
    )

    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=projection,
        actor_role="gap_planner",
    )

    assert result.accepted is True
    edge_ports = {(op.from_port, op.to_port) for op in patch.ops if op.op == "create_edge"}
    assert ("classified_gap", "classified_gap") in edge_ports
    assert ("candidate", "candidate_under_test") in edge_ports


def test_create_join_macro_uses_distinct_source_record_ports() -> None:
    patch = _patch(
        {
            "patch_id": "macro-join",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_join",
                    "args": {
                        "join_id": "join-1",
                        "sources": [
                            {"node_id": "worker-1", "port": "candidate"},
                            {"node_id": "check-1", "port": "check_result"},
                        ],
                    },
                }
            ],
        }
    )

    projection = initial_projection()
    projection["node_kinds"]["worker-1"] = "worker"
    projection["node_roles"]["worker-1"] = "builder"
    projection["node_states"]["worker-1"] = "completed"
    projection["node_kinds"]["check-1"] = "check"
    projection["node_roles"]["check-1"] = "invariant_gate"
    projection["node_states"]["check-1"] = "completed"
    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=projection,
        actor_role="planner",
    )

    assert result.accepted is True
    to_ports = [op.to_port for op in patch.ops if op.op == "create_edge"]
    assert to_ports == ["source_record_1", "source_record_2"]


def test_submit_patch_command_accepts_macro_invocations() -> None:
    events: list[EventEnvelope] = []
    output = apply_command(
        initial_projection(),
        events,
        "submit_patch",
        {
            "patch_id": "macro-work",
            "base_graph_position": 0,
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {"region_id": "feature-region"},
                }
            ],
        },
        FakeClock(),
        _Ids(),
    )

    projection = initial_projection()
    for event in output:
        projection = reduce_event(projection, event)

    assert output[0].event_type == "graph_patch_accepted"
    assert projection["node_kinds"]["worker-feature-region"] == "worker"
    assert projection["node_kinds"]["verifier-feature-region"] == "verifier"


def test_macro_invocations_reject_missing_required_typed_args() -> None:
    payload = {
        "patch_id": "macro-invalid",
        "base_graph_position": 0,
        "macro_invocations": [
            {
                "macro": "create_work_region",
                "args": {},
            }
        ],
    }

    try:
        expand_patch_macros(payload)
    except ValueError as exc:
        assert "create_work_region args invalid" in str(exc)
        assert "region_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_macro_invocations_reject_invalid_invocation_shape() -> None:
    payload = {
        "patch_id": "macro-invalid-shape",
        "base_graph_position": 0,
        "macro_invocations": [
            {
                "macro": "create_join",
                "args": {
                    "join_id": "join-1",
                    "sources": [{"port": "candidate"}],
                },
            }
        ],
    }

    try:
        expand_patch_macros(payload)
    except ValueError as exc:
        assert "create_join args invalid" in str(exc)
        assert "sources.0.node_id" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


class _Ids:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value
