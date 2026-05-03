"""Unit tests for executor gate logic.

Tests ``_find_next_task`` and ``_is_step_gate_satisfied`` against in-memory
``Run`` objects.  No database, no HTTP app, no mocks — pure logic tests.

These were extracted from tests/integration/test_api_human_approval.py because
they test internal executor methods rather than the public HTTP API.
"""

from __future__ import annotations

from datetime import datetime, timezone

from orchestrator.config import AgentRunnerType, GateType, RoutineSource, TaskStatus
from orchestrator.config.models import (
    GateConfig,
    RequirementConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.runners.executor import AgentRunnerExecutor, NoTaskReason
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import HumanApproval


def _make_executor() -> AgentRunnerExecutor:
    """Create an executor with no session factory — sufficient for pure logic tests."""
    return AgentRunnerExecutor(
        session_factory=None,  # type: ignore[arg-type]
        spawn_agents=False,
    )


def _make_run_with_human_gate(routine_id: str = "gate-test") -> object:
    """Create an in-memory run with a human_approval gate on step S-01."""
    routine = RoutineConfig(
        id=routine_id,
        name="Gate Test",
        description="Test",
        steps=[
            StepConfig(
                id="S-01",
                title="Gated Step",
                gate=GateConfig(
                    type=GateType.HUMAN_APPROVAL,
                    approval_prompt="Please review",
                ),
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Gated Task",
                        task_context="Work that needs approval first",
                        requirements=[
                            RequirementConfig(id="R1", desc="Do something"),
                        ],
                    )
                ],
            ),
        ],
    )
    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
        routine_source=RoutineSource.EMBEDDED,
    )
    run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    return run


class TestExecutorGateLogic:
    """Tests for _find_next_task and _is_step_gate_satisfied."""

    def test_executor_stops_at_human_approval_gate(self) -> None:
        """_find_next_task returns BLOCKED_BY_GATE when step has unsatisfied human_approval gate."""
        run = _make_run_with_human_gate()
        executor = _make_executor()

        task, reason = executor._find_next_task(run)
        assert task is None
        assert reason == NoTaskReason.BLOCKED_BY_GATE

        # Verify the gate helper directly
        assert executor._is_step_gate_satisfied(run, run.steps[0]) is False

    def test_executor_proceeds_after_gate_approved(self) -> None:
        """After human_approval gate is satisfied, _find_next_task returns the task."""
        run = _make_run_with_human_gate("gate-test-2")
        executor = _make_executor()

        # Before approval: blocked
        task, reason = executor._find_next_task(run)
        assert reason == NoTaskReason.BLOCKED_BY_GATE
        assert task is None

        # Approve the step
        run.steps[0].human_approval = HumanApproval(
            approved_by="reviewer@example.com",
            approved_at=datetime.now(timezone.utc),
            comment="Approved",
        )

        # After approval: not blocked, task returned
        task, reason = executor._find_next_task(run)
        assert reason is None
        assert task is not None
        assert task.config_id == "T-01"

    def test_step_without_gate_not_blocked(self) -> None:
        """Steps without a human_approval gate should not be blocked."""
        routine = RoutineConfig(
            id="no-gate-test",
            name="No Gate Test",
            description="Test",
            steps=[
                StepConfig(
                    id="S-01",
                    title="Normal Step",
                    tasks=[
                        TaskConfig(
                            id="T-01",
                            title="Normal Task",
                            task_context="Just do work",
                            requirements=[
                                RequirementConfig(id="R1", desc="Do something"),
                            ],
                        )
                    ],
                ),
            ],
        )
        run = create_run_from_routine(
            routine=routine,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.EMBEDDED,
        )
        run.routine_embedded = routine.model_dump(mode="json", by_alias=True)
        run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS

        executor = _make_executor()
        task, reason = executor._find_next_task(run)
        assert reason is None
        assert task is not None
        assert task.config_id == "T-01"

    def test_executor_does_not_start_future_step_when_current_waiting_for_user_action(
        self,
    ) -> None:
        """Executor must not select future-step tasks while current step is blocked on clarification."""
        routine = RoutineConfig(
            id="clarification-block-test",
            name="Clarification Block Test",
            description="Test",
            steps=[
                StepConfig(
                    id="S-01",
                    title="Current Step",
                    tasks=[
                        TaskConfig(
                            id="T-01",
                            title="Current Task",
                            task_context="Needs clarification",
                            requirements=[RequirementConfig(id="R1", desc="Do something")],
                        )
                    ],
                ),
                StepConfig(
                    id="S-02",
                    title="Future Step",
                    tasks=[
                        TaskConfig(
                            id="T-01",
                            title="Future Task",
                            task_context="Should not start yet",
                            requirements=[RequirementConfig(id="R1", desc="Do next thing")],
                        )
                    ],
                ),
            ],
        )

        run = create_run_from_routine(
            routine=routine,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.EMBEDDED,
        )
        run.current_step_index = 0
        run.steps[0].tasks[0].status = TaskStatus.PENDING_USER_ACTION
        run.steps[1].tasks[0].status = TaskStatus.PENDING

        executor = _make_executor()
        task, reason = executor._find_next_task(run)

        assert task is None
        assert reason == NoTaskReason.PENDING_USER_ACTION
