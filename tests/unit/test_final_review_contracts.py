"""Regression coverage for the final typed-payload review."""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from orchestrator.graph import (
    run_state,
    AppealOpenedPayload,
    CallbackAcceptedPayload,
    CallbackDuplicateReturnedPayload,
    CallbackRejectedPayload,
    CommandRejectedPayload,
    DeadInputDetectedPayload,
    EdgeProjection,
    FakeClock,
    HeartbeatRecordedPayload,
    NodeDeferredPayload,
    NodeReadyPayload,
    NodeRetiredPayload,
    NodeStateChangedPayload,
    RunLifecycleChangedPayload,
    RuntimeRetryScheduledPayload,
    SequentialIdGenerator,
    StoredArtifactRef,
    build_projection,
    initial_projection,
)
from orchestrator.graph.command_models import GraphCommandContext
from orchestrator.graph.commands import COMMAND_SPECS, apply_command, serialize_event_payload
from tests.unit.graph_test_utils import event


def test_modeled_event_serialization_uses_canonical_model_dump() -> None:
    serialized = serialize_event_payload(
        "cleanup_requested",
        {"cleanup_id": "cleanup-1", "paths": ("build/output.txt",)},
    )

    assert serialized["paths"] == ["build/output.txt"]
    assert isinstance(serialized["paths"], list)


def test_semantic_boolean_rejects_coercion_before_reduction() -> None:
    with pytest.raises(ValidationError):
        serialize_event_payload(
            "edge_created",
            {
                "edge_id": "edge-1",
                "from_node_id": "worker-1",
                "from_port": "candidate",
                "to_node_id": "verifier-1",
                "to_port": "candidate_under_test",
                "required": "false",
            },
        )


@pytest.mark.parametrize(
    ("model", "payload", "missing_field"),
    [
        (
            RunLifecycleChangedPayload,
            {
                "command_type": "start",
                "from_state": "queued",
                "to_state": "active",
                "trigger": "start_command_accepted",
            },
            "to_state",
        ),
        (CommandRejectedPayload, {"command_type": "start", "reason": "invalid"}, "reason"),
        (
            CallbackAcceptedPayload,
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "execution_id": "exec-1",
                "idempotency_key": "callback-1",
                "payload": None,
                "reason": "accepted",
            },
            "idempotency_key",
        ),
        (
            CallbackRejectedPayload,
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "execution_id": "exec-1",
                "idempotency_key": "callback-1",
                "payload": None,
                "reason": "stale",
            },
            "reason",
        ),
        (
            CallbackDuplicateReturnedPayload,
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "lease_generation": 1,
                "execution_id": "exec-1",
                "idempotency_key": "callback-1",
                "payload": None,
                "reason": "duplicate",
                "prior_result": None,
            },
            "prior_result",
        ),
        (
            RuntimeRetryScheduledPayload,
            {
                "node_id": "worker-1",
                "lease_id": "lease-1",
                "generation": 1,
                "policy": "v1_requeue_same_node_after_agent_death",
                "reason": "process_exit",
            },
            "policy",
        ),
        (
            HeartbeatRecordedPayload,
            {
                "lease_id": "lease-1",
                "node_id": "worker-1",
                "observed_at": "2026-07-16T12:00:00+00:00",
                "expires_at": "2026-07-16T12:05:00+00:00",
            },
            "observed_at",
        ),
        (
            DeadInputDetectedPayload,
            {
                "node_id": "verifier-1",
                "from_node_id": "worker-1",
                "to_port": "candidate_under_test",
                "reason": "upstream_failed:worker-1",
            },
            "from_node_id",
        ),
        (
            AppealOpenedPayload,
            {
                "node_id": "appeal-1",
                "appealed_node_id": "verifier-1",
                "appeal_type": "invalid_test",
            },
            "appealed_node_id",
        ),
        (
            NodeStateChangedPayload,
            {"node_id": "worker-1", "new_state": "ready", "trigger": "scheduler"},
            "new_state",
        ),
        (NodeRetiredPayload, {"node_id": "worker-1", "reason": "superseded"}, "node_id"),
        (NodeReadyPayload, {"node_id": "worker-1"}, "node_id"),
        (
            NodeDeferredPayload,
            {"node_id": "worker-1", "reason": "waiting"},
            "reason",
        ),
    ],
)
def test_event_models_reject_missing_reducer_or_transition_identity(
    model: type[BaseModel], payload: dict[str, Any], missing_field: str
) -> None:
    incomplete = dict(payload)
    incomplete.pop(missing_field)

    with pytest.raises(ValidationError):
        model.model_validate(incomplete)


COMMAND_EXAMPLES: dict[str, dict[str, Any]] = {
    "accept_run": {},
    "start": {},
    "pause": {},
    "resume": {},
    "cancel": {},
    "complete": {},
    "fail": {},
    "record_heartbeat": {"lease_id": "lease-1"},
    "seed_compiled_events": {
        "events": [
            event(
                "node_created",
                {"node_id": "worker-1", "kind": "worker", "state": "planned"},
            )
        ]
    },
    "schedule_tick": {},
    "reconcile": {},
    "submit_callback": {
        "node_id": "worker-1",
        "execution_id": "exec-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "base_snapshot_id": "snapshot-1",
        "observed_graph_position": 1,
        "idempotency_key": "callback-1",
        "payload_hash": "sha256:abc",
    },
    "submit_patch": {"patch_id": "patch-1", "base_graph_position": 1},
    "acknowledge_start": {
        "node_id": "worker-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "execution_id": "exec-1",
    },
    "agent_died": {"lease_id": "lease-1"},
    "raise_appeal": {"node_id": "verifier-1", "appeal_type": "invalid_test"},
    "record_decision": {
        "decision_type": "approval",
        "node_id": "gate-1",
        "decision": "approved",
        "decider": "operator",
    },
    "record_gatekeeper_verdicts": {
        "file_state_record_id": "file-state-1",
        "execution_id": "exec-1",
        "verdicts": [{"path": "build/output", "classification": "build_output"}],
    },
    "record_node_usage": {
        "node_id": "worker-1",
        "node_kind": "worker",
        "execution_id": "exec-1",
        "usage": [{"model": "model-1"}],
    },
    "record_requirement_revision": {"requirement_id": "R1", "version_id": "R1-v2"},
    "record_support_evidence": {
        "support_id": "support-1",
        "evidence_id": "evidence-1",
        "requirement_id": "R1",
    },
    "evaluate_join": {"node_id": "join-1"},
    "evaluate_final_gate": {"node_id": "final-gate-1"},
    "record_cleanup_applied": {
        "cleanup_id": "cleanup-1",
        "superseding_file_state_record": {
            "record_id": "file-state-2",
            "record_kind": "file_state",
            "record_type": "file_state",
            "producer_node_id": "worker-1",
            "port": "file_state",
            "schema": "FileState",
            "snapshot_id": "snapshot-2",
        },
    },
}

IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "complete": ("completion_decision_record_id", "node_id"),
    "record_heartbeat": ("lease_id", "node_id"),
    "schedule_tick": ("base_snapshot_id",),
    "submit_callback": (
        "node_id",
        "execution_id",
        "lease_id",
        "base_snapshot_id",
        "idempotency_key",
        "payload_hash",
    ),
    "submit_patch": (
        "patch_id",
        "rationale_record_id",
        "budget_gate_node_id",
        "carryover_record_id",
    ),
    "acknowledge_start": ("node_id", "lease_id", "execution_id"),
    "agent_died": ("lease_id", "execution_id"),
    "raise_appeal": (
        "node_id",
        "appeal_node_id",
        "oversight_node_id",
        "candidate_id",
        "task_region_id",
        "lease_id",
    ),
    "record_decision": ("node_id", "decider", "record_id"),
    "record_gatekeeper_verdicts": ("file_state_record_id", "execution_id", "consult_id"),
    "record_node_usage": ("node_id", "node_kind", "execution_id"),
    "record_requirement_revision": (
        "requirement_id",
        "version_id",
        "previous_version_id",
        "revision_id",
        "proposal_id",
        "patch_id",
        "node_id",
    ),
    "record_support_evidence": (
        "support_id",
        "evidence_id",
        "requirement_id",
        "requirement_version_id",
    ),
    "evaluate_join": ("node_id", "record_id", "lease_id"),
    "evaluate_final_gate": ("node_id", "record_id", "lease_id"),
    "record_cleanup_applied": ("cleanup_id",),
}


def test_identity_matrix_covers_all_command_specs_and_rejects_blank_values() -> None:
    assert set(COMMAND_EXAMPLES) == set(COMMAND_SPECS)
    assert set(IDENTITY_FIELDS) <= set(COMMAND_SPECS)

    for command_type, fields in IDENTITY_FIELDS.items():
        model = COMMAND_SPECS[command_type].payload_model
        for field in fields:
            baseline = deepcopy(COMMAND_EXAMPLES[command_type])
            baseline.setdefault(field, f"valid-{field}")
            if field == "lease_id" and command_type in {"evaluate_join", "evaluate_final_gate"}:
                baseline["lease_generation"] = 1
            model.model_validate(baseline)
            for blank in ("", "   "):
                invalid = {**baseline, field: blank}
                with pytest.raises(ValidationError):
                    model.model_validate(invalid)


def test_command_validation_error_redacts_unknown_secret_key_and_value() -> None:
    secret_key = "sk_top_level_secret_key"
    secret_value = "sk-super-secret-value"
    emitted = apply_command(
        initial_projection(),
        [],
        "start",
        {secret_key: secret_value},
        GraphCommandContext(run_id="run-1", current_graph_position=-1),
        FakeClock(),
        SequentialIdGenerator(),
    )

    reason = emitted[0].payload["reason"]
    assert secret_key not in reason
    assert secret_value not in reason
    assert "invalid_command_payload" in reason
    assert "payload [extra_forbidden]" in reason
    assert "extra_forbidden" in reason
    assert len(reason) <= 1_000


def test_stored_artifact_ref_rejects_mismatched_uri_digest() -> None:
    with pytest.raises(ValidationError, match="digest"):
        StoredArtifactRef.model_validate(
            {
                "artifact_id": "artifact-1",
                "content_hash": f"sha256:{'a' * 64}",
                "size_bytes": 12,
                "media_type": "text/plain",
                "storage_uri": f"artifact://sha256/{'b' * 64}",
            }
        )


def test_canonical_lifecycle_serialization_preserves_reducer_semantics() -> None:
    serialized = serialize_event_payload(
        "run_lifecycle_changed",
        {
            "command_type": "start",
            "from_state": "queued",
            "to_state": "active",
            "trigger": "start_command_accepted",
        },
    )
    projection = build_projection([event("run_lifecycle_changed", serialized)])

    assert serialized == {
        "command_type": "start",
        "from_state": "queued",
        "to_state": "active",
        "trigger": "start_command_accepted",
    }
    assert run_state(projection) == "active"
    assert (
        EdgeProjection.model_validate(
            {
                "edge_id": "edge-1",
                "from_node_id": "a",
                "from_port": "out",
                "to_node_id": "b",
                "to_port": "in",
                "required": False,
            }
        ).required
        is False
    )
