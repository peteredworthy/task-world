"""Strict canonical validation for durable runner-runtime observations."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orchestrator.workflow import GraphRunnerRuntimeObserved


def _observation(**updates: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": "run-1",
        "node_id": "worker-1",
        "execution_id": "execution-1",
        "lease_id": "lease-1",
        "lease_generation": 1,
        "runner_type": "cli_subprocess",
        "state": "exact_identity_available",
        "pid": 123,
        "process_create_time": 456.25,
        "command_sha256": "a" * 64,
        "reason": "exact child identity captured",
    }
    payload.update(updates)
    return payload


def test_exact_runtime_identity_accepts_only_complete_canonical_evidence() -> None:
    observation = GraphRunnerRuntimeObserved.model_validate(_observation())

    assert observation.state == "exact_identity_available"
    assert observation.pid == 123
    assert observation.process_create_time == 456.25
    assert observation.command_sha256 == "a" * 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pid", None),
        ("pid", 0),
        ("pid", True),
        ("pid", "123"),
        ("process_create_time", None),
        ("process_create_time", float("inf")),
        ("process_create_time", float("nan")),
        ("process_create_time", "456.25"),
        ("command_sha256", None),
        ("command_sha256", "A" * 64),
        ("command_sha256", "a" * 63),
    ],
)
def test_exact_runtime_identity_rejects_incomplete_or_noncanonical_fields(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        GraphRunnerRuntimeObserved.model_validate(_observation(**{field: value}))


@pytest.mark.parametrize("runner_type", ["", "r" * 129])
def test_runtime_observation_rejects_unbounded_runner_type(runner_type: str) -> None:
    with pytest.raises(ValidationError):
        GraphRunnerRuntimeObserved.model_validate(_observation(runner_type=runner_type))


def test_failed_runtime_states_require_root_error_and_reject_partial_identity() -> None:
    with pytest.raises(ValidationError):
        GraphRunnerRuntimeObserved.model_validate(
            _observation(
                state="missing",
                pid=None,
                process_create_time=None,
                command_sha256=None,
            )
        )
    with pytest.raises(ValidationError):
        GraphRunnerRuntimeObserved.model_validate(
            _observation(
                state="missing",
                process_create_time=None,
                root_error="identity disappeared",
            )
        )


def test_non_identity_state_rejects_identity_and_healthy_state_rejects_root_error() -> None:
    with pytest.raises(ValidationError):
        GraphRunnerRuntimeObserved.model_validate(_observation(state="not_yet_reported"))
    with pytest.raises(ValidationError):
        GraphRunnerRuntimeObserved.model_validate(
            _observation(root_error="contradicts an exact healthy observation")
        )


def test_legacy_alive_normalizes_to_exact_only_with_valid_identity() -> None:
    observation = GraphRunnerRuntimeObserved.model_validate(_observation(state="alive"))

    assert observation.state == "exact_identity_available"
    assert observation.root_error is None
    assert "legacy alive" in observation.reason


@pytest.mark.parametrize(
    "identity_updates",
    [
        {"pid": None, "process_create_time": None, "command_sha256": None},
        {"pid": 0},
        {"process_create_time": float("inf")},
        {"command_sha256": "A" * 64},
    ],
)
def test_incomplete_legacy_started_fails_closed_with_bounded_explicit_error(
    identity_updates: dict[str, object],
) -> None:
    observation = GraphRunnerRuntimeObserved.model_validate(
        _observation(state="started", **identity_updates)
    )

    assert observation.state == "invalid_metadata"
    assert observation.pid is None
    assert observation.process_create_time is None
    assert observation.command_sha256 is None
    assert observation.root_error == observation.reason
    assert "legacy started" in observation.reason
    assert len(observation.reason) <= 1_000


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ("invalid_metadata", "process metadata must include a positive integer pid"),
        ("unreported", "runner did not report within 0.01 seconds"),
        ("never_started", "runner completed before reporting"),
    ],
)
def test_process_runner_metadata_failure_states_are_explicit_and_rooted(
    state: str, reason: str
) -> None:
    observation = GraphRunnerRuntimeObserved.model_validate(
        _observation(
            state=state,
            pid=None,
            process_create_time=None,
            command_sha256=None,
            reason=reason,
            root_error=reason,
        )
    )

    assert observation.state == state
    assert observation.root_error == reason
    assert observation.reason == reason
