"""Strict callback, patch, and runtime command payload coverage."""

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    AcknowledgeStartCommand,
    AgentDiedCommand,
    PatchCommandContext,
    SubmitCallbackCommand,
    SubmitPatchCommand,
)
from orchestrator.graph import GraphCommandContext, initial_projection
from orchestrator.graph import FakeClock, SequentialIdGenerator
from tests.unit.graph_test_utils import apply_command


def _callback_payload() -> dict[str, object]:
    return {
        "node_id": "worker-1",
        "execution_id": "exec-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "base_snapshot_id": "S0",
        "observed_graph_position": 4,
        "idempotency_key": "callback-1",
        "payload_hash": "hash-1",
    }


def test_callback_requires_payload_or_payload_hash() -> None:
    payload = _callback_payload()
    payload.pop("payload_hash")

    with pytest.raises(ValidationError, match="payload or payload_hash"):
        SubmitCallbackCommand.model_validate(payload)


@pytest.mark.parametrize("payload_hash", ["", "   "])
def test_callback_rejects_blank_payload_hash_without_payload(payload_hash: str) -> None:
    with pytest.raises(ValidationError):
        SubmitCallbackCommand.model_validate({**_callback_payload(), "payload_hash": payload_hash})


@pytest.mark.parametrize("field", ["node_id", "execution_id", "lease_id", "base_snapshot_id"])
def test_callback_requires_identity_fields(field: str) -> None:
    payload = _callback_payload()
    payload.pop(field)

    with pytest.raises(ValidationError):
        SubmitCallbackCommand.model_validate(payload)


def test_callback_rejects_scalar_payload() -> None:
    with pytest.raises(ValidationError):
        SubmitCallbackCommand.model_validate({**_callback_payload(), "payload": "scalar"})


@pytest.mark.parametrize("value", [True, "1"])
def test_callback_rejects_coerced_lease_generation(value: object) -> None:
    with pytest.raises(ValidationError):
        SubmitCallbackCommand.model_validate({**_callback_payload(), "lease_generation": value})


def test_patch_context_owns_proposer_provenance() -> None:
    context = PatchCommandContext(
        run_id="run-1",
        current_graph_position=4,
        proposed_by_node_id="planner-1",
        actor_role="planner",
    )

    assert context.proposed_by_node_id == "planner-1"
    assert context.actor_role == "planner"


@pytest.mark.parametrize(
    "field",
    [
        "run_id",
        "_current_graph_position",
        "proposed_by_node_id",
        "actor_role",
        "lease_id",
        "lease_generation",
        "execution_id",
        "base_snapshot_id",
        "observed_graph_position",
        "idempotency_key",
    ],
)
def test_patch_rejects_context_and_ignored_runtime_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        SubmitPatchCommand.model_validate(
            {"patch_id": "patch-1", "base_graph_position": 4, field: "unexpected"}
        )


@pytest.mark.parametrize("alias", ["name", "tool"])
def test_patch_macro_rejects_name_and_tool_aliases(alias: str) -> None:
    with pytest.raises(ValidationError):
        SubmitPatchCommand.model_validate(
            {
                "patch_id": "patch-1",
                "base_graph_position": 4,
                "macro_invocations": [{alias: "create_work_region", "args": {}}],
            }
        )


def test_patch_rejects_carryover_summary_alias() -> None:
    with pytest.raises(ValidationError):
        SubmitPatchCommand.model_validate(
            {
                "patch_id": "patch-1",
                "base_graph_position": 4,
                "carryover_summary": "summary-1",
            }
        )


def test_runtime_commands_require_canonical_identity_fields() -> None:
    with pytest.raises(ValidationError):
        AcknowledgeStartCommand.model_validate({"node_id": "worker-1"})
    with pytest.raises(ValidationError):
        AgentDiedCommand.model_validate({})


@pytest.mark.parametrize(
    ("command_type", "field", "value"),
    [
        ("complete", "run_id", "smuggled-run"),
        ("complete", "_current_graph_position", 9),
        ("complete", "actor_role", "operator"),
        ("submit_patch", "proposed_by_node_id", "smuggled-planner"),
    ],
)
def test_shared_command_boundary_rejects_payload_smuggled_context(
    command_type: str,
    field: str,
    value: object,
) -> None:
    context: GraphCommandContext
    if command_type == "submit_patch":
        context = PatchCommandContext(
            run_id="run-1",
            current_graph_position=-1,
            proposed_by_node_id="planner-1",
            actor_role="planner",
        )
        payload: dict[str, object] = {
            "patch_id": "patch-1",
            "base_graph_position": -1,
            field: value,
        }
    else:
        context = GraphCommandContext(run_id="run-1", current_graph_position=-1)
        payload = {field: value}

    emitted = apply_command(
        initial_projection(),
        [],
        command_type,
        payload,
        context,
        FakeClock(),
        SequentialIdGenerator(),
    )

    assert [event.event_type for event in emitted] == ["command_rejected"]
    assert "invalid command payload" in emitted[0].payload["reason"]
