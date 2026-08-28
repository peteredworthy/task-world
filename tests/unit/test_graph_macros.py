from __future__ import annotations

from typing import Any

from orchestrator.graph import (
    node_kinds_view,
    EventEnvelope,
    FakeClock,
    PatchEnvelope,
    PatchCommandContext,
    PatchOp,
    expand_patch_macros,
    build_projection,
    initial_projection,
    reduce_event,
    validate_patch,
)
from orchestrator.graph import SubmitPatchCommand
from tests.unit.graph_test_utils import apply_command, event


def _patch(payload: dict[str, Any], proposed_by_node_id: str = "planner-1") -> PatchEnvelope:
    command = SubmitPatchCommand.model_validate(payload)
    ops = expand_patch_macros(command.ops, command.macro_invocations, proposed_by_node_id)
    return PatchEnvelope(
        patch_id=command.patch_id,
        proposed_by_node_id=proposed_by_node_id,
        base_graph_position=command.base_graph_position,
        ops=[PatchOp(**op) for op in ops],
    )


def _expand(payload: dict[str, Any]) -> list[dict[str, Any]]:
    proposed_by_node_id = "planner-1"
    command = SubmitPatchCommand.model_validate(payload)
    return expand_patch_macros(command.ops, command.macro_invocations, proposed_by_node_id)


def _projection_with_nodes(*nodes: dict[str, str]):
    return build_projection(
        [event("node_created", node, position=index) for index, node in enumerate(nodes)]
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
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
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
    worker = patch.ops[0].node
    assert worker is not None
    assert worker["authority"]["resource_claims"] == [
        {"mode": "write", "scope": "repo", "paths": ["."]}
    ]
    verifier = patch.ops[1].node
    assert verifier is not None
    assert "candidate_id" not in verifier


def test_gap_planner_corrective_region_macro_expands_to_valid_patch() -> None:
    projection = _projection_with_nodes(
        {"node_id": "planner-gap", "kind": "planner", "role": "gap_planner", "state": "running"},
        {
            "node_id": "verifier-failed",
            "kind": "verifier",
            "role": "verifier",
            "state": "completed",
        },
        {"node_id": "check-failed", "kind": "check", "role": "batch_check", "state": "completed"},
    )
    patch = _patch(
        {
            "patch_id": "macro-corrective",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_corrective_region",
                    "args": {
                        "region_id": "corrective_work_region",
                        "worker_id": "worker-fix",
                        "verifier_id": "verifier-fix",
                        "candidate_id": "candidate-fix",
                        "objective": "Produce a corrective candidate that resolves the classified gap.",
                        "access_mode": "write",
                        "acceptance": ["corrective candidate resolves the classified gap"],
                        "failed_verification_source_node_id": "verifier-failed",
                        "failed_check_source_node_ids": ["check-failed"],
                        "failed_verification_record_id": "verification-failed-1",
                        "failed_check_record_ids": ["check-result-failed-1"],
                        "classified_gap_record_id": "classified-gap-1",
                        "base_snapshot_selection": "accepted_region",
                        "base_snapshot_region_id": "feature-region",
                    },
                }
            ],
        },
        proposed_by_node_id="planner-gap",
    )

    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=projection,
        actor_role="gap_planner",
    )

    assert result.accepted is False
    assert result.rejection_reason == (
        "corrective worker classified_gap record must exist and match its edge producer"
    )
    selectors = {
        str(op.to_port): op.accepted_record_selector.model_dump()["record_id"]
        for op in patch.ops
        if op.to_node_id == "worker-fix" and op.accepted_record_selector is not None
    }
    assert selectors == {
        "classified_gap": "classified-gap-1",
        "verification_report": "verification-failed-1",
        "check_result": "check-result-failed-1",
    }


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

    projection = _projection_with_nodes(
        {"node_id": "worker-1", "kind": "worker", "role": "builder", "state": "completed"},
        {"node_id": "check-1", "kind": "check", "role": "invariant_gate", "state": "completed"},
    )
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


def test_request_gate_macro_expands_human_gate_with_decision_request() -> None:
    patch = _patch(
        {
            "patch_id": "macro-request-gate",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "request_gate",
                    "args": {
                        "gate_id": "gate-review",
                        "reason": "Review widened tool access.",
                        "options": ["approve", "reject", "defer"],
                        "default_option": "defer",
                    },
                }
            ],
        }
    )

    assert [op.op for op in patch.ops] == ["create_node"]
    gate = patch.ops[0].node
    assert gate is not None
    assert gate["kind"] == "human_gate"
    assert gate["decision_request"] == {
        "decision_type": "approval",
        "options": ["approve", "reject", "defer"],
        "consequence_summary": "Review widened tool access.",
        "default_option": "defer",
    }


def test_request_gate_macro_expands_authority_request() -> None:
    patch = _patch(
        {
            "patch_id": "macro-authority-request",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "request_gate",
                    "args": {
                        "gate_id": "gate-authority",
                        "kind": "authority_request",
                        "reason": "Worker needs docs write access.",
                        "requested_authority": ["repo:docs/**:write"],
                        "target_node_id": "worker-docs",
                    },
                }
            ],
        }
    )

    gate = patch.ops[0].node
    assert gate is not None
    assert gate["kind"] == "authority_request"
    assert gate["authority_request_record"] == {
        "requested_authority": ["repo:docs/**:write"],
        "reason": "Worker needs docs write access.",
        "target_node_id": "worker-docs",
    }


def test_submit_patch_command_accepts_macro_invocations() -> None:
    events: list[EventEnvelope] = []
    output = apply_command(
        initial_projection(),
        events,
        "submit_patch",
        {
            "patch_id": "macro-work",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {
                        "region_id": "feature-region",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
                    },
                }
            ],
        },
        PatchCommandContext(
            run_id="run-1",
            current_graph_position=0,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        ),
        FakeClock(),
        _Ids(),
    )

    projection = initial_projection()
    for emitted_event in output:
        projection = reduce_event(projection, emitted_event)

    assert output[0].event_type == "graph_patch_accepted"
    assert node_kinds_view(projection)["worker-feature-region"] == "worker"
    assert node_kinds_view(projection)["verifier-feature-region"] == "verifier"


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
        _expand(payload)
    except ValueError as exc:
        assert "create_work_region args invalid" in str(exc)
        assert "payload [missing]" in str(exc)
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
        _expand(payload)
    except ValueError as exc:
        assert "create_join args invalid" in str(exc)
        assert "payload [missing]" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_attach_check_macro_rejects_planner_authored_candidate_id() -> None:
    payload = {
        "patch_id": "macro-invalid-check-candidate",
        "base_graph_position": 0,
        "macro_invocations": [
            {
                "macro": "attach_check",
                "args": {
                    "region_id": "feature-region",
                    "candidate_id": "candidate-llm-authored",
                    "command_definition": {"id": "unit-check", "argv": ["true"]},
                },
            }
        ],
    }

    try:
        _expand(payload)
    except ValueError as exc:
        assert "attach_check args invalid" in str(exc)
        assert "payload [extra_forbidden]" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_attach_verifier_macro_rejects_planner_authored_candidate_id() -> None:
    payload = {
        "patch_id": "macro-invalid-verifier-candidate",
        "base_graph_position": 0,
        "macro_invocations": [
            {
                "macro": "attach_verifier",
                "args": {
                    "region_id": "feature-region",
                    "candidate_id": "candidate-llm-authored",
                },
            }
        ],
    }

    try:
        _expand(payload)
    except ValueError as exc:
        assert "attach_verifier args invalid" in str(exc)
        assert "payload [extra_forbidden]" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected ValueError")


def test_create_work_region_macro_forwards_worker_contract_fields() -> None:
    patch = _patch(
        {
            "patch_id": "macro-work-contract",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {
                        "region_id": "feature-region",
                        "objective": "Implement a candidate that satisfies the bound requirements.",
                        "access_mode": "write",
                        "acceptance": ["candidate satisfies the bound requirements"],
                    },
                }
            ],
        }
    )

    worker = patch.ops[0].node
    assert worker is not None
    assert worker["objective"] == "Implement a candidate that satisfies the bound requirements."
    assert worker["access_mode"] == "write"
    assert worker["acceptance"] == ["candidate satisfies the bound requirements"]

    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert result.accepted is True


def test_create_work_region_macro_without_contract_fields_is_rejected() -> None:
    patch = _patch(
        {
            "patch_id": "macro-work-no-contract",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {"region_id": "feature-region"},
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

    assert result.accepted is False
    assert result.rejection_reason == "worker node requires objective: worker-feature-region"


def test_create_work_region_macro_grants_read_claim_for_read_only_worker() -> None:
    patch = _patch(
        {
            "patch_id": "macro-work-read-only",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {
                        "region_id": "feature-region",
                        "objective": "Investigate root cause and report findings.",
                        "access_mode": "read_only",
                        "acceptance": ["root cause identified and documented"],
                    },
                }
            ],
        }
    )

    worker = patch.ops[0].node
    assert worker is not None
    assert worker["authority"]["resource_claims"] == [
        {"mode": "read", "scope": "repo", "paths": ["."]}
    ]

    result = validate_patch(
        patch,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert result.accepted is True


def test_create_work_region_macro_discovery_write_requires_separate_effectful_writer() -> None:
    base_args = {
        "region_id": "feature-region",
        "worker_role": "discovery",
        "objective": "Implement a candidate that satisfies the bound requirements.",
        "access_mode": "write",
        "acceptance": ["candidate satisfies the bound requirements"],
    }

    rejected_patch = _patch(
        {
            "patch_id": "macro-work-discovery-write",
            "base_graph_position": 0,
            "macro_invocations": [{"macro": "create_work_region", "args": base_args}],
        }
    )
    rejected_result = validate_patch(
        rejected_patch,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert rejected_result.accepted is False
    assert rejected_result.rejection_reason == (
        "discovery worker cannot declare access_mode write; use a separate "
        "effectful artifact-writer region: worker-feature-region"
    )

    accepted_patch = _patch(
        {
            "patch_id": "macro-work-discovery-write-override",
            "base_graph_position": 0,
            "macro_invocations": [
                {
                    "macro": "create_work_region",
                    "args": {
                        **base_args,
                        "access_mode_override_justification": (
                            "Requires write access to reproduce the failure in place."
                        ),
                    },
                }
            ],
        }
    )
    override_result = validate_patch(
        accepted_patch,
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert override_result.accepted is False
    assert override_result.rejection_reason == rejected_result.rejection_reason


class _Ids:
    def __init__(self) -> None:
        self._next = 1

    def next_id(self, prefix: str = "") -> str:
        value = f"{prefix}-{self._next}"
        self._next += 1
        return value
