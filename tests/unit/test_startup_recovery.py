"""Tests for startup recovery helpers and continue semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

from orchestrator.api.app import (
    _is_startup_recoverable_pause_reason,
    _run_startup_recovery,
    _topological_sort_children_first,
)
from orchestrator.config import (
    AgentRunnerType,
    ChecklistStatus,
    Priority,
    RunStatus,
    TaskStatus,
)
from orchestrator.config.models import RequirementConfig, RoutineConfig, StepConfig, TaskConfig
from orchestrator.db import (
    RunRepository,
    create_engine,
    create_session_factory,
    create_wired_event_store_v2,
    init_db,
)
from orchestrator.db.access.mutations import save_run
from orchestrator.state.factory import create_run_from_routine
from orchestrator.state import Attempt
from orchestrator.workflow import LocalAutoVerifyRunner, PersistentEventEmitter
from orchestrator.workflow.service import WorkflowService


class _NoopStartupMonitor:
    def __init__(self) -> None:
        self.called = False

    async def recover_active_runs_on_startup(self) -> list[str]:
        self.called = True
        return []


class _RecordingExecutor:
    def __init__(self) -> None:
        self.spawned: list[tuple[str, AgentRunnerType, dict[str, Any]]] = []

    def is_running(self, _run_id: str) -> bool:
        return False

    def spawn_for_run(
        self,
        run_id: str,
        agent_runner_type: AgentRunnerType,
        agent_runner_config: dict[str, Any],
    ) -> bool:
        self.spawned.append((run_id, agent_runner_type, agent_runner_config))
        return True


def test_startup_recovery_includes_executor_not_started() -> None:
    assert _is_startup_recoverable_pause_reason("server_shutdown") is True
    assert _is_startup_recoverable_pause_reason("agent_not_running_on_startup") is False
    assert _is_startup_recoverable_pause_reason("executor_not_started") is True
    assert _is_startup_recoverable_pause_reason("manual") is False
    assert _is_startup_recoverable_pause_reason(None) is False


def test_startup_recovery_accepts_parent_prefixed_reasons() -> None:
    """Cascade pauses (parent_X) must be recoverable when the underlying reason is."""
    assert _is_startup_recoverable_pause_reason("parent_server_shutdown") is True
    assert _is_startup_recoverable_pause_reason("parent_executor_not_started") is True
    assert _is_startup_recoverable_pause_reason("parent_agent_not_running_on_startup") is False
    assert _is_startup_recoverable_pause_reason("parent_manual_pause") is False
    assert _is_startup_recoverable_pause_reason("parent_paused_manual") is False
    assert _is_startup_recoverable_pause_reason("parent_escalated_requirement") is False
    assert _is_startup_recoverable_pause_reason("parent_awaiting_clarification") is False
    assert _is_startup_recoverable_pause_reason("parent_cancel") is False


def _stub_run(run_id: str, parent_run_id: str | None = None) -> Any:
    """Minimal stand-in for orchestrator.state.models.Run for sort tests."""
    return SimpleNamespace(id=run_id, parent_run_id=parent_run_id)


def test_topological_sort_children_first_orders_descendants_first() -> None:
    parent = _stub_run("p")
    child_a = _stub_run("a", parent_run_id="p")
    child_b = _stub_run("b", parent_run_id="p")
    grandchild = _stub_run("g", parent_run_id="a")

    ordered = _topological_sort_children_first([parent, child_a, child_b, grandchild])
    positions = {r.id: i for i, r in enumerate(ordered)}

    assert positions["g"] < positions["a"]
    assert positions["a"] < positions["p"]
    assert positions["b"] < positions["p"]


def test_topological_sort_children_first_handles_external_parent() -> None:
    """A child whose parent is not in the input set is treated as a root."""
    orphan_child = _stub_run("c", parent_run_id="external-parent-not-in-set")
    standalone = _stub_run("s")

    ordered = _topological_sort_children_first([orphan_child, standalone])

    assert {r.id for r in ordered} == {"c", "s"}


def test_topological_sort_children_first_preserves_empty_input() -> None:
    assert _topological_sort_children_first([]) == []


@pytest.mark.asyncio
async def test_deferred_startup_recovery_resumes_restart_paused_run() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    routine = RoutineConfig(
        id="deferred-recovery-routine",
        name="Deferred Recovery Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do the work",
                        requirements=[RequirementConfig(id="R1", desc="Complete the work")],
                    )
                ],
            )
        ],
    )

    async def service_factory(session: Any) -> WorkflowService:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        emitter = PersistentEventEmitter(event_store)
        return WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

    async with session_factory() as session:
        repo = RunRepository(session)
        run = create_run_from_routine(
            routine=routine,
            repo_name="deferred-recovery-repo",
            source_branch="main",
        )
        run.routine_embedded = routine.model_dump(mode="json")
        run.agent_runner_type = AgentRunnerType.CODEX_SERVER
        run.agent_runner_config = {"model": "gpt-5.4-mini"}
        run.status = RunStatus.PAUSED
        run.pause_reason = "server_shutdown"
        run.worktree_enabled = False

        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
        task.attempts[0].outcome = "paused"
        task.attempts[0].paused_at = datetime.now(timezone.utc)

        await save_run(repo.session, run)
        await session.commit()
        run_id = run.id

    monitor = _NoopStartupMonitor()
    executor = _RecordingExecutor()
    app = SimpleNamespace(
        state=SimpleNamespace(
            session_factory=session_factory,
            global_config=SimpleNamespace(),
            runner_monitor=monitor,
            runner_executor=executor,
            service_factory=service_factory,
        )
    )

    await _run_startup_recovery(cast(Any, app))

    async with session_factory() as session:
        recovered = await RunRepository(session).get(run_id)

    assert monitor.called is True
    assert recovered.status == RunStatus.ACTIVE
    assert recovered.pause_reason is None
    assert executor.spawned == [(run_id, AgentRunnerType.CODEX_SERVER, {"model": "gpt-5.4-mini"})]

    await engine.dispose()


@pytest.mark.asyncio
async def test_startup_recovery_resumes_cascade_child_before_parent() -> None:
    """End-to-end: parent paused as server_shutdown, child as parent_server_shutdown.

    Before the fix the child was filtered out of the recovery allow list and
    the parent woke up to a non-terminal blocking child. After the fix both
    are recovered, and the child is resumed before the parent so the parent's
    oversight observes an ACTIVE child rather than a paused one.
    """
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    routine = RoutineConfig(
        id="cascade-recovery-routine",
        name="Cascade Recovery Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do the work",
                        requirements=[RequirementConfig(id="R1", desc="Complete the work")],
                    )
                ],
            )
        ],
    )

    async def service_factory(session: Any) -> WorkflowService:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        emitter = PersistentEventEmitter(event_store)
        return WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

    def _build_paused_run(repo_name: str, pause_reason: str) -> Any:
        run = create_run_from_routine(
            routine=routine,
            repo_name=repo_name,
            source_branch="main",
        )
        run.routine_embedded = routine.model_dump(mode="json")
        run.agent_runner_type = AgentRunnerType.CODEX_SERVER
        run.agent_runner_config = {"model": "gpt-5.4-mini"}
        run.status = RunStatus.PAUSED
        run.pause_reason = pause_reason
        run.worktree_enabled = False
        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
        task.attempts[0].outcome = "paused"
        task.attempts[0].paused_at = datetime.now(timezone.utc)
        return run

    async with session_factory() as session:
        repo = RunRepository(session)

        parent_run = _build_paused_run("parent-repo", "server_shutdown")
        await save_run(repo.session, parent_run)

        child_run = _build_paused_run("child-repo", "parent_server_shutdown")
        child_run.parent_run_id = parent_run.id
        await save_run(repo.session, child_run)

        await session.commit()
        parent_id = parent_run.id
        child_id = child_run.id

    monitor = _NoopStartupMonitor()
    executor = _RecordingExecutor()
    app = SimpleNamespace(
        state=SimpleNamespace(
            session_factory=session_factory,
            global_config=SimpleNamespace(),
            runner_monitor=monitor,
            runner_executor=executor,
            service_factory=service_factory,
        )
    )

    await _run_startup_recovery(cast(Any, app))

    async with session_factory() as session:
        recovered_parent = await RunRepository(session).get(parent_id)
        recovered_child = await RunRepository(session).get(child_id)

    assert recovered_parent.status == RunStatus.ACTIVE
    assert recovered_parent.pause_reason is None
    assert recovered_child.status == RunStatus.ACTIVE
    assert recovered_child.pause_reason is None

    spawned_ids = [entry[0] for entry in executor.spawned]
    assert child_id in spawned_ids
    assert parent_id in spawned_ids
    assert spawned_ids.index(child_id) < spawned_ids.index(parent_id), (
        f"child must be resumed before parent; got order {spawned_ids}"
    )

    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_resume_run_continue_preserves_current_phase_state() -> None:
    engine = create_engine(":memory:")
    await init_db(engine)
    session_factory = create_session_factory(engine)

    routine = RoutineConfig(
        id="resume-continue-routine",
        name="Resume Continue Routine",
        steps=[
            StepConfig(
                id="S-01",
                title="Step 1",
                tasks=[
                    TaskConfig(
                        id="T-01",
                        title="Task 1",
                        task_context="Do the work",
                        requirements=[RequirementConfig(id="R1", desc="Complete the work")],
                    )
                ],
            )
        ],
    )

    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = create_wired_event_store_v2(session)
        emitter = PersistentEventEmitter(event_store)
        service = WorkflowService(
            session=session,
            repo=repo,
            event_store_v2=event_store,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
        )

        run = create_run_from_routine(
            routine=routine,
            repo_name="resume-continue-repo",
            source_branch="main",
        )
        run.routine_embedded = routine.model_dump(mode="json")
        run.agent_runner_type = AgentRunnerType.CODEX_SERVER
        run.agent_runner_config = {"model": "gpt-5.4-mini"}
        run.status = RunStatus.PAUSED
        run.pause_reason = "executor_not_started"

        task = run.steps[0].tasks[0]
        task.status = TaskStatus.BUILDING
        task.checklist[0].status = ChecklistStatus.DONE
        task.checklist[0].note = "partial progress retained"
        task.checklist[0].priority = Priority.CRITICAL
        task.attempts.append(Attempt(attempt_num=1, started_at=datetime.now(timezone.utc)))
        attempt = task.attempts[0]
        attempt.outcome = "paused"
        attempt.paused_at = datetime.now(timezone.utc)

        await save_run(repo.session, run)
        await session.commit()

        resumed = await service.apply_resume_run(run.id, resume_strategy="continue")
        await session.commit()

        resumed_task = resumed.steps[0].tasks[0]
        resumed_attempt = resumed_task.attempts[-1]

        assert resumed.status == RunStatus.ACTIVE
        assert resumed.pause_reason is None
        assert resumed_task.status == TaskStatus.BUILDING
        assert resumed_task.checklist[0].status == ChecklistStatus.DONE
        assert resumed_task.checklist[0].note == "partial progress retained"
        assert resumed_attempt.outcome is None
        assert resumed_attempt.paused_at is None

    await engine.dispose()
