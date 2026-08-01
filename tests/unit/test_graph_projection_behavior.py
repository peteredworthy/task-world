from copy import deepcopy

import pytest
from pydantic import ValidationError

from orchestrator.graph import (
    CANONICAL_EVENT_TYPES,
    PROJECTION_NEUTRAL_EVENT_TYPES,
    initial_projection,
    projection_to_checkpoint,
    reduce_event,
    validate_projection_integrity,
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
    validate_projection_integrity(before)
    projection_to_checkpoint(before)
    case.assert_outcome(before, after)
    validate_projection_integrity(after)
    projection_to_checkpoint(after)
    before_query = case.query(before)
    after_query = case.query(after)
    assert (after is before) is (case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES)
    if case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES:
        assert after_query == before_query


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


@pytest.mark.parametrize(
    "case",
    tuple(case for case in CASES if case.changed_groups and case.prefix),
    ids=lambda case: case.event_type,
)
def test_matrix_metadata_names_replaced_values_and_shared_siblings(case) -> None:
    before, after = case_projection(case)

    assert case.shared_paths, case.event_type

    for path in case.replaced_paths:
        assert _value_at(before, path) is not _value_at(after, path), (case.event_type, path)
    for path in case.shared_paths:
        assert _value_at(before, path) is _value_at(after, path), (case.event_type, path)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.event_type)
def test_matrix_queries_are_event_specific_public_probes(case) -> None:
    _, projection = case_projection(case)

    assert case.query(projection) != projection_to_checkpoint(projection), case.event_type


@pytest.mark.parametrize(
    "case",
    tuple(case for case in CASES if case.mutate_query_result is not None),
    ids=lambda case: case.event_type,
)
def test_matrix_mutation_probes_change_only_fresh_public_results(case) -> None:
    _, projection = case_projection(case)
    checkpoint = projection_to_checkpoint(projection)
    result = case.query(projection)
    original = deepcopy(result)

    assert case.mutate_query_result is not None
    case.mutate_query_result(result)

    assert result != original, case.event_type
    assert projection_to_checkpoint(projection) == checkpoint


@pytest.mark.parametrize(
    "case",
    tuple(case for case in CASES if case.event_type in PROJECTION_NEUTRAL_EVENT_TYPES),
    ids=lambda case: case.event_type,
)
def test_neutral_mutable_queries_declare_mutation_probes(case) -> None:
    if case.has_mutable_query_target:
        assert case.mutate_query_result is not None, case.event_type
        assert case.frozen_query_result_target is None, case.event_type
    elif case.frozen_query_result_target is not None:
        assert case.mutate_query_result is None, case.event_type
    else:
        assert case.mutate_query_result is None, case.event_type


def _value_at(projection: object, path: tuple[str, ...]) -> object:
    value = projection
    for part in path:
        value = getattr(value, part) if hasattr(value, part) else value[part]
    return value
