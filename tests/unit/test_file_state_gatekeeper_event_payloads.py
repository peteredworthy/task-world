from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FileStateAcceptedPayload,
    FileStateRejectedPayload,
    GatekeeperCostRecordedPayload,
    GatekeeperVerdictRecordedPayload,
    project_gatekeeper_report,
)
from orchestrator.graph_runtime import GraphEventStore


CANONICAL_FILE_STATE = {
    "record_id": "file-state-1",
    "record_kind": "file_state",
    "record_type": "file_state",
    "producer_node_id": "worker-1",
    "port": "file_state",
    "schema": "FileStateRecord",
    "snapshot_id": "snapshot-1",
}


def test_file_state_accepted_preserves_flat_record_shape() -> None:
    payload = FileStateAcceptedPayload.model_validate(CANONICAL_FILE_STATE)

    assert payload.model_dump(mode="json") == CANONICAL_FILE_STATE


@pytest.mark.parametrize("record_type", [None, "candidate"])
def test_file_state_accepted_requires_exact_record_type(record_type: str | None) -> None:
    payload = dict(CANONICAL_FILE_STATE)
    if record_type is None:
        payload.pop("record_type")
    else:
        payload["record_type"] = record_type

    with pytest.raises(ValidationError):
        FileStateAcceptedPayload.model_validate(payload)


def test_file_state_rejected_accepts_only_canonical_record_fields_and_reason() -> None:
    payload = FileStateRejectedPayload.model_validate({**CANONICAL_FILE_STATE, "reason": "denied"})

    assert payload.reason == "denied"


def test_gatekeeper_cost_rejects_unknown_and_negative_values() -> None:
    with pytest.raises(ValidationError):
        GatekeeperCostRecordedPayload.model_validate(
            {"execution_id": "e-1", "input_tokens": -1, "legacy_cost": 1}
        )


def test_gatekeeper_verdict_requires_nonempty_rows() -> None:
    with pytest.raises(ValidationError):
        GatekeeperVerdictRecordedPayload.model_validate(
            {
                "file_state_record_id": "file-state-1",
                "execution_id": "exec-1",
                "producer_node_id": "worker-1",
                "verdicts": [],
                "resolved_count": 0,
            }
        )


@pytest.mark.asyncio
async def test_gatekeeper_cost_fields_survive_summary_reconstruction() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    payload = {
        "execution_id": "exec-1",
        "file_state_record_id": "file-state-1",
        "consult_id": "consult-1",
        "model_id": "model-1",
        "input_tokens": 11,
        "output_tokens": 7,
        "cache_read_tokens": 5,
        "cache_write_tokens": 3,
        "item_count": 2,
        "cost_usd": 0.125,
        "wall_time_ms": 19,
    }
    event = EventEnvelope(
        event_id="event-1",
        run_id="run-1",
        position=-1,
        event_type="gatekeeper_cost_recorded",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload=payload,
    )
    try:
        async with session_factory() as session:
            await GraphEventStore(session).append_events("run-1", 0, [event])
            compact = await GraphEventStore(session).read_run_summary_rebuild("run-1")

        GatekeeperCostRecordedPayload.model_validate(compact[0].payload)
        assert project_gatekeeper_report(compact) == project_gatekeeper_report(
            [event.model_copy(update={"position": 1})]
        )
    finally:
        await engine.dispose()
