"""Unit tests for gate-blocked handling in CLI agent and executor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from orchestrator.runners.cli import CLIAgent
from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.runners.types import ExecutionContext
from orchestrator.config.enums import AgentRunnerType, ChecklistStatus, TaskStatus
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow.errors import GateBlockedError


class _NoopService:
    async def update_checklist_item(
        self, run_id: str, task_id: str, req_id: str, status: ChecklistStatus, note: str | None
    ) -> None:
        return

    async def get_task(self, run_id: str, task_id: str) -> Any:
        raise AssertionError("get_task should not be called when agent raises GateBlockedError")

    async def submit_for_verification(self, run_id: str, task_id: str) -> None:
        raise AssertionError(
            "submit_for_verification should not be called when agent raises GateBlockedError"
        )

    async def start_task(self, run_id: str, task_id: str) -> None:
        raise AssertionError("start_task should not be called when task already BUILDING")


class _FakeAgentMonitor:
    def __init__(self) -> None:
        self.calls = 0

    async def on_agent_died(self, **kwargs: Any) -> None:  # noqa: ARG002
        self.calls += 1


class _GateBlockedAgent:
    async def execute(
        self,
        context: ExecutionContext,  # noqa: ARG002
        on_checklist_update: Any,  # noqa: ARG002
        on_submit: Any,  # noqa: ARG002
        on_output: Any = None,  # noqa: ARG002
        on_grade: Any = None,  # noqa: ARG002
        on_agent_metadata: Any = None,  # noqa: ARG002
        on_escalation: Any = None,  # noqa: ARG002
    ) -> Any:
        raise GateBlockedError("checklist", ["R1"])


class _TestExecutor(AgentRunnerExecutor):
    def __init__(self, agent: _GateBlockedAgent, monitor: _FakeAgentMonitor) -> None:
        super().__init__(session_factory=None, spawn_agents=False, agent_monitor=monitor)
        self._agent = agent

    def _create_agent(
        self,
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        run_id: str | None = None,
        phase: str = "building",
    ) -> _GateBlockedAgent:  # noqa: ARG002,E501
        return self._agent

    async def _store_attempt_prompt(
        self,
        run_id: str,
        task_id: str,
        builder_prompt: str | None = None,
        verifier_prompt: str | None = None,
        session: object = None,
    ) -> None:
        return

    async def _store_attempt_output(
        self,
        run_id: str,
        task_id: str,
        output_lines: list[str],
        error: str | None = None,
        action_log: Any = None,
    ) -> None:
        return

    async def _store_attempt_metrics(self, run_id: str, task_id: str, metrics: Any) -> None:
        return

    async def _persist_agent_metadata(self, run_id: str, agent_metadata: dict[str, Any]) -> None:
        return


@pytest.mark.asyncio
async def test_cli_execute_reraises_gate_blocked_error(tmp_path: Path) -> None:
    """CLIAgent.execute should propagate GateBlockedError from on_submit."""
    agent = CLIAgent(command="python3", args=["-c", "print('ok')"])
    context = ExecutionContext(
        run_id="run-1",
        task_id="task-1",
        working_dir=str(tmp_path),
        prompt="Do work",
        requirements=["R1: Requirement"],
    )

    async def on_checklist_update(req_id: str, status: ChecklistStatus, note: str | None) -> None:  # noqa: ARG001
        return

    async def on_submit() -> None:
        raise GateBlockedError("checklist", ["R1"])

    with pytest.raises(GateBlockedError):
        await agent.execute(context, on_checklist_update, on_submit)


@pytest.mark.asyncio
async def test_execute_task_gate_blocked_does_not_call_on_agent_died(tmp_path: Path) -> None:
    """_execute_task should return on GateBlockedError, leaving task BUILDING."""
    routine = RoutineConfig(
        id="routine-1",
        name="Routine",
        steps=[
            StepConfig(
                id="step-1",
                title="Step",
                tasks=[
                    TaskConfig(
                        id="task-config-1",
                        title="Task",
                        task_context="Implement feature",
                        requirements=[RequirementConfig(id="R1", desc="Do the thing")],
                    )
                ],
            )
        ],
    )
    run = create_run_from_routine(
        routine=routine,
        repo_name="repo",
        source_branch="main",
        id_generator=iter(["run-1", "step-state-1", "task-state-1"]).__next__,
    )
    run.routine_embedded = routine.model_dump(mode="json")
    run.worktree_path = str(tmp_path)

    task_state = run.steps[0].tasks[0]
    task_state.status = TaskStatus.BUILDING

    monitor = _FakeAgentMonitor()
    executor = _TestExecutor(agent=_GateBlockedAgent(), monitor=monitor)
    service = _NoopService()

    await executor._execute_task(
        run=run,
        task_state=task_state,
        service=service,
        agent_type=AgentRunnerType.CLI_SUBPROCESS,
        agent_config={},
    )

    assert monitor.calls == 0
    assert task_state.status == TaskStatus.BUILDING
