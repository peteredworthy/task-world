"""Unit tests for run API schema validation."""

import pytest
from pydantic import ValidationError

from orchestrator.api import (
    ActionLogSchema,
    CreateRunRequest,
    TurnMetricsSchema,
    get_agent_runner_display_name,
    get_agent_runner_icon,
    run_to_trace_response,
)
from orchestrator.config import AgentRunnerType
from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.state.models import (
    ActionEntryKind,
    ActionLog,
    ActionLogEntry,
    Attempt,
    AttemptMetrics,
    ModelTokenUsage,
    Run,
    StepState,
    TaskState,
    TurnMetrics,
)

VALID_EMBEDDED_ROUTINE = {
    "id": "embedded-test",
    "name": "Embedded Test Routine",
    "steps": [
        {
            "id": "S-01",
            "title": "Step One",
            "tasks": [
                {
                    "id": "T-01",
                    "title": "Task One",
                    "task_context": "Do something",
                    "requirements": [{"id": "R1", "desc": "Complete it"}],
                }
            ],
        }
    ],
}


def test_create_run_request_with_routine_id_only() -> None:
    """CreateRunRequest with only routine_id is valid."""
    req = CreateRunRequest(routine_id="my-routine", repo_name="proj-1", branch="main")
    assert req.routine_id == "my-routine"
    assert req.routine_embedded is None


def test_create_run_request_with_routine_embedded_only() -> None:
    """CreateRunRequest with only routine_embedded is valid."""
    req = CreateRunRequest(
        repo_name="proj-1",
        branch="main",
        routine_embedded=VALID_EMBEDDED_ROUTINE,
    )
    assert req.routine_id is None
    assert req.routine_embedded == VALID_EMBEDDED_ROUTINE


def test_create_run_request_with_both_raises() -> None:
    """CreateRunRequest with both routine_id and routine_embedded raises ValueError."""
    with pytest.raises(
        ValidationError, match="routine_id.*routine_embedded|routine_embedded.*routine_id"
    ):
        CreateRunRequest(
            routine_id="my-routine",
            repo_name="proj-1",
            branch="main",
            routine_embedded=VALID_EMBEDDED_ROUTINE,
        )


def test_create_run_request_with_neither_raises() -> None:
    """CreateRunRequest with neither routine_id nor routine_embedded raises ValueError."""
    with pytest.raises(
        ValidationError, match="routine_id.*routine_embedded|routine_embedded.*routine_id"
    ):
        CreateRunRequest(repo_name="proj-1", branch="main")


def test_create_run_request_preserves_config() -> None:
    """Config, agent_runner_type, and agent_runner_config pass through correctly."""
    req = CreateRunRequest(
        routine_id="my-routine",
        repo_name="proj-1",
        branch="main",
        config={"key": "value"},
        agent_runner_type="cli_subprocess",
        agent_runner_config={"model": "test"},
    )
    assert req.config == {"key": "value"}
    assert req.agent_runner_type == "cli_subprocess"
    assert req.agent_runner_config == {"model": "test"}


def test_get_agent_runner_display_name_openhands_local() -> None:
    """OpenHands local agent returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.OPENHANDS_LOCAL) == "OpenHands"


def test_get_agent_runner_display_name_openhands_docker() -> None:
    """OpenHands docker agent returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.OPENHANDS_DOCKER) == "OpenHands Docker"


def test_get_agent_runner_display_name_cli_subprocess() -> None:
    """CLI subprocess agent returns correct display name."""
    assert get_agent_runner_display_name(AgentRunnerType.CLI_SUBPROCESS) == "Claude CLI"


def test_get_agent_runner_display_name_cli_subprocess_uses_command_when_present() -> None:
    """CLI subprocess display uses selected command when available."""
    assert (
        get_agent_runner_display_name(AgentRunnerType.CLI_SUBPROCESS, {"command": "codex"})
        == "codex CLI"
    )


def test_get_agent_runner_display_name_none() -> None:
    """None agent runner type returns 'No Agent Runner'."""
    assert get_agent_runner_display_name(None) == "No Agent Runner"


def test_get_agent_runner_icon_openhands_local() -> None:
    """OpenHands local agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.OPENHANDS_LOCAL) == "openhands"


def test_get_agent_runner_icon_openhands_docker() -> None:
    """OpenHands docker agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.OPENHANDS_DOCKER) == "docker"


def test_get_agent_runner_icon_cli_subprocess() -> None:
    """CLI subprocess agent returns correct icon."""
    assert get_agent_runner_icon(AgentRunnerType.CLI_SUBPROCESS) == "cli"


def test_get_agent_runner_icon_none() -> None:
    """None agent runner type returns 'none' icon."""
    assert get_agent_runner_icon(None) == "none"


def test_action_log_schemas_include_cache_creation_tokens() -> None:
    metrics = TurnMetricsSchema(cache_creation_tokens=11)
    action_log = ActionLogSchema(total_cache_creation_tokens=22)

    assert metrics.cache_creation_tokens == 11
    assert action_log.total_cache_creation_tokens == 22


def test_run_trace_response_includes_attempt_metadata_and_action_log() -> None:
    attempt = Attempt(
        id="attempt-1",
        attempt_num=1,
        builder_prompt="Build it",
        verifier_prompt="Verify it",
        verifier_comment="Looks good",
        outcome="passed",
        metrics=AttemptMetrics(
            tokens_read=100,
            tokens_write=20,
            tokens_cache=5,
            duration_ms=1234,
            num_actions=2,
        ),
        token_usage_by_model=[
            ModelTokenUsage(
                model="test-model",
                input_tokens=100,
                output_tokens=20,
                cache_read_tokens=5,
                cache_creation_tokens=7,
                cost_per_m_input=1.0,
            )
        ],
        action_log=ActionLog(
            entries=[
                ActionLogEntry(
                    sequence_num=1,
                    kind=ActionEntryKind.ASSISTANT_TEXT,
                    text="done",
                    metrics=TurnMetrics(
                        input_tokens=100,
                        output_tokens=20,
                        cache_read_tokens=5,
                        cache_creation_tokens=7,
                        cost_usd=0.01,
                    ),
                )
            ],
            agent_model="test-model",
            total_turns=1,
            total_input_tokens=100,
            total_output_tokens=20,
            total_cache_read_tokens=5,
            total_cache_creation_tokens=7,
        ),
    )
    task = TaskState(
        id="task-1",
        config_id="T-01",
        title="Task One",
        status=TaskStatus.COMPLETED,
        attempts=[attempt],
        current_attempt=1,
        max_attempts=3,
    )
    run = Run(
        id="run-1",
        repo_name="repo",
        status=RunStatus.COMPLETED,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                title="Step One",
                completed=True,
                tasks=[task],
            )
        ],
        total_tokens_read=100,
        total_tokens_write=20,
        total_tokens_cache=5,
        total_duration_ms=1234,
        total_num_actions=2,
        token_usage_by_model=[
            ModelTokenUsage(
                model="test-model",
                input_tokens=100,
                output_tokens=20,
                cache_read_tokens=5,
                cache_creation_tokens=7,
                cost_per_m_input=1.0,
            )
        ],
    )

    trace = run_to_trace_response(run)

    assert trace.run_id == "run-1"
    assert trace.token_usage_by_model[0].cache_creation_tokens == 7
    assert len(trace.attempts) == 1
    trace_attempt = trace.attempts[0]
    assert trace_attempt.step_id == "step-1"
    assert trace_attempt.task_id == "task-1"
    assert [phase.phase for phase in trace_attempt.phases] == ["builder", "verifier"]
    assert trace_attempt.phases[0].message_count == 1
    assert trace_attempt.phases[0].action_sequence_start == 1
    assert trace_attempt.phases[1].note == "Looks good"
    assert trace_attempt.attempt.metrics["num_actions"] == 2
    assert trace_attempt.attempt.token_usage_by_model[0].cache_creation_tokens == 7
    assert trace_attempt.action_log is not None
    assert trace_attempt.action_log.total_cache_creation_tokens == 7
    assert trace_attempt.action_log.entries[0].metrics is not None
    assert trace_attempt.action_log.entries[0].metrics.cache_creation_tokens == 7
