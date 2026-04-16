"""Unit tests for run API request schema field validators."""

import pytest
from pydantic import ValidationError

from orchestrator.api import (
    BackwardTransitionRequest,
    CreateRunRequest,
    MergeBackRequest,
    RecoverRequest,
    ResumeRunRequest,
)


# ---------------------------------------------------------------------------
# agent_type validator (CreateRunRequest, ResumeRunRequest, RecoverRequest)
# ---------------------------------------------------------------------------


def test_invalid_agent_type_rejected() -> None:
    """Invalid agent_type raises ValidationError with helpful message."""
    with pytest.raises(ValidationError) as exc_info:
        CreateRunRequest(routine_id="r", repo_name="proj", branch="main", agent_type="INVALID")
    assert "Invalid agent_type" in str(exc_info.value)
    assert "Valid options" in str(exc_info.value)


def test_uppercase_agent_type_normalised() -> None:
    """agent_type is accepted and normalised to lowercase."""
    req = CreateRunRequest(
        routine_id="r", repo_name="proj", branch="main", agent_type="CODEX_SERVER"
    )
    assert req.agent_type == "codex_server"


def test_mixed_case_agent_type_normalised() -> None:
    """Mixed-case agent_type is normalised to lowercase."""
    req = CreateRunRequest(routine_id="r", repo_name="proj", branch="main", agent_type="Claude_SDK")
    assert req.agent_type == "claude_sdk"


def test_valid_lowercase_agent_type_accepted() -> None:
    """Standard lowercase agent type is accepted unchanged."""
    req = CreateRunRequest(
        routine_id="r", repo_name="proj", branch="main", agent_type="user_managed"
    )
    assert req.agent_type == "user_managed"


def test_null_agent_type_accepted() -> None:
    """None/missing agent_type is accepted."""
    req = CreateRunRequest(routine_id="r", repo_name="proj", branch="main")
    assert req.agent_type is None


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
# ResumeRunRequest.agent_type validator
# ---------------------------------------------------------------------------


def test_resume_invalid_agent_type_rejected() -> None:
    """Invalid agent_type in ResumeRunRequest raises ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        ResumeRunRequest(agent_type="NOT_REAL")
    assert "Invalid agent_type" in str(exc_info.value)


def test_resume_valid_agent_type_normalised() -> None:
    """Valid agent_type in ResumeRunRequest is accepted."""
    req = ResumeRunRequest(agent_type="CODEX_SERVER")
    assert req.agent_type == "codex_server"


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
