"""Integration tests: executor loop never leaves a run ACTIVE after exit.

These tests run the real ``_run_agent_loop`` against a real in-memory DB.
For every ``NoTaskReason`` path, the loop hits ``_find_next_task`` **before**
``_execute_task``, so if the DB state triggers a NoTaskReason the agent is
never instantiated — no mocks needed.

The pure unit tests in ``test_executor_state_machine.py`` verify the decision
logic (``resolve_no_task_action``).  These tests verify the loop actually
uses it and acts on the result.  If someone adds a new ``break`` that
bypasses ``resolve_no_task_action``, or ignores the returned action, these
tests catch it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.app import create_app
from orchestrator.config.enums import (
    AgentRunnerType,
    GateType,
    RoutineSource,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.models import GateConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import init_db
from orchestrator.db import RunRepository
from orchestrator.runners.executor import AgentRunnerExecutor, NoTaskReason
from orchestrator.state.factory import create_run_from_routine
from orchestrator.workflow.service import WorkflowService

FIXTURES = Path(__file__).parent.parent / "fixtures" / "routines"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _await_agent_loop(executor: AgentRunnerExecutor, run_id: str) -> None:
    """Wait for the executor's background agent-loop task to finish."""
    task = executor._running_tasks.get(run_id)
    if task is not None:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    for _tid, t in list(executor._running_tasks.items()):
        if not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass


def _make_service_args(session: AsyncSession) -> dict:
    from orchestrator.db import EventStore
    from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner
    from orchestrator.workflow.event_logger import PersistentEventEmitter

    repo = RunRepository(session)
    event_store = EventStore(session)
    emitter = PersistentEventEmitter(event_store)
    return dict(
        session=session,
        repo=repo,
        event_store=event_store,
        event_emitter=emitter,
        auto_verify_runner=LocalAutoVerifyRunner(),
    )


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


async def _create_active_run(
    session_factory: async_sessionmaker[AsyncSession],
    routine: RoutineConfig,
) -> str:
    """Create a run in the DB as ACTIVE with routine_embedded set.

    Returns the run_id.
    """
    async with session_factory() as session:
        service = WorkflowService(**_make_service_args(session))
        run = create_run_from_routine(
            routine=routine,
            repo_name="test-project",
            source_branch="main",
            routine_source=RoutineSource.LOCAL,
        )
        run.routine_embedded = routine.model_dump(mode="json")
        run.agent_type = AgentRunnerType.CLI_SUBPROCESS
        run.agent_config = {}
        run = await service.create_run(run)
        run_id = run.id

        # Start the run to make it ACTIVE
        await service.start_run(run_id)
        await session.commit()
        return run_id


async def _mutate_run_for_reason(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    reason: NoTaskReason,
) -> None:
    """Mutate the run's task/step state in DB to trigger the given reason."""
    async with session_factory() as session:
        repo = RunRepository(session)
        run = await repo.get(run_id)

        if reason == NoTaskReason.ALL_COMPLETE:
            for step in run.steps:
                step.completed = True
                for task in step.tasks:
                    task.status = TaskStatus.COMPLETED
        elif reason == NoTaskReason.BLOCKED_BY_GATE:
            # Gate is set via routine_embedded — no mutation needed,
            # the factory already includes a gate. Task stays PENDING.
            pass
        elif reason == NoTaskReason.PENDING_USER_ACTION:
            run.steps[0].tasks[0].status = TaskStatus.PENDING_USER_ACTION
        elif reason == NoTaskReason.NO_ACTIONABLE_TASKS:
            for task in run.steps[0].tasks:
                task.status = TaskStatus.COMPLETED
            run.steps[0].completed = False

        await repo.save(run)
        await session.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create test app with in-memory database."""
    app = create_app(
        db_path=":memory:",
        routine_dirs=[(FIXTURES, RoutineSource.LOCAL)],
    )
    await init_db(app.state.engine)
    yield app
    await app.state.engine.dispose()


@pytest.fixture
async def session_factory(app: FastAPI) -> async_sessionmaker[AsyncSession]:
    sf: async_sessionmaker[AsyncSession] = app.state.session_factory
    return sf


# ---------------------------------------------------------------------------
# Expected post-loop states
# ---------------------------------------------------------------------------

# FAN_OUT_IN_PROGRESS is no longer reachable from _find_next_task because
# FAN_OUT_RUNNING tasks are now returned as actionable tasks for re-execution.
_UNREACHABLE_REASONS = {NoTaskReason.FAN_OUT_IN_PROGRESS}

EXPECTED_POST_LOOP_STATE: dict[NoTaskReason, tuple[RunStatus, str | None]] = {
    NoTaskReason.ALL_COMPLETE: (RunStatus.COMPLETED, None),
    NoTaskReason.BLOCKED_BY_GATE: (RunStatus.PAUSED, "awaiting_approval"),
    NoTaskReason.PENDING_USER_ACTION: (RunStatus.PAUSED, "awaiting_user_input"),
    NoTaskReason.NO_ACTIONABLE_TASKS: (RunStatus.PAUSED, "no_actionable_tasks"),
}

# Map reason → routine factory (BLOCKED_BY_GATE needs a gate in the routine)
_ROUTINE_FOR_REASON: dict[NoTaskReason, RoutineConfig] = {
    NoTaskReason.BLOCKED_BY_GATE: _minimal_routine(gate=GateConfig(type=GateType.HUMAN_APPROVAL)),
}


def _routine_for_reason(reason: NoTaskReason) -> RoutineConfig:
    return _ROUTINE_FOR_REASON.get(reason, _minimal_routine())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExecutorLoopNeverLeavesActive:
    """Integration: real loop, real DB, no agents."""

    def test_all_reasons_covered(self) -> None:
        assert set(EXPECTED_POST_LOOP_STATE) | _UNREACHABLE_REASONS == set(NoTaskReason)

    @pytest.mark.parametrize("reason", [r for r in NoTaskReason if r not in _UNREACHABLE_REASONS])
    async def test_run_not_active_after_loop(
        self,
        reason: NoTaskReason,
        app: FastAPI,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        routine = _routine_for_reason(reason)

        # 1. Create ACTIVE run
        run_id = await _create_active_run(session_factory, routine)

        # 2. Mutate DB state to trigger the desired reason
        await _mutate_run_for_reason(session_factory, run_id, reason)

        # 3. Spawn executor — it will read DB, hit _find_next_task, and exit
        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            spawn_agents=True,
        )
        executor.spawn_for_run(run_id, AgentRunnerType.CLI_SUBPROCESS, {})

        # 4. Wait for loop to finish
        await _await_agent_loop(executor, run_id)

        # 5. Read final state from DB
        async with session_factory() as session:
            run = await RunRepository(session).get(run_id)

        # THE INVARIANT: run is never left ACTIVE
        assert run.status != RunStatus.ACTIVE, (
            f"Run left ACTIVE after loop exit for {reason.value}! This is the death-loop bug."
        )

        # Verify specific expected state
        expected_status, expected_pause_reason = EXPECTED_POST_LOOP_STATE[reason]
        assert run.status == expected_status, (
            f"For {reason.value}: expected status={expected_status.value}, got {run.status.value}"
        )
        if expected_pause_reason is not None:
            assert run.pause_reason == expected_pause_reason, (
                f"For {reason.value}: expected pause_reason={expected_pause_reason!r}, "
                f"got {run.pause_reason!r}"
            )

        # Executor cleaned up
        assert run_id not in executor._running_tasks
        assert run_id not in executor._heartbeats

    async def test_heartbeat_cleared_after_loop(
        self,
        app: FastAPI,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Heartbeat dict is cleaned up after loop exits."""
        routine = _minimal_routine()
        run_id = await _create_active_run(session_factory, routine)

        # Make all tasks complete so the loop exits quickly
        await _mutate_run_for_reason(session_factory, run_id, NoTaskReason.ALL_COMPLETE)

        executor = AgentRunnerExecutor(
            session_factory=session_factory,
            spawn_agents=True,
        )
        executor.spawn_for_run(run_id, AgentRunnerType.CLI_SUBPROCESS, {})
        await _await_agent_loop(executor, run_id)

        assert run_id not in executor._heartbeats
        assert not executor.is_running(run_id)
