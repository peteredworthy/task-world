from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Literal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.graph import Actor, ActorKind, EventEnvelope, FakeClock
from orchestrator.graph_runtime import store
from orchestrator.graph_runtime import GraphEventStore
from orchestrator.graph_runtime.store import GraphReadModelUnavailable, summarize_graph_event
import orchestrator.api.routers.graph as graph_router


@pytest.fixture
async def bounded_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_engine(":memory:")
    await init_db(engine)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.parametrize(
    ("key", "route_name", "sql_rows", "decoded_values", "byte_cap"),
    [
        ("graph", "/graph", 1, 0, 262_144),
        ("scheduler", "/scheduler", 1, 0, 262_144),
        ("decisions", "/decisions", 1, 0, 262_144),
        ("topology", "/topology", 100, 0, 262_144),
        ("final_blockers", "/final-blockers", 100, 0, 262_144),
        ("regions", "/regions", 100, 0, 262_144),
        ("events_summary", "/events?payload_mode=summary", 101, 101, 262_144),
        ("events_full", "/events?payload_mode=full", 101, 101, 262_144),
        ("node_detail", "/nodes/{node_id}", 51, 50, 262_144),
        ("file_state", "/file-state", 101, 100, 262_144),
        ("patches", "/patches", 101, 100, 262_144),
        ("evidence_digest", "/evidence-digest", 100, 100, 262_144),
        ("artifact", "/artifacts/{sha}", 1, 1, 1_048_576),
        ("runtime", "graph-runtime", 129, 128, 0),
    ],
)
def test_graph_read_contract_matrix_has_exact_hard_budgets(
    key: str,
    route_name: str,
    sql_rows: int,
    decoded_values: int,
    byte_cap: int,
) -> None:
    contracts = getattr(store, "GRAPH_READ_CONTRACTS", None)
    assert contracts is not None, "checked graph read-contract matrix is missing"
    contract = contracts[key]

    assert contract.route_name == route_name
    assert contract.sql_row_cap == sql_rows
    assert contract.decode_cap == decoded_values
    assert contract.byte_cap == byte_cap
    assert contract.budget.string_byte_cap == store.GRAPH_STRING_BYTES == 4_096
    assert contract.budget.object_entry_cap == store.GRAPH_JSON_OBJECT_ENTRIES == 32
    assert contract.budget.array_item_cap == store.GRAPH_JSON_ARRAY_ITEMS == 50
    assert contract.budget.depth_cap == store.GRAPH_JSON_DEPTH == 6
    assert store.GRAPH_RESPONSE_BYTES == 262_144
    assert contract.ordering_key
    assert contract.cursor_field
    assert contract.stale_policy
    assert contract.owner_read_model_name


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("x" * 4_097, id="string"),
        pytest.param(list(range(51)), id="array"),
        pytest.param({f"key-{index:02d}": index for index in range(33)}, id="object"),
        pytest.param({"1": {"2": {"3": {"4": {"5": {"6": {"7": "deep"}}}}}}}, id="depth"),
    ],
)
def test_bound_graph_json_replaces_over_budget_values_deterministically(value: object) -> None:
    helper = getattr(store, "bound_graph_json", None)
    assert helper is not None, "bounded JSON helper is missing"
    first = helper(value)
    second = helper(value)

    assert first == second
    assert set(first) == {"value", "truncated", "original_bytes", "sha256"}
    assert first["truncated"] is True
    assert first["original_bytes"] == len(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    assert isinstance(first["sha256"], str)
    assert len(first["sha256"]) == 64
    assert json.dumps(value, ensure_ascii=False, sort_keys=True) not in json.dumps(
        first, ensure_ascii=False, sort_keys=True
    )


@pytest.mark.parametrize(
    "candidate_id",
    ["candidate-" + ("x" * 1_000), "候" * 100],
    ids=["ascii-over-budget", "utf8-over-budget"],
)
def test_candidate_identity_compaction_preserves_r1_namespace_metadata(
    candidate_id: str,
) -> None:
    event = EventEnvelope(
        event_id="verification-1",
        event_type="verification_passed",
        run_id="run-1",
        position=1,
        schema_version=1,
        actor=Actor(kind=ActorKind.CONTROLLER),
        timestamp=FakeClock().now(),
        payload={"verifier_node_id": "verifier-1", "candidate_id": candidate_id},
    )

    first = summarize_graph_event(event).payload
    second = summarize_graph_event(event).payload

    assert first == second
    assert first["candidate_id"] == f"sha256:{first['candidate_id_sha256']}"
    assert first["candidate_id_hashed"] is True
    assert first["candidate_id_original_chars"] == len(candidate_id)
    assert first["candidate_id_original_bytes"] == len(candidate_id.encode())
    assert len(first["candidate_id_sha256"]) == 64
    assert candidate_id not in json.dumps(first, ensure_ascii=False)


@pytest.mark.parametrize("contract_key", ["topology", "final_blockers", "regions"])
async def test_bounded_projection_history_refuses_each_over_cap_contract(
    bounded_session: AsyncSession,
    contract_key: Literal["topology", "final_blockers", "regions"],
) -> None:
    run_id = f"bounded-{contract_key}"
    events = [
        EventEnvelope(
            event_id=f"node-{index}",
            event_type="node_created",
            run_id=run_id,
            position=-1,
            schema_version=1,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=FakeClock().now(),
            payload={
                "node_id": f"node-{index}",
                "kind": "worker",
                "role": "builder",
                "state": "planned",
            },
        )
        for index in range(101)
    ]
    await GraphEventStore(bounded_session).append_events(run_id, 0, events)

    with pytest.raises(GraphReadModelUnavailable, match="history_exceeds_bounded_view_cap"):
        await GraphEventStore(bounded_session).read_current_bounded_projection_history(
            run_id,
            contract_key=contract_key,
        )


def test_typed_graph_collections_declare_pydantic_native_contracts() -> None:
    contract_type = getattr(store, "PydanticCollectionContract", None)
    assert contract_type is not None, "Pydantic collection metadata is missing"

    expected = {
        (graph_router.SchedulerViewResponseBody, "ready"): ("list", 100, "self"),
        (graph_router.SchedulerViewResponseBody, "blocked"): ("list", 100, "node_id"),
        (graph_router.SchedulerViewResponseBody, "waiting_resources"): (
            "list",
            100,
            "node_id",
        ),
        (graph_router.SchedulerViewResponseBody, "waiting_gates"): (
            "list",
            100,
            "node_id",
        ),
        (graph_router.DecisionViewResponse, "pending_gates"): ("list", 100, "node_id"),
        (graph_router.DecisionViewResponse, "appeals"): ("list", 100, "node_id"),
        (graph_router.ReviewReadinessResponse, "blockers"): ("list", 100, "self"),
        (graph_router.PendingGateDecisionResponse, "options"): ("list", 50, "self"),
        (graph_router.PendingGateDecisionResponse, "requested_authority"): (
            "list",
            50,
            "self",
        ),
    }
    for (model, field_name), values in expected.items():
        metadata = [
            item
            for item in model.model_fields[field_name].metadata
            if isinstance(item, contract_type)
        ]
        assert len(metadata) == 1
        contract = metadata[0]
        assert (contract.shape, contract.max_items, contract.stable_identity) == values
        assert contract.continuation is True


def test_typed_response_construction_preserves_collection_shapes_above_flexible_json_cap() -> None:
    blocked = [
        graph_router.SchedulerBlockedNodeResponse(node_id=f"gate-{index:03d}", reason="blocked")
        for index in range(60)
    ]

    response = graph_router.SchedulerViewResponseBody(
        ready=[],
        blocked=blocked,
        waiting_resources=blocked,
        waiting_gates=blocked,
    )

    assert len(response.blocked) == 60
    assert all(
        isinstance(item, graph_router.SchedulerBlockedNodeResponse) for item in response.blocked
    )
