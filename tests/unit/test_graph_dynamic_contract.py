"""Table-driven assertions for the frozen dynamic-graph contract.

These pin the patch-validation rules documented in
``docs/graph-approach/dynamic-graph-contract.md`` (§2-§5) so the structural
contract the DG-5.1 saga discovered cannot silently regress. End-to-end binding,
completion, and the task-region footgun (§7) are covered by
``tests/integration/test_graph_dynamic_e2e.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from orchestrator.graph import node_contract_summary
from orchestrator.graph.models import PatchEnvelope, PatchOp
from orchestrator.graph.patch_validator import validate_patch
from orchestrator.graph.projections import GraphProjection, initial_projection


def _patch(ops: list[dict[str, Any]], *, proposed_by: str = "planner-1") -> PatchEnvelope:
    return PatchEnvelope(
        patch_id="patch-under-test",
        proposed_by_node_id=proposed_by,
        base_graph_position=0,
        ops=[PatchOp(**op) for op in ops],
        rationale_record_id=None,
    )


def _projection_with_classified_gap_successor(gap_node_id: str) -> GraphProjection:
    projection = initial_projection()
    projection["edges"] = {
        "edge-gap-corrective": {
            "edge_id": "edge-gap-corrective",
            "from_node_id": gap_node_id,
            "from_port": "classified_gap",
            "to_node_id": "worker-corrective",
            "to_port": "classified_gap",
            "required": True,
            "accepted_record_selector": {"record_kinds": ["gap_analysis"]},
        }
    }
    return projection


def test_agent_contracts_allow_runtime_file_state_output() -> None:
    for node_type, role in (
        ("planner", "planner"),
        ("planner", "gap_planner"),
        ("worker", "builder"),
        ("verifier", "verifier"),
        ("summarizer", None),
    ):
        summary = node_contract_summary(node_type, role)
        assert summary is not None
        assert "file_state" in summary["output_ports"]


def test_worker_contract_accepts_authority_decision_input() -> None:
    summary = node_contract_summary("worker", "builder")

    assert summary is not None
    assert summary["input_ports"]["authority"] == {
        "record_types": ["authority_decision"],
        "schemas": ["AuthorityDecision"],
        "required": False,
        "cardinality": "one",
    }


# --- canonical op fragments ------------------------------------------------- #
def _worker(node_id: str, region: str, candidate: str = "cand") -> dict[str, Any]:
    return {
        "op": "create_node",
        "node": {
            "node_id": node_id,
            "kind": "worker",
            "role": "builder",
            "state": "planned",
            "task_region_id": region,
            "candidate_id": candidate,
        },
    }


def _verifier(node_id: str, region: str, candidate: str = "cand") -> dict[str, Any]:
    return {
        "op": "create_node",
        "node": {
            "node_id": node_id,
            "kind": "verifier",
            "role": "verifier",
            "state": "planned",
            "task_region_id": region,
            "candidate_id": candidate,
        },
    }


def _edge(
    edge_id: str,
    frm: str,
    from_port: str,
    to: str,
    to_port: str,
    kinds: list[str],
) -> dict[str, Any]:
    return {
        "op": "create_edge",
        "edge_id": edge_id,
        "from_node_id": frm,
        "from_port": from_port,
        "to_node_id": to,
        "to_port": to_port,
        "required": True,
        "accepted_record_selector": {"record_kinds": kinds},
    }


_GAP_NODE = {
    "op": "create_node",
    "node": {
        "node_id": "planner-gap",
        "kind": "planner",
        "role": "gap_planner",
        "state": "planned",
    },
}
_SOURCE_VERIFIER = {
    "op": "create_node",
    "node": {
        "node_id": "verifier-x",
        "kind": "verifier",
        "role": "verifier",
        "state": "planned",
    },
}
_VERIFICATION_TO_GAP = _edge(
    "e1",
    "verifier-x",
    "verification_report",
    "planner-gap",
    "verification_evidence",
    ["verification", "check_result"],
)
_CORRECTIVE_WORKER = {
    "op": "create_node",
    "node": {
        "node_id": "worker-corrective",
        "kind": "worker",
        "role": "fixer",
        "state": "planned",
        "task_region_id": "corrective_work_region",
        "candidate_id": "cand-fix",
    },
}
_CLASSIFIED_GAP_EDGE = _edge(
    "e2",
    "planner-gap",
    "classified_gap",
    "worker-corrective",
    "classified_gap",
    ["gap_analysis"],
)
_INVARIANT_CHECK = {
    "op": "create_node",
    "node": {
        "node_id": "check-final",
        "kind": "check",
        "role": "invariant_gate",
        "state": "planned",
        "task_region_id": "corrective_work_region",
        "command_binding": "dynamic_feature_hidden_oracle",
    },
}
_CORRECTIVE_VERIFIER = {
    "op": "create_node",
    "node": {
        "node_id": "verifier-corrective",
        "kind": "verifier",
        "role": "verifier",
        "state": "planned",
        "task_region_id": "corrective_work_region",
    },
}
_INVARIANT_EDGE = _edge(
    "e3",
    "verifier-corrective",
    "verification_report",
    "check-final",
    "verification_evidence",
    ["verification", "check_result"],
)


# (case_id, ops, actor_role, expect_accepted, reason_substring)
CONTRACT_CASES: list[tuple[str, list[dict[str, Any]], str, bool, str | None]] = [
    # §2 required dynamic-region edges
    (
        "gap_planner_without_verification_edge",
        [_GAP_NODE],
        "planner",
        False,
        "gap planner requires verification input edge",
    ),
    (
        "gap_planner_with_verification_edge",
        [_SOURCE_VERIFIER, _GAP_NODE, _VERIFICATION_TO_GAP],
        "planner",
        True,
        None,
    ),
    (
        "corrective_worker_without_classified_gap",
        [_CORRECTIVE_WORKER],
        "planner",
        False,
        "corrective worker requires classified_gap input edge",
    ),
    ("corrective_worker_by_gap_planner_is_exempt", [_CORRECTIVE_WORKER], "gap_planner", True, None),
    (
        "invariant_check_without_verification_edge",
        [_INVARIANT_CHECK],
        "gap_planner",
        False,
        "invariant check requires verification input edge",
    ),
    (
        "invariant_check_with_verification_edge",
        [_CORRECTIVE_VERIFIER, _INVARIANT_CHECK, _INVARIANT_EDGE],
        "gap_planner",
        True,
        None,
    ),
    # §3 check command requirement
    (
        "check_without_command_rejected",
        [
            {
                "op": "create_node",
                "node": {
                    "node_id": "c",
                    "kind": "check",
                    "role": "invariant_gate",
                    "state": "planned",
                    "task_region_id": "corrective_work_region",
                },
            },
            _edge(
                "ce",
                "v",
                "verification_report",
                "c",
                "verification_evidence",
                ["verification", "check_result"],
            ),
        ],
        "gap_planner",
        False,
        "check node requires command_definition",
    ),
    # §4 gap-planner role authority
    (
        "gap_planner_cannot_create_planner_successor",
        [
            {
                "op": "create_node",
                "node": {"node_id": "p2", "kind": "planner", "role": "planner", "state": "planned"},
            }
        ],
        "gap_planner",
        False,
        "gap planner cannot create planner successor",
    ),
    (
        "gap_planner_executable_outside_corrective_region",
        [
            {
                "op": "create_node",
                "node": {
                    "node_id": "w",
                    "kind": "worker",
                    "role": "fixer",
                    "state": "planned",
                    "task_region_id": "feature-region",
                    "candidate_id": "c",
                },
            }
        ],
        "gap_planner",
        False,
        "gap planner executable nodes must target corrective_work_region",
    ),
    # generic op authority
    (
        "planner_cannot_create_gate",
        [{"op": "create_gate", "predecessor_node_ids": ["n1"]}],
        "planner",
        False,
        "cannot perform create_gate",
    ),
    ("unknown_op_rejected", [{"op": "frobnicate"}], "planner", False, "unknown op"),
]


@pytest.mark.parametrize(
    "ops,actor_role,expect_accepted,reason_substring",
    [(c[1], c[2], c[3], c[4]) for c in CONTRACT_CASES],
    ids=[c[0] for c in CONTRACT_CASES],
)
def test_patch_contract(
    ops: list[dict[str, Any]],
    actor_role: str,
    expect_accepted: bool,
    reason_substring: str | None,
) -> None:
    result = validate_patch(
        _patch(ops),
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role=actor_role,
    )
    assert result.accepted is expect_accepted, result.rejection_reason
    if reason_substring is not None:
        assert result.rejection_reason is not None
        assert reason_substring in result.rejection_reason


def test_authority_request_edge_to_worker_authority_port_is_valid() -> None:
    result = validate_patch(
        _patch(
            [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "authority-docs-write",
                        "kind": "authority_request",
                        "state": "planned",
                        "authority_request_record": {
                            "requested_authority": ["repo:docs/**:write"],
                            "target_node_id": "worker-docs-authorized",
                            "reason": "Worker needs docs write access.",
                        },
                    },
                },
                _worker("worker-docs-authorized", "authority-product-proof"),
                _edge(
                    "edge-authority-docs-write-to-worker-docs-authorized",
                    "authority-docs-write",
                    "authority_decision",
                    "worker-docs-authorized",
                    "authority",
                    ["authority_decision"],
                ),
            ]
        ),
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="planner",
    )

    assert result.accepted is True, result.rejection_reason


def test_gap_planner_no_op_allowed_when_classified_gap_successor_unsatisfied() -> None:
    """A no-gap gap-planner decision may use an empty patch; submit emits the
    durable classified_gap record that releases matching successors."""

    result = validate_patch(
        _patch([], proposed_by="planner-gap"),
        current_position=0,
        events_since_base=[],
        projection=_projection_with_classified_gap_successor("planner-gap"),
        actor_role="gap_planner",
    )
    assert result.accepted is True, result.rejection_reason


def test_gap_planner_no_op_allowed_without_open_classified_gap_successor() -> None:
    """A gap-planner no-op is allowed when no required classified_gap successor
    is waiting (nothing to starve)."""

    result = validate_patch(
        _patch([], proposed_by="planner-gap"),
        current_position=0,
        events_since_base=[],
        projection=initial_projection(),
        actor_role="gap_planner",
    )
    assert result.accepted is True, result.rejection_reason
