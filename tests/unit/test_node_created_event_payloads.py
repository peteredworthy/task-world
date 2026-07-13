from __future__ import annotations

from typing import Any

import pytest

from orchestrator.config.models import RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import EventV2Model, create_engine, create_session_factory, init_db
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    FakeClock,
    NodeCreatedPayload,
    SequentialIdGenerator,
    build_projection,
    compile_routine,
    project_planner_chain,
    projection_to_checkpoint,
)
from orchestrator.graph_runtime.store import (
    GRAPH_PAYLOAD_SCHEMA_GENERATION,
    GraphEventStore,
    graph_aggregate_id,
)
from orchestrator.graph import build_graph_catalog
from orchestrator.graph.events.topology import SEED_COMPILED_EVENTS, SeedCompiledEventsCommand
from orchestrator.graph.specifications import EventMetadata


def test_node_created_payload_accepts_complete_named_producer_shape() -> None:
    payload = NodeCreatedPayload.model_validate(
        {
            "node_id": "worker-1",
            "kind": "worker",
            "task_region_id": "task-1",
            "attempt_number": 2,
            "candidate_id": "candidate-2",
            "failed_candidate_id": "candidate-1",
            "resource_claims": [{"mode": "write", "scope": "repo", "paths": ["src"]}],
            "allowed_actions": ["submit_records"],
            "preconditions": ["inputs_bound"],
        }
    )
    assert payload.task_region_id == "task-1"
    assert payload.resource_claims[0].paths == ["src"]


@pytest.mark.parametrize(
    "payload",
    [
        {"node_id": "worker-1", "kind": "worker", "membership": {"attempt_number": 2}},
        {"node_id": "worker-1", "kind": "worker", "authority": {"allowed_actions": []}},
        {"node_id": "worker-1", "kind": "worker", "legacy_note": {"preserved": True}},
        {"node_id": "legacy", "kind": 7, "attempt_number": True, "inputs": "in"},
    ],
)
def test_node_created_payload_rejects_legacy_aliases_unknown_keys_and_malformed_values(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(payload)


def test_node_created_rejects_malformed_nested_input() -> None:
    raw = {
        "node_id": "legacy-inputs",
        "kind": "worker",
        "state": "planned",
        "inputs": [
            {"port": "valid-in", "direction": "input", "schema": "Candidate"},
            {"port": "bad-direction", "direction": "sideways", "schema": "Candidate"},
            {"port": "bad-required", "direction": "input", "required": {"legacy": True}},
        ],
    }

    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_rejects_malformed_nested_output() -> None:
    raw = {
        "node_id": "legacy-outputs",
        "kind": "artifact",
        "state": "completed",
        "outputs": [
            {
                "port": "valid-out",
                "direction": "output",
                "schema": "Artifact",
                "record_layers": ["graph_record"],
            },
            {"port": "bad-schema", "direction": "output", "schema": {"legacy": True}},
            {"port": "bad-layers", "direction": "output", "record_layers": "graph_record"},
        ],
    }

    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_rejects_malformed_nested_claim_and_planner_region() -> None:
    raw = {
        "node_id": "legacy-nested-shapes",
        "kind": "planner",
        "role": "planner",
        "state": "planned",
        "resource_claims": [
            {"mode": "read", "scope": "repo"},
            {"mode": ["legacy"], "scope": "repo"},
        ],
        "planner_chain": {
            "source": ["legacy-source"],
            "regions": [
                {"generation_index": 0, "region_label": "valid"},
                {"generation_index": [1], "region_label": "invalid"},
            ],
        },
    }

    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_rejects_extra_collisions_and_unknown_fields() -> None:
    raw = {
        "node_id": "legacy-collisions",
        "kind": "worker",
        "state": "planned",
        "extra": {
            "inputs": {"old": "input evidence"},
            "resource_claims": "old claim evidence",
            "planner_chain": {"old": "planner evidence"},
            "future_field": "old future evidence",
        },
        "inputs": [
            {"port": "valid", "direction": "input"},
            {"port": "invalid", "direction": "sideways"},
        ],
        "resource_claims": [
            {"mode": "read", "scope": "repo"},
            {"path": 123},
        ],
        "planner_chain": {
            "regions": [
                {"generation_index": 0, "region_label": "valid"},
                {"generation_index": True, "region_label": "invalid"},
            ]
        },
        "future_field": "new future evidence",
    }

    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_rejects_malformed_nested_scalars() -> None:
    raw = {
        "node_id": "legacy-coercions",
        "kind": "planner",
        "role": "planner",
        "state": "planned",
        "inputs": [
            {"port": "valid-in", "direction": "input", "required": True},
            {"port": "integer-bool", "direction": "input", "required": 1},
            {"port": "string-bool", "direction": "input", "required": "yes"},
        ],
        "resource_claims": [
            {"mode": "read", "scope": "repo", "paths": ["src"]},
            {"mode": "read", "scope": "repo", "paths": ["src", 7]},
            {"path": 123},
        ],
        "planner_chain": {
            "regions": [
                {"generation_index": 2, "region_label": "valid"},
                {"generation_index": True, "region_label": "bool-invalid"},
            ]
        },
    }

    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_rejects_invalid_action_and_precondition_elements() -> None:
    raw = {
        "node_id": "legacy-string-lists",
        "kind": "worker",
        "allowed_actions": ["submit_records", 7, {"legacy": True}],
        "preconditions": ["inputs_bound", False, ["legacy"]],
        "extra": {"allowed_actions": "old action evidence"},
    }

    with pytest.raises(ValueError):
        NodeCreatedPayload.model_validate(raw)


def test_node_created_payload_preserves_compiler_recovery_and_command_fields() -> None:
    raw: dict[str, Any] = {
        "run_id": "run-1",
        "node_id": "planner-recovery-1",
        "kind": "planner",
        "role": "gap_planner",
        "state": "planned",
        "task_region_id": "recovery-task-1",
        "attempt_number": 3,
        "candidate_id": "candidate-3",
        "failed_candidate_id": "candidate-2",
        "resource_claims": [{"mode": "read", "scope": "repo", "paths": ["src"]}],
        "allowed_actions": ["submit_patch"],
        "preconditions": ["inputs_bound"],
        "planner_generation_budget": 5,
        "generation_index": 2,
        "region_label": "repair",
        "session_id": "session-1",
        "carryover_record_id": "carryover-1",
        "planner_chain": {
            "source": "legacy_parent_child",
            "regions": [
                {
                    "generation_index": 2,
                    "region_label": "repair",
                    "child_routine": "repair-routine",
                }
            ],
        },
        "gate_type": "approval",
        "approval_type": "human",
        "reason": "repair required",
        "prompt": "Proceed?",
        "approval_prompt": "Approve?",
        "human_prompt": "Choose",
        "message": "Review",
        "blocker": "waiting",
        "blocker_reason": "operator",
        "decision_request": {"options": ["yes", "no"], "opaque": {"kept": True}},
        "authority_request_record": {"requested_authority": ["repo_write"]},
        "authority_request": {"target_region_id": "task-1"},
        "decision_request_record_id": "decision-request-1",
        "authority_request_record_id": "authority-request-1",
        "command_definition": {"argv": ["uv", "run", "pytest"], "future": True},
        "command_definition_id": "command-1",
        "hidden_oracle_command": "uv run pytest hidden",
        "command_binding": "dynamic_feature_hidden_oracle",
        "recovery_reason": "failed_verification",
        "recovery_of_node_id": "verifier-1",
        "recovery_of_record_id": "verification-1",
        "guarded_planner_node_id": "planner-1",
        "rejected_patch_id": "patch-1",
        "requirement_id": "R-1",
        "priority": "must",
        "requirement": {"id": "R-1", "priority": "must"},
        "inputs": [
            {
                "port": "verification_evidence",
                "direction": "input",
                "schema": "VerificationReport",
                "required": True,
            }
        ],
        "outputs": [
            {
                "port": "graph_patch",
                "direction": "output",
                "schema": "GraphPatch",
                "record_layers": ["graph_record"],
            }
        ],
    }

    dumped = NodeCreatedPayload.model_validate(raw).model_dump(mode="json")

    assert set(raw) <= set(dumped)
    assert dumped["planner_chain"]["regions"][0]["child_routine"] == "repair-routine"
    assert dumped["decision_request"]["opaque"] == {"kept": True}
    assert dumped["command_definition"]["future"] is True
    assert dumped["inputs"][0]["schema_"] == "VerificationReport"
    assert dumped["outputs"][0]["schema_"] == "GraphPatch"


def test_node_created_reducer_preserves_planner_recovery_and_authority_indexes() -> None:
    events = [
        _event(
            {
                "node_id": "root",
                "kind": "root",
                "state": "completed",
                "planner_generation_budget": 4,
                "planner_chain": {"regions": [{"generation_index": 1, "region_label": "repair"}]},
            },
            position=1,
        ),
        _event(
            {
                "node_id": "planner-1",
                "kind": "planner",
                "role": "planner",
                "state": "planned",
                "generation_index": 1,
                "session_id": "session-1",
                "resource_claims": [{"mode": "read", "scope": "repo"}],
                "allowed_actions": ["submit_patch"],
                "preconditions": ["inputs_bound"],
            },
            position=2,
        ),
        _event(
            {
                "node_id": "recovery-1",
                "kind": "planner",
                "role": "gap_planner",
                "state": "planned",
                "task_region_id": "recovery-task-1",
                "recovery_reason": "failed_verification",
                "recovery_of_record_id": "verification-1",
            },
            position=3,
        ),
    ]

    projection = build_projection(build_graph_catalog(), events)

    assert projection["planner_generation_budget"] == 4
    assert projection["planner_generations"].values == {"planner-1": 1}
    assert projection["planner_sessions"].values == {"planner-1": "session-1"}
    assert projection["node_allowed_actions"] == {"planner-1": ["submit_patch"]}
    assert projection["node_preconditions"] == {"planner-1": ["inputs_bound"]}
    assert projection["node_resource_claims"]["planner-1"][0].scope == "repo"
    recovery_nodes = projection["recovery_nodes_by_record_id"]["verification-1"]
    assert [entry.node_id for entry in recovery_nodes] == ["recovery-1"]
    planner_rows = project_planner_chain(build_graph_catalog(), events)
    assert planner_rows[0]["region_label"] == "repair"


def test_node_created_producers_emit_payloads_validated_by_typed_model() -> None:
    from tests.graph_command_support import dispatch_graph_command

    routine = RoutineConfig(
        id="typed-nodes",
        name="Typed nodes",
        steps=[StepConfig(id="S-1", title="Step", tasks=[TaskConfig(id="T-1", title="Task")])],
    )
    compiler_events = compile_routine(
        routine,
        FakeClock(),
        SequentialIdGenerator(),
        catalog=build_graph_catalog(),
        run_id="run-1",
    )
    patch_events = dispatch_graph_command(
        [],
        "submit_patch",
        {
            "run_id": "run-1",
            "patch_id": "patch-1",
            "proposed_by_node_id": "planner-1",
            "actor_role": "planner",
            "base_graph_position": -1,
            "ops": [
                {
                    "op": "create_node",
                    "node": {
                        "node_id": "artifact-1",
                        "kind": "artifact",
                        "state": "planned",
                    },
                }
            ],
        },
    )
    appeal_events = dispatch_graph_command(
        [],
        "raise_appeal",
        {"run_id": "run-1", "node_id": "verifier-1", "appeal_type": "invalid_test"},
    )
    compiler_nodes = [
        event for event in compiler_events if event.metadata.event_type == "node_created"
    ]
    command_nodes = [
        event for event in [*patch_events, *appeal_events] if event.event_type == "node_created"
    ]

    assert compiler_nodes and command_nodes
    assert all(isinstance(event.payload, NodeCreatedPayload) for event in compiler_nodes)
    assert all(NodeCreatedPayload.model_validate(event.payload).node_id for event in command_nodes)


def test_seed_compiled_events_accepts_only_hydrated_registered_events() -> None:
    catalog = build_graph_catalog()
    event = catalog.resolve_event("node_created").create(
        EventMetadata(
            event_id="seeded-1",
            run_id="run-1",
            position=-1,
            event_type="node_created",
            payload_schema_generation=2,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=FakeClock().now(),
        ),
        NodeCreatedPayload(node_id="seeded-1", kind="artifact", state="planned"),
    )
    command = SeedCompiledEventsCommand(events=(event,))
    assert SEED_COMPILED_EVENTS.payload_type is SeedCompiledEventsCommand
    assert command.events == (event,)


def test_compiler_planner_preserves_step_context_as_named_top_level_field() -> None:
    routine = RoutineConfig(
        id="planner-metadata",
        name="Planner metadata",
        steps=[
            StepConfig(
                id="S-1",
                kind="planner",
                title="Plan",
                step_context="Retain this planner context.",
            )
        ],
    )

    planner = next(
        event
        for event in compile_routine(
            routine,
            FakeClock(),
            SequentialIdGenerator(),
            catalog=build_graph_catalog(),
            run_id="run-1",
        )
        if event.metadata.event_type == "node_created"
        and isinstance(event.payload, NodeCreatedPayload)
        and event.payload.role == "planner"
    )

    assert isinstance(planner.payload, NodeCreatedPayload)
    assert planner.payload.step_context == "Retain this planner context."


@pytest.mark.asyncio
async def test_hidden_oracle_command_survives_all_sqlite_compact_readers() -> None:
    hidden_oracle_command = "uv run pytest tests/oracle -q"
    event = _event(
        {
            "node_id": "check-hidden-1",
            "kind": "check",
            "state": "planned",
            "hidden_oracle_command": hidden_oracle_command,
        },
        position=1,
    )
    full_checkpoint = projection_to_checkpoint(build_projection(build_graph_catalog(), [event]))

    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id("run-1"),
                    version=1,
                    event_type=event.event_type,
                    payload=event.model_dump_json(),
                    payload_schema_generation=GRAPH_PAYLOAD_SCHEMA_GENERATION,
                    timestamp=event.timestamp.isoformat(),
                )
            )
            await session.flush()
            store = GraphEventStore(
                session,
                build_graph_catalog(),
            )
            for reader in (
                store.read_run_projection,
                store.read_run_light,
                store.read_run_summary_rebuild,
                store.read_run_node_detail,
            ):
                compact_events = await reader("run-1")
                assert compact_events[0].payload["hidden_oracle_command"] == hidden_oracle_command
                assert (
                    projection_to_checkpoint(
                        build_projection(build_graph_catalog(), compact_events)
                    )
                    == full_checkpoint
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_node_created_compact_replay_matches_full_replay() -> None:
    events = [
        _event(
            NodeCreatedPayload.model_validate(
                {
                    "node_id": "planner-1",
                    "kind": "planner",
                    "role": "planner",
                    "state": "planned",
                    "task_region_id": "task-1",
                    "attempt_number": 2,
                    "candidate_id": "candidate-2",
                    "failed_candidate_id": "candidate-1",
                    "resource_claims": [{"mode": "read", "scope": "repo"}],
                    "allowed_actions": ["submit_patch"],
                    "preconditions": ["inputs_bound"],
                    "planner_generation_budget": 5,
                    "generation_index": 1,
                    "region_label": "repair",
                    "session_id": "session-1",
                    "recovery_reason": "failed_verification",
                    "recovery_of_record_id": "verification-1",
                    "command_definition": {"argv": ["uv", "run", "pytest"]},
                    "inputs": [{"port": "in", "required": True}],
                    "outputs": [{"port": "out", "required": False}],
                }
            ).model_dump(mode="json"),
            position=1,
        )
    ]
    full_checkpoint = projection_to_checkpoint(build_projection(build_graph_catalog(), events))
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)
    try:
        async with session_factory() as session:
            event = events[0]
            session.add(
                EventV2Model(
                    aggregate_id=graph_aggregate_id("run-1"),
                    version=1,
                    event_type=event.event_type,
                    payload=event.model_dump_json(),
                    payload_schema_generation=GRAPH_PAYLOAD_SCHEMA_GENERATION,
                    timestamp=event.timestamp.isoformat(),
                )
            )
            await session.flush()
            store = GraphEventStore(
                session,
                build_graph_catalog(),
            )
            for reader in (
                store.read_run_projection,
                store.read_run_light,
                store.read_run_summary_rebuild,
                store.read_run_node_detail,
            ):
                compact_events = await reader("run-1")
                assert (
                    projection_to_checkpoint(
                        build_projection(build_graph_catalog(), compact_events)
                    )
                    == full_checkpoint
                )
    finally:
        await engine.dispose()


def _event(payload: dict[str, Any], *, position: int) -> EventEnvelope:
    return EventEnvelope(
        event_id=f"node-created-{position}",
        run_id="run-1",
        position=position,
        event_type="node_created",
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload=payload,
    )
