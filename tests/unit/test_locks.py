"""Tests for task-level pessimistic locking."""

from datetime import timedelta

import pytest

from orchestrator.config.enums import (
    ChecklistStatus,
    Priority,
    RunStatus,
    TaskStatus,
)
from orchestrator.state.models import (
    ChecklistItem,
    Run,
    StepState,
    TaskState,
)
from orchestrator.state.session import SessionStateManager
from orchestrator.workflow.engine import WorkflowEngine
from orchestrator.workflow.locks import (
    InMemoryLockManager,
    LockTimeoutError,
    TaskLockedError,
)
from tests.conftest import CollectingEmitter, FakeClock


# ---------- InMemoryLockManager unit tests ----------


class TestInMemoryLockManager:
    """Tests for the InMemoryLockManager in isolation."""

    def test_acquire_succeeds_on_unlocked_task(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        assert manager.acquire("task-1", "agent-a", clock.now()) is True

    def test_acquire_fails_when_locked_by_different_agent(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())
        assert manager.acquire("task-1", "agent-b", clock.now()) is False

    def test_acquire_succeeds_when_lock_has_expired(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        # Advance past timeout
        clock.advance(timedelta(minutes=6))
        assert manager.acquire("task-1", "agent-b", clock.now()) is True

    def test_acquire_succeeds_when_same_agent_reacquires(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        # Same agent can re-acquire (refresh the lock)
        clock.advance(timedelta(minutes=2))
        assert manager.acquire("task-1", "agent-a", clock.now()) is True

    def test_release_clears_lock(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        assert manager.release("task-1", "agent-a") is True
        # After release, another agent can acquire
        assert manager.acquire("task-1", "agent-b", clock.now()) is True

    def test_release_returns_false_if_not_locked(self) -> None:
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        assert manager.release("task-1", "agent-a") is False

    def test_release_returns_false_if_locked_by_different_agent(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        assert manager.release("task-1", "agent-b") is False
        # Original lock is still held
        assert manager.is_locked("task-1", clock.now()) is True

    def test_is_locked_returns_true_for_active_lock(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        assert manager.is_locked("task-1", clock.now()) is True

    def test_is_locked_returns_false_for_unlocked_task(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        assert manager.is_locked("task-1", clock.now()) is False

    def test_is_locked_returns_false_for_expired_lock(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        clock.advance(timedelta(minutes=6))
        assert manager.is_locked("task-1", clock.now()) is False

    def test_is_locked_returns_true_within_timeout(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(minutes=5))
        manager.acquire("task-1", "agent-a", clock.now())

        clock.advance(timedelta(minutes=4))
        assert manager.is_locked("task-1", clock.now()) is True

    def test_custom_timeout(self) -> None:
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(seconds=30))
        manager.acquire("task-1", "agent-a", clock.now())

        # Still locked at 29 seconds
        clock.advance(timedelta(seconds=29))
        assert manager.is_locked("task-1", clock.now()) is True

        # Expired at 31 seconds
        clock.advance(timedelta(seconds=2))
        assert manager.is_locked("task-1", clock.now()) is False

    def test_lock_timeout_very_short(self) -> None:
        """Test that locks expire with very short timeout."""
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(seconds=0.1))
        manager.acquire("task-1", "agent-a", clock.now())

        # Lock is active immediately
        assert manager.is_locked("task-1", clock.now()) is True

        # After 0.1 seconds, lock expires
        clock.advance(timedelta(seconds=0.1))
        assert manager.is_locked("task-1", clock.now()) is False

        # Another agent can now acquire it
        assert manager.acquire("task-1", "agent-b", clock.now()) is True

    def test_lock_expires_between_acquire_and_check(self) -> None:
        """Test lock expiration detection between operations."""
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(seconds=1))

        # Agent A acquires lock
        manager.acquire("task-1", "agent-a", clock.now())
        assert manager.is_locked("task-1", clock.now()) is True

        # Time passes beyond timeout
        clock.advance(timedelta(seconds=2))

        # Lock should no longer be active
        assert manager.is_locked("task-1", clock.now()) is False

        # Agent B can now acquire the expired lock
        assert manager.acquire("task-1", "agent-b", clock.now()) is True

    def test_multiple_locks_with_different_expiration_times(self) -> None:
        """Test that different locks can expire independently."""
        clock = FakeClock()
        manager = InMemoryLockManager(timeout=timedelta(seconds=5))

        # Acquire first lock
        manager.acquire("task-1", "agent-a", clock.now())

        # Advance 2 seconds and acquire second lock
        clock.advance(timedelta(seconds=2))
        manager.acquire("task-2", "agent-b", clock.now())

        # Advance 4 more seconds (task-1 at 6s total, task-2 at 4s)
        clock.advance(timedelta(seconds=4))

        # task-1 should be expired (6s > 5s timeout)
        assert manager.is_locked("task-1", clock.now()) is False

        # task-2 should still be locked (4s < 5s timeout)
        assert manager.is_locked("task-2", clock.now()) is True

        # Advance 2 more seconds (task-2 now at 6s)
        clock.advance(timedelta(seconds=2))

        # Now task-2 should also be expired
        assert manager.is_locked("task-2", clock.now()) is False


# ---------- LockTimeoutError tests ----------


class TestLockTimeoutError:
    """Tests for the LockTimeoutError exception."""

    def test_lock_timeout_error_construction(self) -> None:
        """Test that LockTimeoutError can be constructed with task_id."""
        error = LockTimeoutError("task-123")
        assert error.task_id == "task-123"
        assert str(error) == "Lock on task task-123 has expired"

    def test_lock_timeout_error_can_be_raised_and_caught(self) -> None:
        """Test that LockTimeoutError can be raised and caught."""
        with pytest.raises(LockTimeoutError) as exc_info:
            raise LockTimeoutError("task-456")

        assert exc_info.value.task_id == "task-456"
        assert "task-456" in str(exc_info.value)

    def test_lock_timeout_error_attributes(self) -> None:
        """Test that LockTimeoutError has correct attributes."""
        error = LockTimeoutError("task-abc")
        assert hasattr(error, "task_id")
        assert error.task_id == "task-abc"
        assert isinstance(error, Exception)


# ---------- Engine integration tests ----------


def _make_run(
    run_id: str = "run-1",
    task_id: str = "task-1",
    status: RunStatus = RunStatus.DRAFT,
) -> Run:
    return Run(
        id=run_id,
        repo_name="proj-1",
        source_branch="main",
        status=status,
        steps=[
            StepState(
                id="step-1",
                config_id="S-01",
                tasks=[
                    TaskState(
                        id=task_id,
                        config_id="T-01",
                        checklist=[
                            ChecklistItem(
                                req_id="R1",
                                desc="Requirement 1",
                                priority=Priority.CRITICAL,
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )


def _engine_with_locks(
    run: Run,
    lock_timeout: timedelta = timedelta(minutes=5),
) -> tuple[WorkflowEngine, SessionStateManager, FakeClock, CollectingEmitter, InMemoryLockManager]:
    manager = SessionStateManager()
    manager.add_run(run)
    clock = FakeClock()
    emitter = CollectingEmitter()
    lock_manager = InMemoryLockManager(timeout=lock_timeout)
    engine = WorkflowEngine(manager, clock=clock, emitter=emitter, lock_manager=lock_manager)
    return engine, manager, clock, emitter, lock_manager


class TestEngineWithLocks:
    """Tests for WorkflowEngine with lock_manager enabled."""

    def test_start_task_acquires_lock(self) -> None:
        run = _make_run()
        engine, _, clock, _, lock_manager = _engine_with_locks(run)
        engine.start_run("run-1")

        result = engine.start_task("run-1", "task-1", agent_id="agent-a")
        assert result.success is True
        assert result.new_status == TaskStatus.BUILDING
        # Lock should be held
        assert lock_manager.is_locked("task-1", clock.now()) is True

    def test_start_task_on_locked_task_raises_task_locked_error(self) -> None:
        run = _make_run()
        engine, _, _, _, _lock_manager = _engine_with_locks(run)
        engine.start_run("run-1")

        # First agent acquires the lock
        engine.start_task("run-1", "task-1", agent_id="agent-a")

        # Second agent tries to start the same task -- should raise
        with pytest.raises(TaskLockedError) as exc_info:
            engine.start_task("run-1", "task-1", agent_id="agent-b")

        assert exc_info.value.task_id == "task-1"

    def test_complete_verification_releases_lock(self) -> None:
        run = _make_run()
        engine, _, clock, _, lock_manager = _engine_with_locks(run)
        engine.start_run("run-1")
        engine.start_task("run-1", "task-1", agent_id="agent-a")

        # Mark checklist done with passing grade
        task = run.steps[0].tasks[0]
        for item in task.checklist:
            item.status = ChecklistStatus.DONE
            item.grade = "A"

        engine.submit_for_verification("run-1", "task-1")
        clock.advance(timedelta(minutes=1))
        result = engine.complete_verification("run-1", "task-1", agent_id="agent-a")

        assert result.success is True
        assert result.new_status == TaskStatus.COMPLETED
        # Lock should be released
        assert lock_manager.is_locked("task-1", clock.now()) is False

    def test_start_task_succeeds_after_lock_expires(self) -> None:
        run = _make_run()
        engine, _, _clock, _, _ = _engine_with_locks(run, lock_timeout=timedelta(minutes=5))
        engine.start_run("run-1")

        # First agent acquires the lock
        engine.start_task("run-1", "task-1", agent_id="agent-a")

        # Advance past timeout -- the expired lock means the task transitions
        # to BUILDING, so we can't call start_task again on the same task
        # (it's already BUILDING, not PENDING). Instead we verify that lock
        # acquisition itself succeeds for another agent on a different task.
        # Let's test by creating a fresh scenario:
        run2 = _make_run(run_id="run-2", task_id="task-2")
        engine2, _, clock2, _, lock_manager2 = _engine_with_locks(
            run2, lock_timeout=timedelta(minutes=5)
        )
        engine2.start_run("run-2")

        # Agent-a locks task-2
        engine2.start_task("run-2", "task-2", agent_id="agent-a")

        # Agent-b cannot lock within timeout
        with pytest.raises(TaskLockedError):
            engine2.start_task("run-2", "task-2", agent_id="agent-b")

        # After timeout, lock manager allows re-acquisition
        clock2.advance(timedelta(minutes=6))
        # Direct lock manager check -- the task itself is already in BUILDING
        # so we can't re-start it, but the lock manager should allow acquire
        assert lock_manager2.acquire("task-2", "agent-b", clock2.now()) is True

    def test_engine_without_lock_manager_works_unchanged(self) -> None:
        """Verify backward compatibility -- engine without lock_manager."""
        run = _make_run()
        manager = SessionStateManager()
        manager.add_run(run)
        clock = FakeClock()
        emitter = CollectingEmitter()
        engine = WorkflowEngine(manager, clock=clock, emitter=emitter)

        engine.start_run("run-1")
        result = engine.start_task("run-1", "task-1")
        assert result.success is True
        assert result.new_status == TaskStatus.BUILDING

    def test_revision_keeps_lock_held(self) -> None:
        """When verification triggers a revision (back to BUILDING), lock stays."""
        run = _make_run()
        engine, _, clock, _, lock_manager = _engine_with_locks(run)
        engine.start_run("run-1")
        engine.start_task("run-1", "task-1", agent_id="agent-a")

        # Mark checklist done with failing grade
        task = run.steps[0].tasks[0]
        for item in task.checklist:
            item.status = ChecklistStatus.DONE
            item.grade = "D"

        engine.submit_for_verification("run-1", "task-1")
        result = engine.complete_verification("run-1", "task-1", agent_id="agent-a")

        assert result.success is True
        assert result.new_status == TaskStatus.BUILDING  # Revision
        # Lock should still be held (revision, not terminal)
        assert lock_manager.is_locked("task-1", clock.now()) is True

    def test_failed_task_releases_lock(self) -> None:
        """When a task fails (max attempts), lock is released."""
        run = Run(
            id="run-1",
            repo_name="proj-1",
            source_branch="main",
            status=RunStatus.DRAFT,
            steps=[
                StepState(
                    id="step-1",
                    config_id="S-01",
                    tasks=[
                        TaskState(
                            id="task-1",
                            config_id="T-01",
                            max_attempts=1,
                            checklist=[
                                ChecklistItem(
                                    req_id="R1",
                                    desc="Requirement 1",
                                    priority=Priority.CRITICAL,
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
        engine, _, clock, _, lock_manager = _engine_with_locks(run)
        engine.start_run("run-1")
        engine.start_task("run-1", "task-1", agent_id="agent-a")

        task = run.steps[0].tasks[0]
        for item in task.checklist:
            item.status = ChecklistStatus.DONE
            item.grade = "F"  # Failing, max_attempts=1 -> FAILED

        engine.submit_for_verification("run-1", "task-1")
        result = engine.complete_verification("run-1", "task-1", agent_id="agent-a")

        assert result.success is True
        assert result.new_status == TaskStatus.FAILED
        # Lock released on terminal state
        assert lock_manager.is_locked("task-1", clock.now()) is False
