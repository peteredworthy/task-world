"""Unit tests for verifier model pinning.

Verifies that:
- Run creation stores verifier model from agent_config
- Verifier uses the pinned model from run state
- Changing agent_config after creation doesn't affect the pinned model
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.config.enums import AgentRunnerType, TaskStatus
from orchestrator.state.models import Run, TaskState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor() -> AgentRunnerExecutor:
    """Create an AgentRunnerExecutor with no DB session and agent spawning disabled."""
    return AgentRunnerExecutor(session_factory=None, spawn_agents=False)  # type: ignore[arg-type]


def _make_run(
    agent_type: AgentRunnerType = AgentRunnerType.CLAUDE_SDK,
    agent_config: dict[str, Any] | None = None,
    verifier_model: str | None = None,
) -> Run:
    """Create a minimal Run with the given config."""
    return Run(
        id="run-1",
        repo_name="test-repo",
        agent_type=agent_type,
        agent_config=agent_config or {},
        verifier_model=verifier_model,
        worktree_path="/tmp/worktree",
    )


def _make_task_state(status: TaskStatus = TaskStatus.VERIFYING) -> TaskState:
    """Create a minimal TaskState in VERIFYING status."""
    return TaskState(
        id="task-1",
        config_id="task-cfg-1",
        title="Test Task",
        status=status,
    )


# ---------------------------------------------------------------------------
# Unit tests: Run state model
# ---------------------------------------------------------------------------


def test_run_verifier_model_defaults_to_none() -> None:
    """Run.verifier_model defaults to None for backwards compatibility."""
    run = Run(id="r1", repo_name="repo")
    assert run.verifier_model is None


def test_run_verifier_model_can_be_set() -> None:
    """Run.verifier_model can be set to a model string."""
    run = Run(id="r1", repo_name="repo", verifier_model="claude-opus-4-5")
    assert run.verifier_model == "claude-opus-4-5"


# ---------------------------------------------------------------------------
# Unit tests: executor _handle_verification uses pinned model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifier_uses_pinned_model_not_agent_config() -> None:
    """_handle_verification uses run.verifier_model, not agent_config['model']."""
    executor = _make_executor()

    # Run has verifier_model pinned to opus; agent_config has sonnet
    run = _make_run(
        agent_config={"model": "claude-sonnet-4-5"},
        verifier_model="claude-opus-4-5",
    )
    task_state = _make_task_state()

    # task_config with a rubric so LLM verification is triggered
    task_config = MagicMock()
    task_config.verifier.rubric = ["Does the implementation pass all tests?"]

    captured_configs: list[dict[str, Any]] = []

    def _fake_create_agent(
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        run_id: str | None = None,
        phase: str = "building",
    ) -> MagicMock:
        captured_configs.append(dict(agent_config))
        agent = MagicMock()
        agent.execute = AsyncMock(return_value=MagicMock(success=True, output_lines=[], error=None))
        return agent

    service = AsyncMock()

    with patch.object(executor, "_create_agent", side_effect=_fake_create_agent):
        with patch(
            "orchestrator.workflow.prompts.generate_verifier_prompt",
            return_value=MagicMock(system="sys", user="usr"),
        ):
            # Patch _store_attempt_prompt and related methods
            with patch.object(executor, "_store_attempt_prompt", new=AsyncMock()):
                with patch.object(executor, "_store_attempt_output", new=AsyncMock()):
                    with patch.object(executor, "_store_attempt_metrics", new=AsyncMock()):
                        with patch.object(executor, "_emit_log_event", new=AsyncMock()):
                            await executor._handle_verification(
                                run=run,
                                task_state=task_state,
                                task_config=task_config,
                                service=service,
                                agent_type=AgentRunnerType.CLAUDE_SDK,
                                agent_config={"model": "claude-sonnet-4-5"},
                            )

    assert len(captured_configs) == 1
    # Must use the pinned verifier_model (opus), not the agent_config model (sonnet)
    assert captured_configs[0]["model"] == "claude-opus-4-5"


@pytest.mark.asyncio
async def test_verifier_uses_agent_config_when_no_pinned_model() -> None:
    """When run.verifier_model is None, agent_config['model'] is used as-is."""
    executor = _make_executor()

    # No pinned model
    run = _make_run(
        agent_config={"model": "claude-sonnet-4-5"},
        verifier_model=None,
    )
    task_state = _make_task_state()

    task_config = MagicMock()
    task_config.verifier.rubric = ["Check implementation."]

    captured_configs: list[dict[str, Any]] = []

    def _fake_create_agent(
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        run_id: str | None = None,
        phase: str = "building",
    ) -> MagicMock:
        captured_configs.append(dict(agent_config))
        agent = MagicMock()
        agent.execute = AsyncMock(return_value=MagicMock(success=True, output_lines=[], error=None))
        return agent

    service = AsyncMock()

    with patch.object(executor, "_create_agent", side_effect=_fake_create_agent):
        with patch(
            "orchestrator.workflow.prompts.generate_verifier_prompt",
            return_value=MagicMock(system="sys", user="usr"),
        ):
            with patch.object(executor, "_store_attempt_prompt", new=AsyncMock()):
                with patch.object(executor, "_store_attempt_output", new=AsyncMock()):
                    with patch.object(executor, "_store_attempt_metrics", new=AsyncMock()):
                        with patch.object(executor, "_emit_log_event", new=AsyncMock()):
                            await executor._handle_verification(
                                run=run,
                                task_state=task_state,
                                task_config=task_config,
                                service=service,
                                agent_type=AgentRunnerType.CLAUDE_SDK,
                                agent_config={"model": "claude-sonnet-4-5"},
                            )

    assert len(captured_configs) == 1
    # No pinned model, so agent_config model is passed through unchanged
    assert captured_configs[0]["model"] == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_changing_agent_config_after_creation_does_not_affect_verifier() -> None:
    """Pinned verifier_model is immutable: even if agent_config dict changes, verifier uses pin."""
    executor = _make_executor()

    run = _make_run(
        agent_config={"model": "claude-sonnet-4-5"},
        verifier_model="claude-opus-4-5",
    )
    task_state = _make_task_state()
    task_config = MagicMock()
    task_config.verifier.rubric = ["Check."]

    # Simulate post-creation change to agent_config
    run.agent_config = {"model": "claude-haiku-4-5"}  # Changed!

    captured_configs: list[dict[str, Any]] = []

    def _fake_create_agent(
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        run_id: str | None = None,
        phase: str = "building",
    ) -> MagicMock:
        captured_configs.append(dict(agent_config))
        agent = MagicMock()
        agent.execute = AsyncMock(return_value=MagicMock(success=True, output_lines=[], error=None))
        return agent

    service = AsyncMock()

    with patch.object(executor, "_create_agent", side_effect=_fake_create_agent):
        with patch(
            "orchestrator.workflow.prompts.generate_verifier_prompt",
            return_value=MagicMock(system="sys", user="usr"),
        ):
            with patch.object(executor, "_store_attempt_prompt", new=AsyncMock()):
                with patch.object(executor, "_store_attempt_output", new=AsyncMock()):
                    with patch.object(executor, "_store_attempt_metrics", new=AsyncMock()):
                        with patch.object(executor, "_emit_log_event", new=AsyncMock()):
                            await executor._handle_verification(
                                run=run,
                                task_state=task_state,
                                task_config=task_config,
                                service=service,
                                agent_type=AgentRunnerType.CLAUDE_SDK,
                                # Pass the current (changed) agent_config
                                agent_config=run.agent_config,
                            )

    assert len(captured_configs) == 1
    # Verifier must still use the pinned opus model, ignoring the haiku change
    assert captured_configs[0]["model"] == "claude-opus-4-5"
