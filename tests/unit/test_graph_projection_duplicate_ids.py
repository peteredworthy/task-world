"""RED coverage for immutable graph-projection duplicate and collision rules."""

from datetime import UTC, datetime
from typing import Any

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    ApprovalDecisionRecordedPayload,
    AuthorityDecisionRecordedPayload,
    CleanupAppliedPayload,
    CleanupRequestedPayload,
    FileStateAcceptedPayload,
    GatekeeperVerdictRecordedPayload,
    NodeCreatedPayload,
    NodeReadyPayload,
    NodeStateChangedPayload,
    OutputRecordAcceptedPayload,
    OversightDecisionRecordedPayload,
    ProjectionReplayConflictError,
    ProjectedFileStateRecord,
    RecordStore,
    EventEnvelope,
    accepted_output_records_by_node_port_view,
    active_requirement_versions_view,
    build_projection,
    edges_view,
    initial_projection,
    insert_projected_record,
    file_state_records_view,
    node_creation_positions_view,
    node_roles_view,
    node_states_view,
    node_task_regions_view,
    node_resource_claims_view,
    output_record_payloads_view,
    project_node_max_attempts,
    projection_from_checkpoint,
    projection_to_checkpoint,
    reduce_event,
    ready_nodes_view,
    task_candidates_view,
)


def _event(
    event_type: str,
    payload: dict[str, Any],
    *,
    position: int,
    event_id: str | None = None,
) -> EventEnvelope:
    payload_model: Any = {
        "node_created": NodeCreatedPayload,
        "node_ready": NodeReadyPayload,
        "node_state_changed": NodeStateChangedPayload,
        "output_record_accepted": OutputRecordAcceptedPayload,
        "file_state_accepted": FileStateAcceptedPayload,
        "gatekeeper_verdict_recorded": GatekeeperVerdictRecordedPayload,
        "cleanup_requested": CleanupRequestedPayload,
        "cleanup_applied": CleanupAppliedPayload,
        "approval_decision_recorded": ApprovalDecisionRecordedPayload,
        "authority_decision_recorded": AuthorityDecisionRecordedPayload,
        "oversight_decision_recorded": OversightDecisionRecordedPayload,
    }.get(event_type)
    if payload_model is not None:
        payload = payload_model.model_validate(payload).model_dump(mode="json")
    return EventEnvelope(
        event_id=event_id or f"event-{position}",
        run_id="run-1",
        position=position,
        event_type=event_type,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )


def _node(
    node_id: str = "worker-1",
    *,
    position: int = 0,
    **fields: Any,
) -> EventEnvelope:
    return _event(
        "node_created",
        {"node_id": node_id, "kind": "worker", "state": "planned", **fields},
        position=position,
    )


def _candidate_record(
    record_id: str = "candidate-1",
    *,
    position: int = 0,
    value: dict[str, Any] | None = None,
    producer_node_id: str = "worker-1",
    record_type: str = "candidate",
    port: str = "candidate",
    schema: str = "ImplementationCandidate",
    record_kind: str = "output",
) -> EventEnvelope:
    payload = {
        "record_id": record_id,
        "record_kind": record_kind,
        "record_type": record_type,
        "producer_node_id": producer_node_id,
        "port": port,
        "schema": schema,
        "candidate_id": record_id,
        "task_region_id": "task-1",
        "attempt_number": 1,
        "value": value or {"summary": "candidate"},
    }
    return _event("output_record_accepted", payload, position=position)


def _fan_out_record(
    record_id: str = "record-1",
    *,
    position: int = 0,
    value: dict[str, Any] | None = None,
    producer_node_id: str = "worker-1",
    port: str = "candidate",
    schema: str = "ImplementationCandidate",
) -> EventEnvelope:
    return _candidate_record(
        record_id,
        position=position,
        value=value or {"nested": {"items": [1, {"ok": True}]}},
        producer_node_id=producer_node_id,
        record_type="fan_out_inputs",
        port=port,
        schema=schema,
    )


def _analysis_record(
    record_id: str = "record-1",
    *,
    position: int = 0,
    port: str = "analysis_summary",
    schema: str = "AnalysisSummary",
    producer_node_id: str = "worker-1",
) -> EventEnvelope:
    return _event(
        "output_record_accepted",
        {
            "record_id": record_id,
            "record_kind": "output",
            "record_type": "analysis_summary",
            "producer_node_id": producer_node_id,
            "port": port,
            "schema": schema,
            "value": {
                "summary": "summary",
                "source_record_ids": ["source-1"],
                "lossy": False,
                "omitted_details": [],
            },
        },
        position=position,
    )


def _file_state(
    record_id: str = "file-state-1",
    *,
    position: int = 0,
    tracked: list[dict[str, Any]] | None = None,
) -> EventEnvelope:
    return _event(
        "file_state_accepted",
        {
            "record_id": record_id,
            "record_type": "file_state",
            "record_kind": "file_state",
            "producer_node_id": "worker-1",
            "port": "file_state",
            "schema": "FileStateRecord",
            "snapshot_id": "snapshot-1",
            "base_snapshot_id": "snapshot-0",
            "tracked": tracked or [{"path": "src/app.py", "status": "modified"}],
            "classifications": [
                {
                    "path": "src/app.py",
                    "source": "tracked",
                    "classification": "unknown",
                    "needs_gatekeeper": True,
                }
            ],
            "verdict": "captured",
        },
        position=position,
    )


def _requirement_revision(
    version_id: str = "requirement-1.v1",
    *,
    position: int,
    requirement_id: str = "requirement-1",
    **fields: Any,
) -> EventEnvelope:
    return _event(
        "requirement_revision_recorded",
        {"requirement_id": requirement_id, "version_id": version_id, **fields},
        position=position,
    )


def _support_evidence(
    support_id: str = "support-1",
    *,
    position: int,
    evidence_id: str = "evidence-1",
    requirement_id: str = "requirement-1",
    requirement_version_id: str = "requirement-1.v1",
    **fields: Any,
) -> EventEnvelope:
    return _event(
        "support_evidence_recorded",
        {
            "support_id": support_id,
            "evidence_id": evidence_id,
            "requirement_id": requirement_id,
            "requirement_version_id": requirement_version_id,
            **fields,
        },
        position=position,
    )


def _gatekeeper_verdict(*, position: int) -> EventEnvelope:
    return _event(
        "gatekeeper_verdict_recorded",
        {
            "file_state_record_id": "file-state-1",
            "execution_id": "execution-1",
            "producer_node_id": "worker-1",
            "verdicts": [
                {
                    "path": "src/app.py",
                    "classification": "source",
                    "confidence": 1.0,
                    "rationale": "tracked source",
                }
            ],
            "resolved_count": 1,
        },
        position=position,
    )


def _cleanup_requested(*, position: int) -> EventEnvelope:
    return _event(
        "cleanup_requested",
        {
            "cleanup_id": "cleanup-1",
            "file_state_record_id": "file-state-1",
            "paths": ["src/app.py"],
            "reason": "test cleanup",
        },
        position=position,
    )


def _governance_decision_values(state: Any, event_type: str) -> dict[str, Any]:
    if event_type == "approval_decision_recorded":
        return {
            node_id: state.governance.approval_decisions_by_id[decision_id]
            for node_id, decision_id in state.governance.approval_decision_id_by_node.items()
        }
    if event_type == "authority_decision_recorded":
        return {
            node_id: state.governance.authority_decisions_by_id[decision_id]
            for node_id, decision_id in state.governance.authority_decision_id_by_node.items()
        }
    return {
        node_id: state.governance.oversight_decisions_by_id[decision_id]
        for node_id, decision_id in state.governance.oversight_decision_id_by_node.items()
    }


def test_identical_record_id_replay_is_idempotent_at_a_later_position() -> None:
    first = _fan_out_record(position=3)
    once = reduce_event(initial_projection(), first)

    twice = reduce_event(once, first.model_copy(update={"position": 4, "event_id": "retry"}))

    assert twice == once
    assert (
        output_record_payloads_view(twice)["record-1"]
        == output_record_payloads_view(once)["record-1"]
    )
    assert tuple(
        item["record_id"]
        for item in accepted_output_records_by_node_port_view(twice)["worker-1"]["candidate"]
    ) == ("record-1",)


def test_identical_requirement_revision_id_replay_preserves_first_write_and_indexes() -> None:
    first = _requirement_revision(position=3, classification="documentation")
    once = reduce_event(initial_projection(), first)

    twice = reduce_event(once, first.model_copy(update={"position": 4, "event_id": "retry"}))

    assert twice is once
    revision = projection_to_checkpoint(twice)["state"]["requirements"]["revisions_by_id"][
        "requirement-1.v1"
    ]
    assert revision is not None
    assert revision["position"] == 3
    assert active_requirement_versions_view(twice) == {"requirement-1": "requirement-1.v1"}


def test_conflicting_requirement_revision_id_replay_preserves_requirements_indexes() -> None:
    original = _requirement_revision(
        position=2,
        classification="documentation",
        previous_version_id="requirement-1.v0",
    )
    state = build_projection(
        [
            _requirement_revision("requirement-1.v0", position=0, active=False),
            _support_evidence(
                "support-old",
                position=1,
                evidence_id="evidence-old",
                requirement_version_id="requirement-1.v0",
            ),
            original,
        ]
    )
    conflicting = original.model_copy(
        update={
            "event_id": "conflicting-revision",
            "position": 3,
            "payload": {
                **original.payload,
                "classification": "validation_strengthening",
                "requires_authority": True,
            },
        }
    )

    with pytest.raises(
        ProjectionReplayConflictError, match=r"requirement revision.*requirement-1.v1.*event"
    ):
        reduce_event(state, conflicting)

    checkpoint = projection_to_checkpoint(state)
    revision = checkpoint["state"]["requirements"]["revisions_by_id"]["requirement-1.v1"]
    assert revision is not None
    assert revision["change_classification"] == "documentation"
    assert revision["position"] == 2
    assert active_requirement_versions_view(state) == {"requirement-1": "requirement-1.v1"}
    old_support = checkpoint["state"]["requirements"]["support_by_id"]["support-old"]
    assert old_support is not None
    assert old_support["status"] == "active"
    assert (
        checkpoint["state"]["governance"]
        .get("authority_revision_blockers", {})
        .get("requirement-1.v1")
        is None
    )


def test_identical_support_evidence_id_replay_preserves_first_write_and_indexes() -> None:
    first = _support_evidence(position=3, status="active", confidence="high")
    once = reduce_event(initial_projection(), first)

    twice = reduce_event(once, first.model_copy(update={"position": 4, "event_id": "retry"}))

    assert twice is once
    support = projection_to_checkpoint(twice)["state"]["requirements"]["support_by_id"]["support-1"]
    assert support is not None
    assert support["position"] == 3
    assert support["status"] == "active"


def test_conflicting_support_evidence_id_replay_preserves_canonical_evidence_and_indexes() -> None:
    state = build_projection(
        [
            _requirement_revision(position=0, classification="semantic"),
            _support_evidence(position=1, status="active", confidence="high"),
        ]
    )
    conflicting = _support_evidence(
        position=2,
        evidence_id="evidence-2",
        requirement_id="requirement-2",
        requirement_version_id="requirement-2.v1",
        status="stale",
        confidence="low",
    )

    with pytest.raises(ProjectionReplayConflictError, match=r"support evidence.*support-1.*event"):
        reduce_event(state, conflicting)

    checkpoint = projection_to_checkpoint(state)
    support = checkpoint["state"]["requirements"]["support_by_id"]["support-1"]
    assert support is not None
    assert support["evidence_id"] == "evidence-1"
    assert support["requirement_id"] == "requirement-1"
    assert support["requirement_version_id"] == "requirement-1.v1"
    assert support["status"] == "active"
    assert support["confidence"] == "high"
    assert support["position"] == 1
    assert active_requirement_versions_view(state) == {"requirement-1": "requirement-1.v1"}
    assert (
        checkpoint["state"]["governance"]["authority_revision_blockers"].get("requirement-1.v1")
        is not None
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (_fan_out_record(), _fan_out_record(value={"nested": {"items": [2]}})),
        (_candidate_record(record_id="record-1"), _fan_out_record()),
        (
            _analysis_record(),
            _event(
                "file_state_accepted",
                {
                    "record_id": "record-1",
                    "record_kind": "file_state",
                    "record_type": "file_state",
                    "producer_node_id": "worker-1",
                    "snapshot_id": "snapshot-1",
                    "verdict": "captured",
                },
                position=1,
            ),
        ),
        (_analysis_record(), _analysis_record(producer_node_id="worker-2")),
        (_analysis_record(), _analysis_record(schema="RegionSummary")),
        (_analysis_record(), _analysis_record(port="planning_summary")),
    ],
    ids=["value", "type", "kind", "producer", "schema", "port"],
)
def test_conflicting_record_id_fails_replay(first: EventEnvelope, second: EventEnvelope) -> None:
    with pytest.raises(ProjectionReplayConflictError, match=r"record.*record-1"):
        build_projection([first, second.model_copy(update={"position": 1})])


def test_conflicting_duplicate_matrix_node_id_raises_typed_replay_conflict() -> None:
    state_with_matrix_node = reduce_event(initial_projection(), _node(position=1, role="builder"))
    conflicting_same_node_id_event = _node(position=2, role="verifier")

    with pytest.raises(ProjectionReplayConflictError, match="conflicts during replay") as raised:
        reduce_event(state_with_matrix_node, conflicting_same_node_id_event)

    assert "node 'worker-1'" in str(raised.value)
    assert "stable field 'role'" in str(raised.value)
    assert "'event-2'" in str(raised.value)


@pytest.mark.parametrize("field", ("graph_position", "run_id"))
def test_record_payload_delivery_fields_are_part_of_immutable_identity(field: str) -> None:
    first = _fan_out_record()
    conflicting = first.model_copy(
        update={
            "event_id": "conflicting-record",
            "position": 1,
            "payload": {**first.payload, field: "other-run" if field == "run_id" else 7},
        }
    )

    with pytest.raises(ProjectionReplayConflictError, match=r"record.*record-1"):
        build_projection([first, conflicting])


def test_file_state_duplicate_compares_nested_values() -> None:
    first = _file_state(position=8)
    duplicate = _file_state(position=9)
    projection = build_projection([first, duplicate])

    assert (
        file_state_records_view(projection)["file-state-1"].model_dump(mode="json")["position"] == 8
    )

    conflicting = _file_state(
        position=9,
        tracked=[{"path": "src/other.py", "status": "modified"}],
    )
    with pytest.raises(ProjectionReplayConflictError, match=r"record.*file-state-1"):
        build_projection([first, conflicting])


@pytest.mark.parametrize(
    "enrichment",
    [_gatekeeper_verdict(position=9), _cleanup_requested(position=9)],
    ids=["gatekeeper-verdict", "cleanup"],
)
def test_file_state_duplicate_is_idempotent_after_derived_enrichment(
    enrichment: EventEnvelope,
) -> None:
    first = _file_state(position=8)
    duplicate = _file_state(position=10)
    enriched = build_projection([_node(position=7), first, enrichment])

    assert reduce_event(enriched, duplicate) is enriched

    restored = projection_from_checkpoint(projection_to_checkpoint(enriched))
    assert reduce_event(restored, duplicate) is restored


def test_paired_file_state_events_ignore_delivery_timestamps_for_replay_identity() -> None:
    payload = dict(_file_state(position=48).payload)
    output_accepted = _event(
        "output_record_accepted",
        {
            **payload,
            "created_at": "2026-01-01T00:00:00+00:00",
            "graph_position": 48,
            "run_id": "run-1",
        },
        position=48,
    )
    file_state_accepted = _event(
        "file_state_accepted",
        {
            **payload,
            "created_at": "2026-01-01T00:00:01+00:00",
            "graph_position": 49,
            "run_id": "run-1",
        },
        position=49,
    )

    state = build_projection([output_accepted, file_state_accepted])

    record = file_state_records_view(state)["file-state-1"]
    assert record is not None
    assert record.created_at == "2026-01-01T00:00:00+00:00"
    assert record.graph_position == 48
    assert record.position == 48
    assert record.run_id == "run-1"


def test_file_state_duplicate_from_a_different_run_conflicts() -> None:
    first = _file_state(position=48)
    different_run = first.model_copy(
        update={"event_id": "different-run", "position": 49, "run_id": "run-2"}
    )

    with pytest.raises(ProjectionReplayConflictError, match=r"record.*file-state-1"):
        build_projection([first, different_run])


def test_direct_file_state_insert_computes_identity_and_rejects_conflicting_missing_identity() -> (
    None
):
    record = ProjectedFileStateRecord(
        record_id="file-state-direct",
        record_type="file_state",
        producer_node_id="worker-1",
    )

    inserted = insert_projected_record(RecordStore(), record, event_id="accepted-1")
    accepted = inserted.by_id["file-state-direct"]

    assert isinstance(accepted, ProjectedFileStateRecord)
    assert accepted.acceptance_identity is not None
    assert len(accepted.acceptance_identity) == 64
    assert insert_projected_record(inserted, record, event_id="accepted-2") is inserted

    conflicting = ProjectedFileStateRecord(
        record_id="file-state-direct",
        record_type="file_state",
        producer_node_id="worker-1",
        tracked=[{"path": "src/other.py", "status": "modified"}],
    )
    with pytest.raises(ProjectionReplayConflictError, match=r"record.*file-state-direct"):
        insert_projected_record(inserted, conflicting, event_id="accepted-3")


@pytest.mark.parametrize(
    "enrichment",
    [_gatekeeper_verdict(position=9), _cleanup_requested(position=9)],
    ids=["gatekeeper-verdict", "cleanup"],
)
def test_file_state_conflicting_duplicate_fails_after_derived_enrichment(
    enrichment: EventEnvelope,
) -> None:
    first = _file_state(position=8)
    conflicting = _file_state(
        position=10,
        tracked=[{"path": "src/other.py", "status": "modified"}],
    )

    with pytest.raises(ProjectionReplayConflictError, match=r"record.*file-state-1"):
        build_projection([first, enrichment, conflicting])


def test_flexible_json_values_compare_by_json_semantics() -> None:
    first = _fan_out_record(value={"nested": {"items": [1, {"left": "a", "right": [True, None]}]}})
    same_json = _fan_out_record(
        value={"nested": {"items": [1, {"right": [True, None], "left": "a"}]}}
    )
    assert build_projection([first, same_json]) == build_projection([first])

    different_json = _fan_out_record(value={"nested": {"items": [1, {"left": "b"}]}})
    with pytest.raises(ProjectionReplayConflictError, match=r"record.*record-1"):
        build_projection([first, different_json])


def test_repeated_node_creation_preserves_runtime_state_and_first_position() -> None:
    projection = build_projection(
        [
            _node(position=5),
            _event(
                "node_state_changed",
                {"node_id": "worker-1", "new_state": "running"},
                position=6,
            ),
            _node(position=7),
        ]
    )

    assert node_states_view(projection)["worker-1"] == "running"
    assert node_creation_positions_view(projection)["worker-1"] == 5


def test_absent_stable_node_fields_may_be_filled_by_replay() -> None:
    projection = build_projection(
        [
            _node(position=1),
            _node(position=2, role="builder", task_region_id="task-1"),
        ]
    )

    assert node_roles_view(projection)["worker-1"] == "builder"
    assert node_task_regions_view(projection)["worker-1"] == "task-1"


@pytest.mark.parametrize(
    ("field", "later_value"),
    [
        ("allowed_actions", ["submit_callback"]),
        ("preconditions", ["inputs_bound"]),
        ("resource_claims", [{"paths": ["src/app.py"], "mode": "write", "scope": "repo"}]),
    ],
)
def test_omitted_node_collections_may_be_filled_by_replay(
    field: str, later_value: list[Any]
) -> None:
    projection = build_projection([_node(position=1), _node(position=2, **{field: later_value})])

    if field == "allowed_actions":
        assert projection.nodes["worker-1"].spec.allowed_actions == ("submit_callback",)
    elif field == "preconditions":
        assert projection.nodes["worker-1"].spec.preconditions == ("inputs_bound",)
    else:
        claims = node_resource_claims_view(projection)["worker-1"]
        assert [claim.model_dump(exclude_none=True) for claim in claims] == later_value


def test_planner_node_creation_installs_a_checkpoint_valid_detached_session() -> None:
    projection = build_projection(
        [
            _node(
                "planner-1",
                position=1,
                kind="planner",
                role="planner",
                session_id="session-1",
            )
        ]
    )

    restored = projection_from_checkpoint(projection_to_checkpoint(projection))

    assert restored.planning.sessions["session-1"].state == "detached"


@pytest.mark.parametrize(
    ("field", "later_value"),
    [
        ("kind", "verifier"),
        ("role", "verifier"),
        ("task_region_id", "task-2"),
    ],
)
def test_conflicting_stable_node_fields_fail_replay(field: str, later_value: str) -> None:
    first = _node(position=1, role="builder", task_region_id="task-1")
    second_fields = {"role": "builder", "task_region_id": "task-1", field: later_value}
    second = _node(position=2, **second_fields)

    with pytest.raises(ProjectionReplayConflictError, match=r"node.*worker-1"):
        build_projection([first, second])


@pytest.mark.parametrize(
    ("field", "later_value"),
    [
        ("allowed_actions", ["submit_callback"]),
        ("preconditions", ["inputs_bound"]),
        ("resource_claims", [{"paths": ["src/app.py"], "mode": "write", "scope": "repo"}]),
    ],
)
def test_explicit_empty_node_collections_are_present_and_conflict(
    field: str, later_value: list[Any]
) -> None:
    first = _node(position=1, **{field: []})
    second = _node(position=2, **{field: later_value})

    with pytest.raises(ProjectionReplayConflictError, match=r"node.*worker-1"):
        build_projection([first, second])


def test_first_non_null_max_attempts_wins_and_later_conflict_fails() -> None:
    first_non_null = build_projection([_node(position=1), _node(position=2, max_attempts=3)])
    assert project_node_max_attempts(first_non_null)["worker-1"] == 3

    with pytest.raises(ProjectionReplayConflictError, match=r"node.*worker-1"):
        build_projection(
            [
                _node(position=1),
                _node(position=2, max_attempts=3),
                _node(position=3, max_attempts=7),
            ]
        )


@pytest.mark.parametrize(
    "moved",
    [
        _fan_out_record(producer_node_id="worker-2"),
        _analysis_record(producer_node_id="worker-1", port="planning_summary"),
    ],
    ids=["node", "port"],
)
def test_record_id_cannot_move_node_or_port_and_original_index_remains_single(
    moved: EventEnvelope,
) -> None:
    first = _fan_out_record(record_id="record-1")
    projection = reduce_event(initial_projection(), first)

    with pytest.raises(ProjectionReplayConflictError, match=r"record.*record-1"):
        reduce_event(projection, moved)

    assert tuple(
        item["record_id"]
        for item in accepted_output_records_by_node_port_view(projection)["worker-1"]["candidate"]
    ) == ("record-1",)


def test_identical_duplicates_do_not_duplicate_topology_task_ready_or_decision_indexes() -> None:
    source = _node("source", position=0, outputs=[{"port": "candidate", "direction": "output"}])
    target = _node("target", position=1)
    edge_payload = {
        "edge_id": "edge-1",
        "from_node_id": "source",
        "from_port": "candidate",
        "to_node_id": "target",
        "to_port": "input",
        "required": True,
    }
    candidate = _candidate_record(position=4)
    ready = _event("node_ready", {"node_id": "source"}, position=7)
    decision_payload = {
        "node_id": "gate-1",
        "decision": "approved",
        "decision_type": "approval",
        "decider": "fixture-controller",
    }
    events = [
        source,
        target,
        _event("edge_created", edge_payload, position=2),
        _event("edge_created", edge_payload, position=3),
        candidate,
        candidate.model_copy(update={"position": 5, "event_id": "candidate-retry"}),
        _event(
            "node_state_changed",
            {"node_id": "source", "new_state": "ready"},
            position=6,
        ),
        ready,
        ready.model_copy(update={"position": 8, "event_id": "ready-retry"}),
        _event("approval_decision_recorded", decision_payload, position=9),
        _event("approval_decision_recorded", decision_payload, position=10),
    ]

    projection = build_projection(events)

    assert list(edges_view(projection)) == ["edge-1"]
    assert [item.candidate_id for item in task_candidates_view(projection)["task-1"]] == [
        "candidate-1"
    ]
    assert ready_nodes_view(projection) == ["source"]
    assert list(projection.governance.approval_decision_id_by_node) == ["gate-1"]
    assert [
        item["record_id"]
        for item in accepted_output_records_by_node_port_view(projection)["worker-1"]["candidate"]
    ] == ["candidate-1"]


def test_node_ready_does_not_replace_authoritative_runtime_state() -> None:
    projection = build_projection(
        [_node(position=1), _event("node_ready", {"node_id": "worker-1"}, position=2)]
    )

    assert node_states_view(projection)["worker-1"] == "planned"
    assert ready_nodes_view(projection) == []


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (
            "approval_decision_recorded",
            {
                "record_id": "decision-1",
                "decision_type": "approval",
                "node_id": "gate-1",
                "appeal_node_id": "appeal-1",
                "decision": "approved",
                "decider": "controller",
            },
        ),
        (
            "authority_decision_recorded",
            {
                "record_id": "decision-1",
                "decision_type": "authority",
                "node_id": "authority-1",
                "appeal_node_id": "appeal-1",
                "decision": "granted",
                "decider": "controller",
            },
        ),
        (
            "oversight_decision_recorded",
            {
                "record_id": "decision-1",
                "decision_type": "oversight",
                "node_id": "oversight-1",
                "appeal_node_id": "appeal-1",
                "decision": "accepted",
                "decider": {"kind": "human", "id": "reviewer-1"},
            },
        ),
    ],
    ids=["approval", "authority", "oversight"],
)
def test_identical_explicit_decision_id_redelivery_preserves_canonical_value_and_aliases(
    event_type: str,
    payload: dict[str, Any],
) -> None:
    first = _event(event_type, payload, position=3, event_id="original")
    once = reduce_event(initial_projection(), first)
    decisions = _governance_decision_values(once, event_type)

    replayed = reduce_event(
        once,
        first.model_copy(update={"position": 9, "event_id": "redelivery"}),
    )

    assert replayed is once
    assert _governance_decision_values(replayed, event_type) == decisions
    assert set(decisions) == {payload["node_id"], "appeal-1"}
    if event_type == "oversight_decision_recorded":
        assert decisions[payload["node_id"]].position == 3


@pytest.mark.parametrize(
    ("event_type", "payload", "conflicting_decision"),
    [
        (
            "approval_decision_recorded",
            {
                "record_id": "decision-1",
                "decision_type": "approval",
                "node_id": "gate-1",
                "decision": "approved",
                "decider": "controller",
            },
            "deferred",
        ),
        (
            "authority_decision_recorded",
            {
                "record_id": "decision-1",
                "decision_type": "authority",
                "node_id": "authority-1",
                "decision": "granted",
                "decider": "controller",
            },
            "deferred",
        ),
        (
            "oversight_decision_recorded",
            {
                "record_id": "decision-1",
                "decision_type": "oversight",
                "node_id": "oversight-1",
                "decision": "accepted",
                "decider": "controller",
            },
            "rejected",
        ),
    ],
    ids=["approval", "authority", "oversight"],
)
def test_conflicting_explicit_decision_id_fails_before_canonical_alias_or_side_index_changes(
    event_type: str,
    payload: dict[str, Any],
    conflicting_decision: str,
) -> None:
    first = _event(event_type, payload, position=3, event_id="original")
    state = reduce_event(initial_projection(), first)
    decisions = _governance_decision_values(state, event_type)
    conflicting = _event(
        event_type,
        {**payload, "node_id": "different-node", "decision": conflicting_decision},
        position=4,
        event_id="conflicting-redelivery",
    )

    with pytest.raises(
        ProjectionReplayConflictError,
        match=rf"{event_type.replace('_decision_recorded', '')} decision.*decision-1.*event",
    ):
        reduce_event(state, conflicting)

    assert _governance_decision_values(state, event_type) == decisions
    assert decisions[payload["node_id"]].node_id == payload["node_id"]
    assert "different-node" not in decisions
