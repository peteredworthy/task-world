"""Public query-boundary behavior."""

from datetime import UTC, datetime
from copy import deepcopy
import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    accepted_output_records_by_node_port_view,
    build_projection,
    completion_decision_passed,
    initial_projection,
    projection_to_checkpoint,
    output_records_by_node_port_view,
    run_state,
    task_region_snapshot_authority_view,
)
from tests.unit.graph_test_utils import canonical_event_payload
from tests.unit.graph_projection_behavior_cases import behavior_cases, case_projection, fold_events


def test_lifecycle_queries_preserve_missing_and_default_values() -> None:
    projection = initial_projection()

    assert run_state(projection) is None
    assert completion_decision_passed(projection) is False


def test_lifecycle_queries_read_active_and_completed_event_projections() -> None:
    active = build_projection((_event("active", "run_lifecycle_changed", _lifecycle("active")),))
    completed = build_projection(
        (
            _event("active", "run_lifecycle_changed", _lifecycle("active")),
            _event(
                "decision",
                "output_record_accepted",
                {
                    "record_id": "decision-1",
                    "record_type": "completion_decision",
                    "producer_node_id": "gate-final",
                    "port": "completion_decision",
                    "value": {"status": "passed"},
                },
            ),
            _event("completed", "run_lifecycle_changed", _lifecycle("completed")),
        )
    )

    assert run_state(active) == "active"
    assert run_state(completed) == "completed"
    assert completion_decision_passed(completed) is True


@pytest.mark.parametrize(
    "case",
    tuple(case for case in behavior_cases() if case.mutate_query_result is not None),
    ids=lambda case: case.event_type,
)
def test_matrix_public_query_results_cannot_mutate_projection_storage(case) -> None:
    _, projection = case_projection(case)
    checkpoint = deepcopy(projection_to_checkpoint(projection))
    original = case.query(projection)
    original_copy = deepcopy(original)

    assert case.mutate_query_result is not None
    case.mutate_query_result(original)

    assert projection_to_checkpoint(projection) == checkpoint
    assert case.query(projection) == original_copy
    case.assert_outcome(fold_events(case.prefix), projection)


@pytest.mark.parametrize(
    "case",
    tuple(case for case in behavior_cases() if case.frozen_query_result_target is not None),
    ids=lambda case: case.event_type,
)
def test_matrix_frozen_public_query_results_reject_field_assignment(case) -> None:
    _, projection = case_projection(case)
    checkpoint = deepcopy(projection_to_checkpoint(projection))
    original = case.query(projection)
    original_copy = deepcopy(original)

    assert case.frozen_query_result_target is not None
    model, field = case.frozen_query_result_target(original)
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        setattr(model, field, getattr(model, field))

    assert projection_to_checkpoint(projection) == checkpoint
    assert case.query(projection) == original_copy


def test_output_record_view_thaws_projected_verification_evidence_for_event_transport() -> None:
    projection = build_projection(
        (
            _query_event(
                1,
                "node_created",
                {"node_id": "verifier-serialization", "kind": "verifier", "state": "ready"},
            ),
            _query_event(
                2,
                "output_record_accepted",
                {
                    "record_id": "verification-serialization",
                    "record_kind": "verification",
                    "record_type": "verification_report",
                    "producer_node_id": "verifier-serialization",
                    "port": "verification_report",
                    "schema": "VerificationReport",
                    "candidate_id": "candidate-serialization",
                    "outcome": "failed",
                    "value": {"outcome": "failed", "grades": []},
                    "evidence": {"nested": {"record_ids": ["candidate-serialization"]}},
                },
            ),
        )
    )

    record = output_records_by_node_port_view(projection)["verifier-serialization"][
        "verification_report"
    ][0]
    payload = record.model_dump(mode="json")
    event = EventEnvelope(
        event_id="verification-transport",
        run_id="query-run",
        position=3,
        event_type="output_record_accepted",
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )

    assert payload["evidence"] == {"nested": {"record_ids": ["candidate-serialization"]}}
    assert '"evidence"' in event.model_dump_json()


def test_accepted_output_record_view_hides_file_state_acceptance_identity() -> None:
    projection = build_projection(
        (
            _query_event(
                1,
                "node_created",
                {"node_id": "worker-file-state", "kind": "worker", "state": "ready"},
            ),
            _query_event(
                2,
                "file_state_accepted",
                {
                    "record_id": "file-state-serialization",
                    "record_kind": "file_state",
                    "record_type": "file_state",
                    "producer_node_id": "worker-file-state",
                    "snapshot_id": "snapshot-file-state",
                    "base_snapshot_id": "base-file-state",
                    "git": {
                        "commit_sha": "commit-file-state",
                        "tree_sha": "tree-file-state",
                        "ref": "refs/orchestrator/snapshots/snapshot-file-state",
                    },
                },
            ),
        )
    )

    record = accepted_output_records_by_node_port_view(projection)["worker-file-state"][
        "file_state"
    ][0]["payload"]

    assert "acceptance_identity" not in record.model_dump(mode="json")


def test_task_region_snapshot_authority_preserves_rejected_and_advances_only_passed() -> None:
    events = (
        _query_event(
            1,
            "node_created",
            {
                "node_id": "worker-snapshots",
                "kind": "worker",
                "state": "completed",
                "task_region_id": "region-snapshots",
            },
        ),
        _query_event(
            2,
            "node_created",
            {
                "node_id": "verifier-snapshots",
                "kind": "verifier",
                "state": "completed",
                "task_region_id": "region-snapshots",
            },
        ),
        *_candidate_snapshot_events(3, "one", "failed"),
        *_candidate_snapshot_events(7, "two", "passed"),
    )

    rejected_only = task_region_snapshot_authority_view(build_projection(events[:6]))[
        "region-snapshots"
    ]
    authority = task_region_snapshot_authority_view(build_projection(events))["region-snapshots"]

    assert rejected_only.accepted_snapshot is None
    assert rejected_only.current_candidate_snapshot is not None
    assert rejected_only.current_candidate_snapshot.snapshot_id == "snapshot-one"
    assert [item.snapshot_id for item in rejected_only.rejected_snapshots] == ["snapshot-one"]
    assert authority.accepted_snapshot is not None
    assert authority.accepted_snapshot.snapshot_id == "snapshot-two"
    assert authority.accepted_snapshot.file_state_record_id == "file-state-two"
    assert authority.accepted_snapshot.verification_record_id == "verification-two"
    assert [item.snapshot_id for item in authority.rejected_snapshots] == ["snapshot-one"]


def _candidate_snapshot_events(
    position: int, suffix: str, outcome: str
) -> tuple[EventEnvelope, ...]:
    candidate_id = f"candidate-{suffix}"
    verification_id = f"verification-{suffix}"
    return (
        _query_event(
            position,
            "file_state_accepted",
            {
                "record_id": f"file-state-{suffix}",
                "record_kind": "file_state",
                "record_type": "file_state",
                "producer_node_id": "worker-snapshots",
                "snapshot_id": f"snapshot-{suffix}",
                "base_snapshot_id": "run-baseline" if suffix == "one" else "snapshot-one",
                "task_region_id": "region-snapshots",
                "candidate_id": candidate_id,
            },
        ),
        _query_event(
            position + 1,
            "output_record_accepted",
            {
                "record_id": candidate_id,
                "record_kind": "output",
                "record_type": "candidate",
                "producer_node_id": "worker-snapshots",
                "port": "candidate",
                "schema": "ImplementationCandidate",
                "candidate_id": candidate_id,
                "task_region_id": "region-snapshots",
                "attempt_number": 1,
                "file_state_record_ids": [f"file-state-{suffix}"],
                "value": {
                    "summary": suffix,
                    "file_state_record_ids": [f"file-state-{suffix}"],
                },
            },
        ),
        _query_event(
            position + 2,
            "output_record_accepted",
            {
                "record_id": verification_id,
                "record_kind": "verification",
                "record_type": "verification_report",
                "producer_node_id": "verifier-snapshots",
                "port": "verification_report",
                "schema": "VerificationReport",
                "candidate_id": candidate_id,
                "task_region_id": "region-snapshots",
                "outcome": outcome,
                "value": {"outcome": outcome, "grades": []},
            },
        ),
        _query_event(
            position + 3,
            f"verification_{outcome}",
            {
                "node_id": "verifier-snapshots",
                "verifier_node_id": "verifier-snapshots",
                "candidate_id": candidate_id,
                "task_region_id": "region-snapshots",
                "record_id": verification_id,
                "outcome": outcome,
                "value": {"outcome": outcome, "grades": []},
            },
        ),
    )


def _event(event_id: str, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        run_id="run-1",
        position={"active": 0, "decision": 1, "completed": 2}[event_id],
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )


def _lifecycle(to_state: str) -> dict[str, object]:
    return {
        "command_type": "run_lifecycle",
        "from_state": "queued" if to_state == "active" else "active",
        "to_state": to_state,
        "trigger": "test",
    }


def _query_event(position: int, event_type: str, payload: dict[str, object]) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"query-{position}",
        run_id="query-run",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.SYSTEM, id="system"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=canonical_event_payload(event_type, payload),
    )
