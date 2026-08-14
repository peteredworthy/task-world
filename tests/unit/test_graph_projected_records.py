"""Canonical accepted-record ownership contracts."""

from copy import deepcopy
from typing import Any

from pydantic import BaseModel
import pytest

from orchestrator.graph import (
    FileStateRecord,
    FrozenMap,
    OutputRecordAcceptedPayload,
    OUTPUT_RECORD_MODELS_BY_TYPE,
    RecordStore,
    file_state_records_view,
    initial_projection,
    insert_record,
    projection_from_checkpoint,
    projection_to_checkpoint,
    freeze_canonical_record,
)
from tests.unit.test_output_record_event_payloads import OUTPUT_RECORD_CASES


def _assert_deeply_immutable(value: object) -> None:
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            if hasattr(value, field_name):
                _assert_deeply_immutable(getattr(value, field_name))
        return
    if isinstance(value, FrozenMap):
        for key, item in value.items():
            assert type(key) is str
            _assert_deeply_immutable(item)
        return
    if isinstance(value, dict):
        with pytest.raises(TypeError):
            value["__mutation__"] = True
        for item in value.values():
            _assert_deeply_immutable(item)
        return
    if isinstance(value, tuple):
        for item in value:
            _assert_deeply_immutable(item)
        return
    assert type(value) in {type(None), bool, int, float, str}


def test_accepted_record_models_are_the_canonical_record_contracts() -> None:
    assert set(OUTPUT_RECORD_MODELS_BY_TYPE) == {
        "analysis_summary",
        "artifact_reference",
        "authority_decision",
        "authority_request_record",
        "candidate",
        "check_result",
        "classified_gap",
        "completion_decision",
        "decision_record",
        "decision_request",
        "failure_record",
        "fan_out_inputs",
        "file_state",
        "gap_classification",
        "gap_plan",
        "graph_patch_proposal",
        "join_result",
        "recovery_plan",
        "requirement_record",
        "routine_snapshot",
        "run_context",
        "verification_report",
    }
    for record_type, payload in OUTPUT_RECORD_CASES.items():
        record = (
            FileStateRecord.model_validate(deepcopy(payload))
            if record_type == "file_state"
            else OutputRecordAcceptedPayload.model_validate(deepcopy(payload)).root
        )
        freeze_canonical_record(record)
        assert type(record) is OUTPUT_RECORD_MODELS_BY_TYPE[record_type]
        _assert_deeply_immutable(record)


def test_canonical_records_are_retained_without_projection_conversion() -> None:
    payload = deepcopy(OUTPUT_RECORD_CASES["candidate"])
    record = OutputRecordAcceptedPayload.model_validate(payload).root
    store = insert_record(RecordStore(), record, event_id="accepted-1")

    retained = store.by_id[record.record_id]
    assert retained is record
    assert type(retained).__name__ == "CandidateRecord"
    assert store.ids_by_node_port[record.producer_node_id][record.port] == (record.record_id,)


def test_canonical_file_state_round_trips_through_disposable_checkpoint() -> None:
    payload: dict[str, Any] = {
        "record_id": "file-state-1",
        "record_type": "file_state",
        "record_kind": "file_state",
        "producer_node_id": "worker-1",
        "port": "file_state",
        "schema": "FileStateRecord",
        "paths": [{"path": "src/app.py", "source": "tracked", "status": "modified"}],
    }
    record = FileStateRecord.model_validate(payload)
    projection = initial_projection().model_copy(
        update={"records": insert_record(RecordStore(), record, event_id="accepted-file-state")}
    )
    restored = projection_from_checkpoint(projection_to_checkpoint(projection, position=4))

    restored_record = file_state_records_view(restored)[record.record_id]
    assert isinstance(restored_record, FileStateRecord)
    restored_dump = restored_record.model_dump(mode="json", by_alias=True)
    original_dump = record.model_dump(mode="json", by_alias=True)
    restored_dump.pop("acceptance_identity", None)
    assert restored_dump == original_dump
    _assert_deeply_immutable(restored.records.by_id[record.record_id])


def test_output_record_acceptance_wrapper_exposes_the_canonical_root() -> None:
    payload = deepcopy(OUTPUT_RECORD_CASES["fan_out_inputs"])
    accepted = OutputRecordAcceptedPayload.model_validate(payload)
    assert accepted.root.record_type == "fan_out_inputs"
    assert accepted.model_dump(mode="json")["record_type"] == "fan_out_inputs"
