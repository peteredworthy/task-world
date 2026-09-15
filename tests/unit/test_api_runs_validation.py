"""Unit tests for run API request schema field validators."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from orchestrator.api import (
    BackwardTransitionRequest,
    CreateRunRequest,
    MergeBackRequest,
    RecoverRequest,
    ResumeRunRequest,
)
from orchestrator.api.schemas.model_profiles import AgentRunnerModelProfileDefaultsSchema
from orchestrator.api.schemas.review import AgentResolveConflictsRequest


# ---------------------------------------------------------------------------
# agent_runner_type validator (CreateRunRequest, ResumeRunRequest, RecoverRequest)
# ---------------------------------------------------------------------------


def test_invalid_agent_runner_type_rejected() -> None:
    """Invalid agent_runner_type raises ValidationError with helpful message."""
    with pytest.raises(ValidationError) as exc_info:
        CreateRunRequest(
            routine_id="r", repo_name="proj", branch="main", agent_runner_type="INVALID"
        )
    assert "Invalid agent_runner_type" in str(exc_info.value)
    assert "Valid options" in str(exc_info.value)


def test_removed_user_managed_agent_runner_type_rejected() -> None:
    """The removed external runner type is no longer accepted."""
    with pytest.raises(ValidationError) as exc_info:
        CreateRunRequest(
            routine_id="r", repo_name="proj", branch="main", agent_runner_type="user_managed"
        )
    assert "Invalid agent_runner_type" in str(exc_info.value)


def test_uppercase_agent_runner_type_normalised() -> None:
    """agent_runner_type is accepted and normalised to lowercase."""
    req = CreateRunRequest(
        routine_id="r", repo_name="proj", branch="main", agent_runner_type="CODEX_SERVER"
    )
    assert req.agent_runner_type == "codex_server"


@pytest.mark.parametrize("agent_runner_type", ["claude_sdk", "retired"])
@pytest.mark.parametrize(
    "build_request",
    [
        lambda value: CreateRunRequest(
            routine_id="r", repo_name="proj", branch="main", agent_runner_type=value
        ),
        lambda value: ResumeRunRequest(agent_runner_type=value),
        lambda value: RecoverRequest(target_task_id="T-01", agent_runner_type=value),
    ],
)
def test_non_selectable_agent_runner_type_rejected(
    agent_runner_type: str, build_request: Callable[[str], object]
) -> None:
    """Historical runner values cannot be selected for run execution."""
    with pytest.raises(ValidationError) as exc_info:
        build_request(agent_runner_type)
    assert "Invalid agent_runner_type" in str(exc_info.value)


@pytest.mark.parametrize("invalid", [1, ["codex_server"]])
def test_non_string_agent_runner_type_rejected_at_every_run_request_boundary(
    invalid: object,
) -> None:
    """JSON numbers and arrays must not be coerced into runner identifiers."""
    builders = (
        lambda value: CreateRunRequest(
            routine_id="r", repo_name="proj", branch="main", agent_runner_type=value
        ),
        lambda value: ResumeRunRequest(agent_runner_type=value),
        lambda value: RecoverRequest(target_task_id="T-01", agent_runner_type=value),
        lambda value: AgentResolveConflictsRequest(agent_runner_type=value),
    )
    for build in builders:
        with pytest.raises(ValidationError, match="must be a string"):
            build(invalid)


@pytest.mark.parametrize("invalid", [1, ["codex_server"]])
def test_model_profile_defaults_reject_non_string_runner_type(invalid: object) -> None:
    with pytest.raises(ValidationError, match="must be a string"):
        AgentRunnerModelProfileDefaultsSchema(
            agent_runner_type=invalid,
            model_profile_defaults={},
        )


def test_valid_lowercase_agent_runner_type_accepted() -> None:
    """Standard lowercase agent runner type is accepted unchanged."""
    req = CreateRunRequest(
        routine_id="r", repo_name="proj", branch="main", agent_runner_type="cli_subprocess"
    )
    assert req.agent_runner_type == "cli_subprocess"


def test_null_agent_runner_type_accepted() -> None:
    """None/missing agent_runner_type is accepted."""
    req = CreateRunRequest(routine_id="r", repo_name="proj", branch="main")
    assert req.agent_runner_type is None


@pytest.mark.parametrize(
    "field",
    [
        "max_rejected_plan_proposals_per_planner",
        "max_planner_executions_per_node",
    ],
)
@pytest.mark.parametrize("invalid", [True, 0, -1, "2", 101])
def test_reliable_plan_runtime_limits_reject_invalid_run_config(
    field: str, invalid: object
) -> None:
    with pytest.raises(ValidationError):
        CreateRunRequest(
            routine_id="dynamic-graph-feature",
            repo_name="proj",
            branch="main",
            config={field: invalid},
        )


def test_reliable_plan_runtime_limits_accept_strict_positive_run_config() -> None:
    request = CreateRunRequest(
        routine_id="dynamic-graph-feature",
        repo_name="proj",
        branch="main",
        config={
            "max_rejected_plan_proposals_per_planner": 2,
            "max_planner_executions_per_node": 1,
        },
    )
    assert request.config["max_rejected_plan_proposals_per_planner"] == 2
    assert request.config["max_planner_executions_per_node"] == 1


# ---------------------------------------------------------------------------
# merge_strategy validator
# ---------------------------------------------------------------------------


def test_invalid_merge_strategy_rejected() -> None:
    """Invalid merge_strategy raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        CreateRunRequest(routine_id="r", repo_name="proj", branch="main", merge_strategy="rebase")
    assert "Invalid merge_strategy" in str(exc_info.value)


def test_valid_merge_strategy_accepted() -> None:
    """Valid merge_strategy is accepted."""
    req = CreateRunRequest(routine_id="r", repo_name="proj", branch="main", merge_strategy="squash")
    assert req.merge_strategy == "squash"


def test_uppercase_merge_strategy_normalised() -> None:
    """Uppercase merge_strategy is normalised to lowercase."""
    req = CreateRunRequest(routine_id="r", repo_name="proj", branch="main", merge_strategy="MERGE")
    assert req.merge_strategy == "merge"


def test_null_merge_strategy_accepted() -> None:
    """None merge_strategy is accepted."""
    req = CreateRunRequest(routine_id="r", repo_name="proj", branch="main")
    assert req.merge_strategy is None


# ---------------------------------------------------------------------------
# BackwardTransitionRequest.target_step_index  (ge=0 Field constraint)
# ---------------------------------------------------------------------------


def test_backward_transition_negative_index_rejected() -> None:
    """Negative target_step_index raises ValidationError."""
    with pytest.raises(ValidationError):
        BackwardTransitionRequest(target_step_index=-1)


def test_backward_transition_zero_index_accepted() -> None:
    """Zero target_step_index is valid."""
    req = BackwardTransitionRequest(target_step_index=0)
    assert req.target_step_index == 0


# ---------------------------------------------------------------------------
# ResumeRunRequest.agent_runner_type validator
# ---------------------------------------------------------------------------


def test_resume_invalid_agent_runner_type_rejected() -> None:
    """Invalid agent_runner_type in ResumeRunRequest raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ResumeRunRequest(agent_runner_type="NOT_REAL")
    assert "Invalid agent_runner_type" in str(exc_info.value)


def test_resume_valid_agent_runner_type_normalised() -> None:
    """Valid agent_runner_type in ResumeRunRequest is accepted."""
    req = ResumeRunRequest(agent_runner_type="CODEX_SERVER")
    assert req.agent_runner_type == "codex_server"


# ---------------------------------------------------------------------------
# RecoverRequest.additional_attempts  (ge=0 Field constraint)
# ---------------------------------------------------------------------------


def test_recover_negative_additional_attempts_rejected() -> None:
    """Negative additional_attempts raises ValidationError."""
    with pytest.raises(ValidationError):
        RecoverRequest(target_task_id="T-01", additional_attempts=-1)


def test_recover_zero_additional_attempts_accepted() -> None:
    """Zero additional_attempts is valid."""
    req = RecoverRequest(target_task_id="T-01", additional_attempts=0)
    assert req.additional_attempts == 0


# ---------------------------------------------------------------------------
# MergeBackRequest — Literal constraint on strategy
# ---------------------------------------------------------------------------


def test_merge_back_invalid_strategy_rejected() -> None:
    """Invalid strategy in MergeBackRequest raises ValidationError."""
    with pytest.raises(ValidationError):
        MergeBackRequest(strategy="rebase")


def test_merge_back_valid_strategy_squash() -> None:
    """'squash' strategy is accepted."""
    req = MergeBackRequest(strategy="squash")
    assert req.strategy == "squash"


def test_merge_back_valid_strategy_merge() -> None:
    """'merge' strategy is accepted."""
    req = MergeBackRequest(strategy="merge")
    assert req.strategy == "merge"


def test_merge_back_null_strategy_accepted() -> None:
    """None strategy is accepted."""
    req = MergeBackRequest()
    assert req.strategy is None
