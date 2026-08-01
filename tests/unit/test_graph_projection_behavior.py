import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    CANONICAL_EVENT_TYPES,
    PROJECTION_NEUTRAL_EVENT_TYPES,
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
)
from tests.unit.graph_projection_behavior_cases import behavior_cases, case_projection


CASES = behavior_cases()


def test_behavior_matrix_exactly_covers_every_canonical_event_once() -> None:
    event_types = tuple(case.event_type for case in CASES)
    assert len(event_types) == len(set(event_types))
    assert frozenset(event_types) == CANONICAL_EVENT_TYPES
    assert {
        case.event_type for case in CASES if not case.changed_groups
    } == PROJECTION_NEUTRAL_EVENT_TYPES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.event_type)
def test_each_canonical_event_owns_its_declared_behavior(case) -> None:
    before, after = case_projection(case)
    case.assert_outcome(before, after)
    assert (after is before) is (case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES)


@pytest.mark.parametrize(
    "case",
    tuple(case for case in CASES if case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES),
    ids=lambda case: case.event_type,
)
def test_projection_neutral_events_reject_malformed_payloads_without_changing_state(case) -> None:
    before, _ = case_projection(case)
    snapshot = projection_to_checkpoint(before)
    malformed = case.event.model_copy(update={"payload": {"__unexpected__": True}})

    with pytest.raises(ValidationError):
        reduce_event(before, malformed)

    assert projection_to_checkpoint(before) == snapshot


def test_unsupported_event_name_still_fails_loudly() -> None:
    source = CASES[0].event
    unsupported = source.model_copy(
        update={"event_id": "unsupported", "event_type": "not_canonical", "payload": {}}
    )
    with pytest.raises(ValueError, match="unsupported graph projection event type"):
        reduce_event(initial_projection(), unsupported)
