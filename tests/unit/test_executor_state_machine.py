"""Pure unit tests for executor decision logic.

Tests the ``resolve_no_task_action`` pure function and ``_find_next_task``
method against in-memory Pydantic ``Run`` objects.  No database, no async,
no mocks.

Two completeness guards (``test_all_reasons_have_factory`` and
``test_all_reasons_have_expected_action``) ensure that adding a new
``NoTaskReason`` enum member without updating the test registry causes
immediate test failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import pytest

from orchestrator.config import AgentRunnerType, GateType, RunStatus, TaskStatus
from orchestrator.config.models import (
    GateConfig,
    RoutineConfig,
    StepConfig,
    TaskConfig,
)
from orchestrator.runners.executor import (
    AgentRunnerExecutor,
    NoTaskReason,
    resolve_no_task_action,
)
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state.models import Run

# ---------------------------------------------------------------------------
# Run factories — one per NoTaskReason
# ---------------------------------------------------------------------------


def _minimal_routine(**step_kwargs: object) -> RoutineConfig:
    """Build a RoutineConfig with one step and one task."""
    return RoutineConfig(
        id="test-routine",
        name="Test Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="do something",
                    )
                ],
                **step_kwargs,  # type: ignore[arg-type]
            )
        ],
    )


def _base_run(routine: RoutineConfig | None = None) -> Run:
    """Create a draft Run with routine_embedded set."""
    if routine is None:
        routine = _minimal_routine()
    run = create_run_from_routine(
        routine=routine,
        repo_name="test-project",
        source_branch="main",
    )
    run.routine_embedded = routine.model_dump(mode="json")
    run.agent_runner_type = AgentRunnerType.CLI_SUBPROCESS
    run.status = RunStatus.ACTIVE
    return run


def _make_run_all_complete() -> Run:
    """All steps completed, all tasks completed."""
    run = _base_run()
    for step in run.steps:
        step.completed = True
        for task in step.tasks:
            task.status = TaskStatus.COMPLETED
    return run


def _make_run_all_complete_with_failure() -> Run:
    """All steps completed, but one task failed."""
    run = _base_run()
    for step in run.steps:
        step.completed = True
        for task in step.tasks:
            task.status = TaskStatus.FAILED
    return run


def _make_run_gate_blocked() -> Run:
    """Step has a human_approval gate that hasn't been approved."""
    routine = _minimal_routine(gate=GateConfig(type=GateType.HUMAN_APPROVAL))
    run = _base_run(routine)
    # Task is PENDING, gate is unsatisfied (no human_approval on step)
    return run


def _make_run_pending_user_action() -> Run:
    """A task is waiting for user input."""
    run = _base_run()
    run.steps[0].tasks[0].status = TaskStatus.PENDING_USER_ACTION
    return run


def _make_run_fan_out_running() -> Run:
    """A fan-out task is in progress but no executor is driving it."""
    run = _base_run()
    run.steps[0].tasks[0].status = TaskStatus.FAN_OUT_RUNNING
    return run


def _make_run_no_actionable() -> Run:
    """All tasks in current step are terminal but step not marked completed."""
    run = _base_run()
    run.steps[0].tasks[0].status = TaskStatus.COMPLETED
    run.steps[0].completed = False
    return run


# FAN_OUT_IN_PROGRESS is no longer reachable from _find_next_task because
# FAN_OUT_RUNNING tasks are now returned as actionable (so the executor can
# re-enter _execute_fan_out on resume).  It's kept in NoTaskReason for
# resolve_no_task_action coverage but excluded from _find_next_task tests.
REASON_FACTORIES: dict[NoTaskReason, Callable[[], Run]] = {
    NoTaskReason.ALL_COMPLETE: _make_run_all_complete,
    NoTaskReason.BLOCKED_BY_GATE: _make_run_gate_blocked,
    NoTaskReason.PENDING_USER_ACTION: _make_run_pending_user_action,
    NoTaskReason.NO_ACTIONABLE_TASKS: _make_run_no_actionable,
}

_UNREACHABLE_REASONS = {NoTaskReason.FAN_OUT_IN_PROGRESS}

# ---------------------------------------------------------------------------
# TestFindNextTaskReasons
# ---------------------------------------------------------------------------


class TestFindNextTaskReasons:
    """Pure tests: _find_next_task on in-memory Run objects."""

    def test_all_reasons_have_factory(self) -> None:
        """Every reachable NoTaskReason member must have a factory."""
        assert set(REASON_FACTORIES) | _UNREACHABLE_REASONS == set(NoTaskReason)

    @pytest.mark.parametrize("reason", [r for r in NoTaskReason if r not in _UNREACHABLE_REASONS])
    def test_returns_expected_reason(self, reason: NoTaskReason) -> None:
        run = REASON_FACTORIES[reason]()
        # We need a bare executor for _find_next_task (it's a method).
        # spawn_agents=False, session_factory is unused for this method.
        executor = AgentRunnerExecutor(
            session_factory=None,  # type: ignore[arg-type]
            spawn_agents=False,
        )
        task, actual = executor._find_next_task(run)
        assert task is None, f"Expected no task for {reason}, got task {task}"
        assert actual == reason

    def test_returns_task_when_pending(self) -> None:
        """A pending task should be returned (not a NoTaskReason)."""
        run = _base_run()
        # Default state: task is PENDING, no gate
        executor = AgentRunnerExecutor(
            session_factory=None,  # type: ignore[arg-type]
            spawn_agents=False,
        )
        task, reason = executor._find_next_task(run)
        assert task is not None
        assert reason is None

    def test_returns_task_when_fan_out_running(self) -> None:
        """A FAN_OUT_RUNNING task should be returned so executor re-enters _execute_fan_out."""
        run = _make_run_fan_out_running()
        executor = AgentRunnerExecutor(
            session_factory=None,  # type: ignore[arg-type]
            spawn_agents=False,
        )
        task, reason = executor._find_next_task(run)
        assert task is not None
        assert task.status == TaskStatus.FAN_OUT_RUNNING
        assert reason is None

    def test_returns_task_when_building(self) -> None:
        """A building task should be returned."""
        run = _base_run()
        run.steps[0].tasks[0].status = TaskStatus.BUILDING
        executor = AgentRunnerExecutor(
            session_factory=None,  # type: ignore[arg-type]
            spawn_agents=False,
        )
        task, reason = executor._find_next_task(run)
        assert task is not None
        assert reason is None


# ---------------------------------------------------------------------------
# TestResolveNoTaskAction
# ---------------------------------------------------------------------------

EXPECTED_ACTIONS: dict[NoTaskReason, tuple[str, str | None]] = {
    NoTaskReason.ALL_COMPLETE: ("complete", None),
    NoTaskReason.BLOCKED_BY_GATE: ("pause", "awaiting_approval"),
    NoTaskReason.PENDING_USER_ACTION: ("pause", "awaiting_user_input"),
    NoTaskReason.FAN_OUT_IN_PROGRESS: ("pause", "fan_out_orphaned"),
    NoTaskReason.NO_ACTIONABLE_TASKS: ("pause", "no_actionable_tasks"),
}


class TestResolveNoTaskAction:
    """Pure tests for resolve_no_task_action.

    Core invariant: for every NoTaskReason, the returned action
    would result in a non-ACTIVE run.
    """

    def test_all_reasons_have_expected_action(self) -> None:
        """Every NoTaskReason must have an expected action."""
        assert set(EXPECTED_ACTIONS) == set(NoTaskReason)

    @pytest.mark.parametrize("reason", list(NoTaskReason))
    def test_action_never_leaves_run_active(self, reason: NoTaskReason) -> None:
        """The invariant: every reason produces a non-trivial action."""
        # Use the factory if available, otherwise use a generic run
        factory = REASON_FACTORIES.get(reason)
        run = factory() if factory else _base_run()
        action = resolve_no_task_action(run, reason)
        assert action.kind in ("pause", "complete", "fail")
        if action.kind == "pause":
            assert action.pause_reason is not None, (
                f"Pause action for {reason} must have a pause_reason"
            )

    @pytest.mark.parametrize("reason", list(NoTaskReason))
    def test_action_matches_expected(self, reason: NoTaskReason) -> None:
        factory = REASON_FACTORIES.get(reason)
        run = factory() if factory else _base_run()
        action = resolve_no_task_action(run, reason)
        expected_kind, expected_pause_reason = EXPECTED_ACTIONS[reason]
        assert action.kind == expected_kind, (
            f"For {reason}: expected kind={expected_kind}, got {action.kind}"
        )
        if expected_pause_reason is not None:
            assert action.pause_reason == expected_pause_reason

    def test_all_complete_with_failure_returns_fail(self) -> None:
        """ALL_COMPLETE with a failed task → kind='fail'."""
        run = _make_run_all_complete_with_failure()
        action = resolve_no_task_action(run, NoTaskReason.ALL_COMPLETE)
        assert action.kind == "fail"

    def test_all_complete_but_not_terminal_returns_safety_pause(self) -> None:
        """Edge case: all steps completed=True but run is not ACTIVE → None
        from check_run_completion → safety pause."""
        run = _make_run_all_complete()
        # Force status to PAUSED so check_run_completion returns None
        run.status = RunStatus.PAUSED
        action = resolve_no_task_action(run, NoTaskReason.ALL_COMPLETE)
        assert action.kind == "pause"
        assert action.pause_reason == "all_steps_complete_but_active"


# ---------------------------------------------------------------------------
# TestIsRunning
# ---------------------------------------------------------------------------


class TestIsRunning:
    """Pure tests for is_running() with heartbeat."""

    @pytest.fixture
    def executor(self) -> AgentRunnerExecutor:
        return AgentRunnerExecutor(
            session_factory=None,  # type: ignore[arg-type]
            spawn_agents=False,
        )

    @pytest.mark.parametrize(
        "in_tasks, hb_age_seconds, expected",
        [
            (True, None, True),  # In _running_tasks, no heartbeat
            (True, 200, True),  # In _running_tasks, stale heartbeat (task wins)
            (False, 10, True),  # Not in tasks, recent heartbeat
            (False, 119, True),  # Not in tasks, heartbeat just under threshold
            (False, 121, False),  # Not in tasks, heartbeat just over threshold
            (False, 200, False),  # Not in tasks, stale heartbeat
            (False, None, False),  # Not in tasks, no heartbeat
        ],
    )
    def test_is_running(
        self,
        executor: AgentRunnerExecutor,
        in_tasks: bool,
        hb_age_seconds: float | None,
        expected: bool,
    ) -> None:
        run_id = "test-run"
        if in_tasks:
            # Put a dummy task in _running_tasks
            import asyncio

            loop = asyncio.new_event_loop()
            try:
                dummy = loop.create_future()
                # We can't use a real asyncio.Task here, but _running_tasks
                # just checks `run_id in self._running_tasks`
                executor._running_tasks[run_id] = dummy  # type: ignore[assignment]
            finally:
                loop.close()

        if hb_age_seconds is not None:
            from datetime import timedelta

            executor._heartbeats[run_id] = datetime.now(timezone.utc) - timedelta(
                seconds=hb_age_seconds
            )

        assert executor.is_running(run_id) == expected

        # Cleanup
        executor._running_tasks.pop(run_id, None)
        executor._heartbeats.pop(run_id, None)

    def test_heartbeat_records_timestamp(self, executor: AgentRunnerExecutor) -> None:
        run_id = "test-run"
        assert executor.last_heartbeat(run_id) is None
        executor.heartbeat(run_id)
        ts = executor.last_heartbeat(run_id)
        assert ts is not None
        # Should be very recent
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        assert age < 2.0

    def test_last_heartbeat_none_for_unknown(self, executor: AgentRunnerExecutor) -> None:
        assert executor.last_heartbeat("nonexistent") is None

    def test_heartbeat_updates_on_repeat(self, executor: AgentRunnerExecutor) -> None:
        run_id = "test-run"
        executor.heartbeat(run_id)
        first = executor.last_heartbeat(run_id)
        assert first is not None

        # Small delay to ensure timestamp changes
        import time

        time.sleep(0.01)
        executor.heartbeat(run_id)
        second = executor.last_heartbeat(run_id)
        assert second is not None
        assert second >= first
