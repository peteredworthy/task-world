"""Strict scheduling and seeding command payload coverage."""

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    ReconcileCommand,
    ScheduleTickCommand,
    SeedCompiledEventsCommand,
)


@pytest.mark.parametrize("field", ["max_grants", "lease_seconds"])
@pytest.mark.parametrize("value", [True, "10"])
def test_schedule_tick_rejects_coerced_integer_fields(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        ScheduleTickCommand.model_validate({field: value})


def test_schedule_tick_rejects_non_integer_dynamic_values() -> None:
    with pytest.raises(ValidationError):
        ScheduleTickCommand.model_validate({"priorities": {"worker-1": "1"}})


def test_reconcile_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ReconcileCommand.model_validate({"ignored": True})


def test_seed_compiled_events_requires_non_empty_events() -> None:
    with pytest.raises(ValidationError):
        SeedCompiledEventsCommand.model_validate({"events": []})
