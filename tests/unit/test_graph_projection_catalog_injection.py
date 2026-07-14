from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, ClassVar, cast

from datetime import UTC, datetime

import pytest

from orchestrator.graph import (
    Actor,
    ActorKind,
    EventMetadata,
    GraphCatalog,
    build_graph_catalog,
    initial_projection,
    reduce_event,
)
from orchestrator.graph.payloads import StrictPayload
from orchestrator.graph.specifications import EventSpecification, ProjectionParticipation
from pydantic import field_validator
from orchestrator.graph import UnknownGraphEventError


def test_projection_module_does_not_construct_a_graph_catalog() -> None:
    source = Path("src/orchestrator/graph/projections.py").read_text()
    tree = ast.parse(source)

    assert "build_graph_catalog" not in {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }


def test_reduce_event_honors_the_injected_catalog() -> None:
    catalog = build_graph_catalog()
    specification = catalog.resolve_event("run_lifecycle_changed")
    lifecycle_event = specification.create(
        EventMetadata(
            event_id="event-1",
            run_id="run-1",
            position=1,
            event_type="run_lifecycle_changed",
            payload_schema_generation=2,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        specification.validate_payload(
            {"from_state": "pending", "to_state": "active", "reason": "start"}
        ),
    )

    empty_catalog = GraphCatalog.compose((), ())
    with pytest.raises(UnknownGraphEventError, match="run_lifecycle_changed"):
        reduce_event(empty_catalog, initial_projection(), lifecycle_event)
    normal_result = reduce_event(catalog, initial_projection(), lifecycle_event)

    assert normal_result["run_state"] == "active"


def test_catalog_owned_event_hydrates_once_through_injected_catalog() -> None:
    validations: list[str] = []

    class CountingPayload(StrictPayload):
        value: str
        observations: ClassVar[list[str]] = validations

        @field_validator("value")
        @classmethod
        def observe_validation(cls, value: str) -> str:
            cls.observations.append(value)
            return value

    def reducer(
        state: dict[str, object],
        payload: CountingPayload,
        metadata: EventMetadata,
    ) -> dict[str, object]:
        return {**state, "value": payload.value, "event_id": metadata.event_id}

    specification = EventSpecification(
        name="custom_owned_event",
        payload_type=CountingPayload,
        reducer=reducer,
        projection_participation=ProjectionParticipation.MUTATES,
    )
    catalog = GraphCatalog.compose((specification,), ())
    owned_specification = catalog.resolve_event("custom_owned_event")
    owned_event = owned_specification.create(
        EventMetadata(
            event_id="event-1",
            run_id="run-1",
            position=1,
            event_type="custom_owned_event",
            payload_schema_generation=2,
            actor=Actor(kind=ActorKind.CONTROLLER),
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        owned_specification.validate_payload({"value": "observed-once"}),
    )

    result = reduce_event(catalog, initial_projection(), owned_event)

    assert cast(dict[str, Any], result)["value"] == "observed-once"
    assert validations == ["observed-once"]
