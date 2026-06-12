"""Round-trip tests for execution graph Pydantic models."""

from typing import Any, TypeVar

from pydantic import BaseModel

from orchestrator.graph.models import (
    Actor,
    ActorKind,
    Authority,
    CallbackEnvelope,
    EdgeModel,
    EventEnvelope,
    FileStateRecord,
    GraphRecord,
    GraphRecordKind,
    InputBinding,
    LeaseModel,
    LeaseState,
    NodeKind,
    NodeMembership,
    NodeModel,
    NodeState,
    OutputRecord,
    PatchEnvelope,
    PatchOp,
    PortModel,
    RecordSelector,
    ResourceClaim,
    RunLifecycleState,
    RunModel,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def assert_round_trips(model_type: type[ModelT], example: dict[str, Any]) -> None:
    parsed = model_type.model_validate(example)
    dumped = parsed.model_dump(mode="json")
    reparsed = model_type.model_validate(dumped)

    assert reparsed == parsed
    assert dumped == example


def test_run_model_round_trips() -> None:
    assert_round_trips(
        RunModel,
        {
            "run_id": "run-123",
            "routine_snapshot_id": "routine-snap-456",
            "repo_id": "repo-abc",
            "worktree_path": "worktrees/run-run-123",
            "run_branch": "orchestrator/run-run-123",
            "lifecycle_state": "active",
            "root_snapshot_id": "S0",
            "event_position": 128,
        },
    )


def test_node_model_round_trips() -> None:
    assert_round_trips(
        NodeModel,
        {
            "node_id": "build-A-1",
            "run_id": "run-123",
            "kind": "worker",
            "role": "builder",
            "state": "ready",
            "created_by_event": "evt-10",
            "authority": {
                "allowed_actions": [
                    "submit_records",
                    "request_clarification",
                    "raise_appeal",
                ],
                "resource_claims": [
                    {"mode": "write", "scope": "repo", "paths": ["src/**", "tests/**"]}
                ],
            },
            "inputs": [{"port": "requirements", "required": True}],
            "outputs": [{"port": "candidate", "schema": "ImplementationCandidate"}],
        },
    )


def test_node_membership_round_trips() -> None:
    assert_round_trips(
        NodeMembership,
        {
            "task_region_id": "task-A",
            "attempt_number": 2,
            "candidate_id": "candidate-A-2",
            "execution_id": "exec-build-A-2-1",
        },
    )


def test_port_model_round_trips() -> None:
    assert_round_trips(
        PortModel,
        {
            "node_id": "verify-A-1",
            "port": "verification_report",
            "direction": "output",
            "schema": "VerificationReport",
            "record_layers": ["output", "graph_record"],
        },
    )


def test_edge_model_round_trips() -> None:
    assert_round_trips(
        EdgeModel,
        {
            "edge_id": "edge-verify-A",
            "from_node_id": "build-A-1",
            "from_port": "candidate",
            "to_node_id": "verify-A-1",
            "to_port": "candidate_under_test",
            "required": True,
            "accepted_record_selector": {
                "record_kinds": ["output", "file_state"],
                "schema": "ImplementationCandidate",
            },
        },
    )


def test_input_binding_round_trips() -> None:
    assert_round_trips(
        InputBinding,
        {
            "edge_id": "edge-verify-A",
            "to_node_id": "verify-A-1",
            "to_port": "candidate_under_test",
            "record_ids": ["rec-output-1", "rec-file-S1"],
            "bound_at_position": 43,
        },
    )


def test_output_record_round_trips() -> None:
    assert_round_trips(
        OutputRecord,
        {
            "record_id": "rec-output-1",
            "record_kind": "output",
            "producer_node_id": "build-A-1",
            "port": "candidate",
            "schema": "ImplementationCandidate",
            "value": {
                "summary": "Implemented validation path",
                "changed_paths": ["src/foo.py", "tests/unit/test_foo.py"],
                "requirements_addressed": ["R1", "R4"],
            },
        },
    )


def test_file_state_record_round_trips() -> None:
    assert_round_trips(
        FileStateRecord,
        {
            "record_id": "rec-file-S1",
            "record_kind": "file_state",
            "snapshot_id": "S1",
            "base_snapshot_id": "S0",
            "producer_node_id": "build-A-1",
            "git": {
                "commit_sha": "abc123",
                "tree_sha": "def456",
                "no_commit_reason": None,
            },
            "tracked": [{"path": "src/foo.py", "status": "modified"}],
            "untracked": [],
            "ignored": [
                {
                    "path": ".pytest_cache",
                    "classification": "tool_cache",
                    "policy": "ephemeral_allowed",
                }
            ],
            "external": [],
        },
    )


def test_graph_record_round_trips() -> None:
    assert_round_trips(
        GraphRecord,
        {
            "record_id": "rec-graph-1",
            "record_kind": "node_state_changed",
            "run_id": "run-123",
            "producer_node_id": "controller",
            "payload": {"node_id": "build-A-1", "new_state": "completed"},
        },
    )


def test_actor_round_trips() -> None:
    assert_round_trips(Actor, {"kind": "controller"})


def test_event_envelope_round_trips_and_accepts_iso_timestamp() -> None:
    assert_round_trips(
        EventEnvelope,
        {
            "event_id": "evt-123",
            "run_id": "run-123",
            "position": 42,
            "event_type": "node_state_changed",
            "schema_version": 1,
            "actor": {"kind": "controller"},
            "causation_id": "callback-789",
            "correlation_id": "build-A-1",
            "timestamp": "2026-06-10T10:00:00Z",
            "payload": {},
        },
    )


def test_patch_envelope_round_trips() -> None:
    assert_round_trips(
        PatchEnvelope,
        {
            "patch_id": "patch-123",
            "proposed_by_node_id": "planner-1",
            "base_graph_position": 42,
            "ops": [
                {
                    "op": "create_node",
                    "node": {"node_id": "build-A2-1", "kind": "worker", "role": "builder"},
                },
                {
                    "op": "create_edge",
                    "from_node_id": "read-tests",
                    "from_port": "findings",
                    "to_node_id": "synthesis",
                    "to_port": "context",
                },
            ],
            "rationale_record_id": "rec-plan-rationale-1",
        },
    )


def test_lease_model_round_trips() -> None:
    assert_round_trips(
        LeaseModel,
        {
            "lease_id": "lease-1",
            "generation": 3,
            "run_id": "run-123",
            "node_id": "build-A-1",
            "session_id": "session-W7",
            "base_snapshot_id": "S0",
            "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["**"]}],
            "expires_at": "2026-06-10T10:20:00Z",
            "state": "active",
        },
    )


def test_callback_envelope_round_trips() -> None:
    assert_round_trips(
        CallbackEnvelope,
        {
            "run_id": "run-123",
            "node_id": "build-A-1",
            "execution_id": "exec-1",
            "lease_id": "lease-1",
            "lease_generation": 3,
            "base_snapshot_id": "S0",
            "observed_graph_position": 42,
            "idempotency_key": "callback-uuid",
            "records": [
                {"record_kind": "output", "port": "candidate", "value": {}},
                {"record_kind": "file_state", "port": "file_state", "value": {}},
            ],
            "proposed_graph_patches": [],
        },
    )


def test_all_models_import_and_enums_cover_prd_values() -> None:
    assert RunModel.__name__ == "RunModel"
    assert set(RunLifecycleState) == {
        RunLifecycleState.DRAFT,
        RunLifecycleState.QUEUED,
        RunLifecycleState.ACTIVE,
        RunLifecycleState.PAUSING,
        RunLifecycleState.PAUSED,
        RunLifecycleState.RESUMING,
        RunLifecycleState.CANCELLING,
        RunLifecycleState.CANCELLED,
        RunLifecycleState.COMPLETED,
        RunLifecycleState.FAILED,
    }
    assert {kind.value for kind in NodeKind} == {
        "root",
        "task_projection",
        "worker",
        "verifier",
        "check",
        "planner",
        "oversight",
        "appeal",
        "gate",
        "recovery",
        "review",
        "artifact",
        "requirement",
        "file_state",
        "session",
    }
    assert {state.value for state in NodeState} == {
        "planned",
        "blocked",
        "ready",
        "leased",
        "running",
        "suspended",
        "completed",
        "failed",
        "retired",
        "cancelled",
    }
    assert {kind.value for kind in GraphRecordKind} == {
        "node_created",
        "edge_created",
        "node_retired",
        "node_state_changed",
        "lease_granted",
        "lease_suspended",
        "lease_revoked",
        "callback_received",
        "callback_accepted",
        "callback_rejected_stale",
        "verification_passed",
        "verification_failed",
        "revision_created",
        "appeal_opened",
        "oversight_decision_recorded",
        "approval_decision_recorded",
        "graph_patch_accepted",
        "file_state_accepted",
    }
    assert {state.value for state in LeaseState} == {
        "active",
        "suspended",
        "revoked",
        "expired",
        "released",
    }
    assert Actor.model_validate({"kind": ActorKind.CONTROLLER}) == Actor(kind="controller")
    assert PatchOp.model_validate({"op": "retire_node", "node_id": "build-A-1"}).op
    assert ResourceClaim.model_validate({"mode": "read", "scope": "repo"}).mode == "read"
    assert Authority.model_validate({"allowed_actions": []}).allowed_actions == []
    assert RecordSelector.model_validate({"record_kinds": ["output"]}).record_kinds == ["output"]
