import pytest
from pydantic import ValidationError

from orchestrator.config import RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import (
    FakeClock,
    NodeCreatedPayload,
    SequentialIdGenerator,
    build_projection,
    compile_routine,
    projection_to_checkpoint,
)
from orchestrator.graph_runtime import GraphEventStore
from tests.unit.graph_test_utils import event


def test_node_created_payload_serializes_canonical_shape() -> None:
    raw = {
        "node_id": "worker-1",
        "kind": "worker",
        "state": "planned",
        "task_region_id": "task-1",
        "attempt_number": 1,
        "authority": {"resource_claims": []},
        "resource_claims": [],
        "allowed_actions": ["submit_output"],
        "preconditions": ["inputs_bound"],
    }
    assert NodeCreatedPayload.model_validate(raw).model_dump(mode="json") == raw


@pytest.mark.parametrize(
    "raw",
    [
        {"node_id": "worker-1", "kind": "worker", "future_field": True},
        {"node_id": "worker-1", "kind": "worker", "attempt_number": "1"},
    ],
)
def test_node_created_payload_rejects_unknown_and_wrong_typed_fields(
    raw: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_reducer_reads_direct_membership_fields() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "task_region_id": "task-1",
                    "attempt_number": 2,
                },
            )
        ]
    )
    assert projection["node_task_regions"]["worker-1"] == "task-1"
    assert projection["node_attempts"]["worker-1"] == 2


def test_direct_authority_controls_take_precedence_over_nested_authority() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "authority": {
                        "resource_claims": [
                            {"mode": "write", "scope": "repo", "paths": ["nested"]}
                        ],
                        "allowed_actions": ["nested_action"],
                        "preconditions": ["nested_precondition"],
                    },
                    "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["direct"]}],
                    "allowed_actions": ["direct_action"],
                    "preconditions": ["direct_precondition"],
                },
            )
        ]
    )
    created = projection["node_creation_payloads"]["worker-1"]

    assert [claim.paths for claim in created.resource_claims] == [["direct"]]
    assert created.allowed_actions == ["direct_action"]
    assert created.preconditions == ["direct_precondition"]


def test_explicit_empty_direct_controls_take_precedence_on_node_created() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "authority": {
                        "resource_claims": [
                            {"mode": "write", "scope": "repo", "paths": ["nested"]}
                        ],
                        "allowed_actions": ["nested_action"],
                        "preconditions": ["nested_precondition"],
                    },
                    "resource_claims": [],
                    "allowed_actions": [],
                    "preconditions": [],
                },
            )
        ]
    )
    created = projection["node_creation_payloads"]["worker-1"]

    assert created.resource_claims == []
    assert created.allowed_actions == []
    assert created.preconditions == []


def test_explicit_empty_authority_change_controls_override_nested_authority() -> None:
    projection = build_projection(
        [
            event(
                "node_created",
                {
                    "node_id": "worker-1",
                    "kind": "worker",
                    "authority": {
                        "resource_claims": [
                            {"mode": "write", "scope": "repo", "paths": ["initial"]}
                        ],
                        "allowed_actions": ["initial_action"],
                        "preconditions": ["initial_precondition"],
                    },
                },
            ),
            event(
                "node_authority_changed",
                {
                    "node_id": "worker-1",
                    "authority": {
                        "resource_claims": [
                            {"mode": "write", "scope": "repo", "paths": ["nested"]}
                        ],
                        "allowed_actions": ["nested_action"],
                        "preconditions": ["nested_precondition"],
                    },
                    "resource_claims": [],
                    "allowed_actions": [],
                    "preconditions": [],
                },
            ),
        ]
    )

    assert projection["node_resource_claims"]["worker-1"] == []
    assert projection["node_allowed_actions"]["worker-1"] == []
    assert projection["node_preconditions"]["worker-1"] == []


def test_compiler_node_created_producer_matches_typed_payload_json() -> None:
    routine = RoutineConfig(
        id="typed-nodes",
        name="Typed nodes",
        steps=[StepConfig(id="S-1", title="Step", tasks=[TaskConfig(id="T-1", title="Task")])],
    )
    emitted = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        run_id="run-1",
    )

    for node_event in (item for item in emitted if item.event_type == "node_created"):
        assert node_event.payload == NodeCreatedPayload.model_validate(
            node_event.payload
        ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_hidden_oracle_and_node_created_parity_survive_compact_sqlite_replay() -> None:
    node = event(
        "node_created",
        {
            "node_id": "check-hidden-1",
            "kind": "check",
            "state": "planned",
            "task_region_id": "task-1",
            "attempt_number": 1,
            "hidden_oracle_command": "uv run pytest tests/oracle -q",
            "command_definition": {"id": "hidden-oracle", "cmd": "true"},
            "inputs": [{"port": "candidate_under_test", "direction": "input", "required": True}],
            "outputs": [{"port": "check_result", "direction": "output", "required": False}],
        },
        position=1,
    )
    full_checkpoint = projection_to_checkpoint(build_projection([node]))
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            async with session.begin():
                await GraphEventStore(session).append_events("run-1", 0, [node])
            store = GraphEventStore(session)
            for reader in (
                store.read_run_projection,
                store.read_run_light,
                store.read_run_summary_rebuild,
                store.read_run_node_detail,
            ):
                compact_events = await reader("run-1")
                assert compact_events[0].payload["hidden_oracle_command"] == (
                    "uv run pytest tests/oracle -q"
                )
                assert projection_to_checkpoint(build_projection(compact_events)) == full_checkpoint
    finally:
        await engine.dispose()
