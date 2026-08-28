from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator.artifacts import FilesystemArtifactStore
from orchestrator.config import RoutineConfig, SemanticArtifactSchemaConfig, StepConfig, TaskConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    RELIABLE_PLAN_INCIDENT_ID,
    FakeClock,
    SequentialIdGenerator,
    thaw_json,
)
from orchestrator.graph_runtime import GraphController, seed_run


pytestmark = pytest.mark.slow


@pytest.mark.asyncio
async def test_controller_resolves_semantic_artifact_reference_before_acceptance(
    tmp_path: Path,
) -> None:
    """A worker cannot forge validation evidence for absent or invalid bytes."""
    routine = RoutineConfig(
        id="semantic-controller",
        name="Semantic controller",
        semantic_artifact_schemas=[
            SemanticArtifactSchemaConfig(
                schema_id="plan",
                version=1,
                semantic_role="implementation_plan",
                json_schema={
                    "type": "object",
                    "required": ["mode", "batches"],
                    "properties": {
                        "mode": {"enum": ["relaxed", "strict"]},
                        "batches": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "required": ["batch_id", "selector"],
                                "properties": {
                                    "batch_id": {
                                        "type": "string",
                                        "minLength": 7,
                                        "pattern": "^batch-[0-9]+$",
                                    },
                                    "selector": {
                                        "type": "object",
                                        "properties": {
                                            "path": {"type": "string"},
                                            "query": {"type": "string"},
                                        },
                                        "oneOf": [
                                            {"required": ["path"]},
                                            {"required": ["query"]},
                                        ],
                                        "additionalProperties": False,
                                    },
                                },
                                "additionalProperties": False,
                            },
                        },
                    },
                    "allOf": [
                        {
                            "if": {"properties": {"mode": {"const": "strict"}}},
                            "then": {"properties": {"batches": {"minItems": 2}}},
                        }
                    ],
                    "additionalProperties": False,
                },
            )
        ],
        steps=[StepConfig(id="S1", title="Work", tasks=[TaskConfig(id="T1", title="Do")])],
    )
    engine = create_engine(tmp_path / "semantic-controller.db")
    await init_db(engine)
    sessions = create_session_factory(engine)
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    clock = FakeClock()
    ids = SequentialIdGenerator()
    controller = GraphController(
        sessions,
        clock,
        ids,
        auto_dispatch=False,
        artifact_store=store,
    )
    # Durable product-path reproduction for the incident-informed skeleton.
    run_id = RELIABLE_PLAN_INCIDENT_ID
    try:
        seeded = await seed_run(sessions, routine, run_id=run_id, clock=clock, id_gen=ids)
        accepted = await controller.handle_command(run_id, seeded.projection_position, "accept_run")
        started = await controller.handle_command(run_id, accepted.projection_position, "start")
        scheduled = await controller.handle_command(
            run_id,
            started.projection_position,
            "schedule_tick",
            {"max_grants": 1, "lease_seconds": 60},
        )
        lease = next(event for event in scheduled.events if event.event_type == "lease_granted")
        node_id = str(lease.payload["node_id"])
        acknowledged = await controller.handle_command(
            run_id,
            scheduled.projection_position,
            "acknowledge_start",
            {
                "node_id": node_id,
                "lease_id": lease.payload["lease_id"],
                "lease_generation": lease.payload["generation"],
                "execution_id": lease.payload["execution_id"],
            },
        )

        missing_digest = "sha256:" + "0" * 64
        forged = _semantic_callback(
            node_id,
            lease.payload,
            acknowledged.projection_position,
            record_id="missing-plan",
            artifact_ref={
                "artifact_id": missing_digest,
                "content_hash": missing_digest,
                "size_bytes": 2,
                "media_type": "application/json",
                "encoding": "utf-8",
                "storage_uri": "artifact://sha256/" + "0" * 64,
            },
            artifact_validation={
                "declaration_record_id": "semantic-schema-plan-v1",
                "content_hash": missing_digest,
                "validated_json": {"batches": []},
            },
        )
        rejected = await controller.handle_command(
            run_id,
            acknowledged.projection_position,
            "submit_callback",
            forged,
        )
        assert any(event.event_type == "callback_rejected_conflict" for event in rejected.events)
        assert "missing-plan" not in (await controller.read_projection(run_id)).records.by_id

        position = rejected.projection_position
        invalid_documents = {
            "min-length": {
                "mode": "relaxed",
                "batches": [{"batch_id": "x", "selector": {"path": "src"}}],
            },
            "pattern": {
                "mode": "relaxed",
                "batches": [{"batch_id": "xxxxxxx", "selector": {"path": "src"}}],
            },
            "object": {
                "mode": "relaxed",
                "batches": [{"batch_id": "batch-1", "selector": {"path": "src"}, "extra": True}],
            },
            "array": {"mode": "relaxed", "batches": []},
            "composition": {
                "mode": "relaxed",
                "batches": [
                    {
                        "batch_id": "batch-1",
                        "selector": {"path": "src", "query": "tests"},
                    }
                ],
            },
            "conditional": {
                "mode": "strict",
                "batches": [{"batch_id": "batch-1", "selector": {"path": "src"}}],
            },
        }
        for case, document in invalid_documents.items():
            invalid_ref = await store.put(
                json.dumps(document).encode(),
                media_type="application/json",
                encoding="utf-8",
            )
            invalid = _semantic_callback(
                node_id,
                lease.payload,
                position,
                record_id=f"invalid-{case}",
                artifact_ref=invalid_ref.model_dump(mode="json"),
            )
            invalid_result = await controller.handle_command(
                run_id,
                position,
                "submit_callback",
                invalid,
            )
            assert any(
                event.event_type == "callback_rejected_conflict" for event in invalid_result.events
            ), case
            position = invalid_result.projection_position

        stored_ref = await store.put(
            json.dumps(
                {
                    "mode": "relaxed",
                    "batches": [{"batch_id": "batch-1", "selector": {"path": "src"}}],
                }
            ).encode(),
            media_type="application/json",
            encoding="utf-8",
        )
        valid = _semantic_callback(
            node_id,
            lease.payload,
            position,
            record_id="resolved-plan",
            artifact_ref=stored_ref.model_dump(mode="json"),
        )
        result = await controller.handle_command(
            run_id,
            position,
            "submit_callback",
            valid,
        )
        assert any(event.event_type == "callback_accepted" for event in result.events), [
            (event.event_type, event.payload.get("reason")) for event in result.events
        ]
        record = (await controller.read_projection(run_id)).records.by_id["resolved-plan"]
        assert record.value.artifact_validation.declaration_record_id == "semantic-schema-plan-v1"
        assert thaw_json(record.value.artifact_validation.validated_json) == {
            "mode": "relaxed",
            "batches": [{"batch_id": "batch-1", "selector": {"path": "src"}}],
        }
    finally:
        await engine.dispose()


def _semantic_callback(
    node_id: str,
    lease: dict[str, object],
    position: int,
    *,
    record_id: str,
    artifact_ref: dict[str, object],
    artifact_validation: dict[str, object] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "semantic_role": "implementation_plan",
        "schema_id": "plan",
        "schema_version": 1,
        "artifact_ref": artifact_ref,
        "provenance": {"source": "worker"},
        "authority_status": "accepted",
    }
    if artifact_validation is not None:
        value["artifact_validation"] = artifact_validation
    return {
        "node_id": node_id,
        "execution_id": lease["execution_id"],
        "lease_id": lease["lease_id"],
        "lease_generation": lease["generation"],
        "base_snapshot_id": lease["base_snapshot_id"],
        "observed_graph_position": position,
        "idempotency_key": f"callback-{record_id}",
        "payload_hash": f"hash-{record_id}",
        "payload": {
            "output_records": [
                {
                    "record_id": record_id,
                    "record_kind": "graph_record",
                    "record_type": "semantic_artifact",
                    "schema_version": 1,
                    "producer_node_id": node_id,
                    "producer_port": "semantic_artifact",
                    "port": "semantic_artifact",
                    "schema": "SemanticArtifact",
                    "value": value,
                }
            ]
        },
        "complete_node": False,
    }
