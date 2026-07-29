"""Boundary conversion contracts for immutable projected records."""

from typing import Any, cast

import pytest
from pydantic import TypeAdapter

from orchestrator.graph import (
    OUTPUT_RECORD_MODELS_BY_TYPE,
    FrozenMap,
    ProjectedRecord,
    project_record,
)
from tests.unit.test_output_record_event_payloads import OUTPUT_RECORD_CASES


@pytest.mark.parametrize("record_type", sorted(OUTPUT_RECORD_MODELS_BY_TYPE))
def test_project_record_converts_each_accepted_tag(record_type: str) -> None:
    source_type = OUTPUT_RECORD_MODELS_BY_TYPE[record_type]
    source = source_type.model_validate(OUTPUT_RECORD_CASES[record_type])

    projected = project_record(source)

    assert projected.record_type == record_type
    assert isinstance(projected.data, FrozenMap)


@pytest.mark.parametrize("record_type", sorted(OUTPUT_RECORD_MODELS_BY_TYPE))
def test_projected_record_round_trips_public_json(record_type: str) -> None:
    source = OUTPUT_RECORD_MODELS_BY_TYPE[record_type].model_validate(
        OUTPUT_RECORD_CASES[record_type]
    )
    projected = project_record(source)

    restored = TypeAdapter(ProjectedRecord).validate_json(projected.model_dump_json())

    assert restored == projected


def test_project_record_isolated_from_source_event_mutation() -> None:
    raw: dict[str, Any] = dict(OUTPUT_RECORD_CASES["candidate"])
    source = OUTPUT_RECORD_MODELS_BY_TYPE["candidate"].model_validate(raw)
    projected = project_record(source)

    raw["value"]["summary"] = "mutated after projection"

    assert projected.data["value"]["summary"] == "Implemented the requested change"


def test_project_record_rejects_unknown_discriminator() -> None:
    with pytest.raises(ValueError, match="unknown projected record discriminator"):
        project_record(cast(Any, {"record_type": "unknown"}))
