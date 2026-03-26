"""RunWorkflow - the single owner of run execution, plus NoTaskReason and LoopAction.

RunWorkflow wraps the executor loop and is created by AgentRunnerExecutor
for each active run.  It:

  1. Registers itself in the active-workflow registry so WorkflowService can
     route external pause/resume/cancel signals through the signal queue.
  2. Calls on_signal() at the top of every iteration to drain and apply
     pending signals before doing any task work.
  3. Contains the main while-True execution loop (previously in
     AgentRunnerExecutor._run_agent_loop).

NoTaskReason and LoopAction define the executor's decision-making for pauses/completions.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Literal

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.workflow.engine.errors import GateBlockedError
from orchestrator.workflow.signals.handlers import build_registry, signal_handler
from orchestrator.workflow.signals.signals import (
    DbSignalTransport,
    SignalQueue,
    SignalTransport,
    WorkflowSignal,
    register_active_run,
    unregister_active_run,
)
from orchestrator.workflow.agent.summary_cache import SummaryCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.config.enums import AgentRunnerType
    from orchestrator.runners import AttemptStore, EventBroadcaster
    from orchestrator.state.models import Run
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


class NoTaskReason(enum.Enum):
    """Why _find_next_task returned no actionable task."""

    ALL_COMPLETE = "all_complete"  # All steps are done
    BLOCKED_BY_GATE = "blocked_by_gate"  # human_approval gate unsatisfied
    PENDING_USER_ACTION = "pending_user_action"  # Waiting on user input
    FAN_OUT_IN_PROGRESS = "fan_out_in_progress"  # Fan-out children running (crash recovery)
    NO_ACTIONABLE_TASKS = "no_actionable_tasks"  # Step has tasks but none actionable


@dataclasses.dataclass(frozen=True)
class LoopAction:
    """What the executor loop should do when _find_next_task returns no task."""

    kind: Literal["pause", "complete", "fail"]
    pause_reason: str | None = None  # for kind="pause"


def resolve_no_task_action(run: Run, reason: NoTaskReason) -> LoopAction:
    """Decide what the executor loop should do for a given NoTaskReason.

    Pure function — no DB, no service, no side effects.  The only
    external call is ``check_run_completion`` which mutates the Run
    in-memory (sets status/completed_at) but performs no I/O.
    """
    if reason == NoTaskReason.BLOCKED_BY_GATE:
        return LoopAction(kind="pause", pause_reason="awaiting_approval")
    if reason == NoTaskReason.PENDING_USER_ACTION:
        return LoopAction(kind="pause", pause_reason="awaiting_user_input")
    if reason == NoTaskReason.FAN_OUT_IN_PROGRESS:
        return LoopAction(kind="pause", pause_reason="fan_out_orphaned")
    if reason == NoTaskReason.NO_ACTIONABLE_TASKS:
        return LoopAction(kind="pause", pause_reason="no_actionable_tasks")
    if reason == NoTaskReason.ALL_COMPLETE:
        from orchestrator.workflow.engine.transitions import check_run_completion

        new_status = check_run_completion(run, datetime.now(timezone.utc))
        if new_status == RunStatus.COMPLETED:
            return LoopAction(kind="complete")
        if new_status == RunStatus.FAILED:
            return LoopAction(kind="fail")
        # Still ACTIVE despite all steps done — shouldn't happen
        return LoopAction(kind="pause", pause_reason="all_steps_complete_but_active")
    # Defensive: unknown reason — pause rather than leave ACTIVE
    return LoopAction(kind="pause", pause_reason=f"unknown_reason_{reason.value}")


@dataclasses.dataclass
class ExecutorCallbacks:
    """Grouped callbacks and services passed from AgentRunnerExecutor to RunWorkflow.

    All fields default to ``None`` so that a minimal ``RunWorkflow`` can be
    created for signal-only use (e.g., ``on_signal()`` in integration tests)
    without an executor context.
    """

    session_factory: async_sessionmaker[AsyncSession] | None = None
    create_service: Callable[..., Any] | None = None
    monitor_agent_health: Callable[..., Any] | None = None
    heartbeat: Callable[[str], None] | None = None
    find_next_task: Callable[..., Any] | None = None
    broadcaster: EventBroadcaster | None = None
    prepare_codex_config: Callable[..., Any] | None = None
    execute_task: Callable[..., Any] | None = None
    attempt_store: AttemptStore | None = None
    running_tasks: dict[str, asyncio.Task[None]] | None = None
    heartbeats: dict[str, datetime] | None = None


class RunWorkflow:
    """Single owner of run execution for one active run.

    Executor services are grouped into an ``ExecutorCallbacks`` dataclass
    which ``AgentRunnerExecutor`` constructs and passes in.  This avoids
    15+ optional keyword parameters and keeps RunWorkflow's own attributes
    public so static type checkers do not raise reportPrivateUsage errors.
    """

    def __init__(
        self,
        run_id: str,
        agent_type: AgentRunnerType | None = None,
        agent_config: dict[str, Any] | None = None,
        *,
        callbacks: ExecutorCallbacks | None = None,
        transport: SignalTransport | None = None,
    ) -> None:
        self.run_id = run_id
        self.agent_type = agent_type
        self.agent_config = agent_config if agent_config is not None else {}

        # Executor services grouped in a dataclass
        self._callbacks = callbacks or ExecutorCallbacks()

        # Injectable signal transport — falls back to DbSignalTransport when None
        self._transport = transport

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entry point.  Registers workflow, runs loop, cleans up.

        Executor creates this instance and awaits .run() inside the
        background asyncio Task.
        """
        # These must be set when run() is called from an executor context.
        assert self._callbacks.session_factory is not None, "session_factory required for run()"
        assert self._callbacks.create_service is not None, "create_service required for run()"
        assert self._callbacks.monitor_agent_health is not None, (
            "monitor_agent_health required for run()"
        )

        run_id = self.run_id
        agent_type = self.agent_type

        # Background health monitor (same as before)
        health_monitor_task = asyncio.create_task(
            self._callbacks.monitor_agent_health(run_id, agent_type)
        )

        register_active_run(run_id)
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            # Server shutdown/reload cancels asyncio tasks. Use "server_shutdown"
            # reason so startup recovery can auto-resume these runs.
            logger.warning(f"Run {run_id}: agent loop cancelled (server shutdown?), pausing run")
            unregister_active_run(run_id)
            try:
                async with self._callbacks.session_factory() as session:
                    service = await self._callbacks.create_service(session)
                    await service.pause_run(run_id, reason="server_shutdown")
                    await session.commit()
            except Exception:
                # DB/engine might be shutting down too.
                logger.debug(f"Run {run_id}: could not pause run during shutdown (expected)")
            raise  # Re-raise so the task is marked as cancelled
        except Exception as e:
            logger.exception(f"Run {run_id}: unexpected error in agent loop: {e}")
            unregister_active_run(run_id)
            try:
                async with self._callbacks.session_factory() as session:
                    service = await self._callbacks.create_service(session)
                    await service.pause_run(run_id, reason="unexpected_error")
                    await session.commit()
            except Exception:
                logger.exception(f"Run {run_id}: failed to pause run after outer error")
        finally:
            # Always unregister (may already be done in exception handlers above)
            unregister_active_run(run_id)

            # Cancel health monitor
            health_monitor_task.cancel()
            try:
                await health_monitor_task
            except asyncio.CancelledError:
                pass

            # Safety net: if the run is still ACTIVE when the executor exits,
            # pause it so the sweeper doesn't find an orphaned ACTIVE run.
            # unregister_active_run() has already been called so service.pause_run()
            # uses the direct-DB path.
            try:
                async with self._callbacks.session_factory() as session:
                    from orchestrator.db import RunRepository

                    repo = RunRepository(session)
                    run = await repo.get(run_id)
                    if run.status == RunStatus.ACTIVE:
                        logger.warning(
                            f"Run {run_id}: executor exiting with run still ACTIVE "
                            "— pausing (safety net)"
                        )
                        service = await self._callbacks.create_service(session)
                        await service.pause_run(run_id, reason="executor_exited")
                        await session.commit()
            except Exception:
                logger.exception(f"Run {run_id}: safety-net pause failed — run may be left ACTIVE")

            if self._callbacks.running_tasks is not None:
                self._callbacks.running_tasks.pop(run_id, None)
            if self._callbacks.heartbeats is not None:
                self._callbacks.heartbeats.pop(run_id, None)
            logger.info(f"Run {run_id}: agent loop ended")

    async def on_signal(self, session: AsyncSession, service: WorkflowService) -> bool:
        """Drain pending signals and dispatch each to its typed handler.

        Called at the top of each iteration of the execution loop.  Returns
        True if the loop should stop (signal was applied that transitions the
        run out of ACTIVE state).

        Signals are processed in FIFO order (by created_at).  Each signal is
        marked processed_at exactly once — the DbSignalTransport guarantees
        idempotent consumption.
        """
        _transport: SignalTransport = (
            self._transport if self._transport is not None else DbSignalTransport(session)
        )
        queue = SignalQueue(_transport)
        signals = await queue.drain(self.run_id)

        registry = build_registry(self)

        for signal in signals:
            handler = registry.get(signal.signal_type)
            if handler is not None:
                should_stop: bool = await handler(session, service, signal.payload)
                if should_stop:
                    return True
            else:
                logger.debug(f"Run {self.run_id}: unhandled signal {signal.signal_type.value}")

        return False

    # ------------------------------------------------------------------
    # Typed signal handlers (registered via @signal_handler decorator)
    # ------------------------------------------------------------------

    @signal_handler(WorkflowSignal.PAUSE)
    async def handle_pause(
        self,
        session: AsyncSession,
        service: WorkflowService,
        payload: dict[str, Any] | None,
    ) -> bool:
        """Apply pause state and emit RunStatusChanged."""
        raw_reason: Any = payload.get("reason") if payload else None
        reason: str = raw_reason if isinstance(raw_reason, str) else "signal_pause"
        logger.info(f"Run {self.run_id}: applying PAUSE signal (reason={reason})")
        unregister_active_run(self.run_id)
        await service.pause_run(self.run_id, reason=reason)
        return True

    @signal_handler(WorkflowSignal.RESUME)
    async def handle_resume(
        self,
        session: AsyncSession,
        service: WorkflowService,
        payload: dict[str, Any] | None,
    ) -> bool:
        """Ignore RESUME while already running (no-op)."""
        logger.debug(f"Run {self.run_id}: ignoring RESUME signal (already running)")
        return False

    @signal_handler(WorkflowSignal.CANCEL)
    async def handle_cancel(
        self,
        session: AsyncSession,
        service: WorkflowService,
        payload: dict[str, Any] | None,
    ) -> bool:
        """Apply cancelled state and emit RunStatusChanged."""
        logger.info(f"Run {self.run_id}: applying CANCEL signal")
        unregister_active_run(self.run_id)
        await service.cancel_run(self.run_id)
        return True

    @signal_handler(WorkflowSignal.ACTIVITY_COMPLETED)
    async def handle_activity_completed(
        self,
        session: AsyncSession,
        service: WorkflowService,
        payload: dict[str, Any] | None,
    ) -> bool:
        """Transition task from BUILDING → VERIFYING on ACTIVITY_COMPLETED signal."""
        task_id: str | None = payload.get("task_id") if payload else None
        if not task_id:
            logger.warning(f"Run {self.run_id}: ACTIVITY_COMPLETED signal missing task_id")
            return False
        try:
            result = await service.submit_for_verification(self.run_id, task_id)
            if result.success:
                logger.info(
                    f"Run {self.run_id}: task {task_id} transitioned to "
                    f"{result.new_status.value} via ACTIVITY_COMPLETED signal"
                )
            else:
                logger.warning(
                    f"Run {self.run_id}: ACTIVITY_COMPLETED for task {task_id} "
                    f"failed: {result.error}"
                )
        except GateBlockedError as e:
            logger.warning(
                f"Run {self.run_id}: task {task_id} checklist gate blocked on submit: {e}. "
                "Pausing run."
            )
            await service.pause_run(self.run_id, reason="gate_blocked")
            await session.commit()
        except Exception as e:
            logger.warning(
                f"Run {self.run_id}: error handling ACTIVITY_COMPLETED for task {task_id}: {e}"
            )
        return False

    @signal_handler(WorkflowSignal.ACTIVITY_VERIFIED)
    async def handle_activity_verified(
        self,
        session: AsyncSession,
        service: WorkflowService,
        payload: dict[str, Any] | None,
    ) -> bool:
        """Process verification outcome on ACTIVITY_VERIFIED signal."""
        task_id: str | None = payload.get("task_id") if payload else None
        if not task_id:
            logger.warning(f"Run {self.run_id}: ACTIVITY_VERIFIED signal missing task_id")
            return False
        try:
            result = await service.complete_verification(self.run_id, task_id)
            if result.success:
                logger.info(
                    f"Run {self.run_id}: task {task_id} verification completed → "
                    f"{result.new_status.value} via ACTIVITY_VERIFIED signal"
                )
            else:
                logger.warning(
                    f"Run {self.run_id}: ACTIVITY_VERIFIED for task {task_id} "
                    f"failed: {result.error}"
                )
        except Exception as e:
            logger.warning(
                f"Run {self.run_id}: error handling ACTIVITY_VERIFIED for task {task_id}: {e}"
            )
        return False

    # ------------------------------------------------------------------
    # Main execution loop (previously AgentRunnerExecutor._run_agent_loop)
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Execution loop: find task → execute → repeat until done/paused/failed.

        Moved from AgentRunnerExecutor._run_agent_loop().  All internal
        calls to service.pause_run() unregister_active_run() first so
        that the signal-routing check in WorkflowService uses the direct-DB
        path (not the signal queue).
        """
        from orchestrator.db import RunRepository
        from orchestrator.workflow.events import ApprovalRequested

        # All executor services must be present when _run_loop() is called.
        assert self._callbacks.session_factory is not None, (
            "session_factory required for _run_loop()"
        )
        assert self._callbacks.create_service is not None, "create_service required for _run_loop()"
        assert self._callbacks.heartbeat is not None, "heartbeat required for _run_loop()"
        assert self._callbacks.find_next_task is not None, "find_next_task required for _run_loop()"
        assert self._callbacks.broadcaster is not None, "broadcaster required for _run_loop()"
        assert self._callbacks.prepare_codex_config is not None, (
            "prepare_codex_config required for _run_loop()"
        )
        assert self._callbacks.execute_task is not None, "execute_task required for _run_loop()"
        assert self._callbacks.attempt_store is not None, "attempt_store required for _run_loop()"

        run_id = self.run_id
        agent_type = self.agent_type
        agent_config = self.agent_config

        # Track tasks whose recovery was already attempted in this session.
        recovery_attempted: set[str] = set()

        # Run-scoped summary cache: reuse summaries from earlier tasks.
        summary_cache = SummaryCache()

        while True:
            async with self._callbacks.session_factory() as session:
                service = await self._callbacks.create_service(session)
                repo = RunRepository(session)

                run = await repo.get(run_id)

                # Stop if run is no longer active
                if run.status != RunStatus.ACTIVE:
                    logger.info(f"Run {run_id}: status is {run.status.value}, stopping agent loop")
                    break

                # Record heartbeat
                self._callbacks.heartbeat(run_id)

                # Drain and apply pending signals at the top of each iteration
                if await self.on_signal(session, service):
                    await session.commit()
                    break

                # Find the next actionable task
                task_state, no_task_reason = self._callbacks.find_next_task(run)

                if no_task_reason is not None:
                    action = resolve_no_task_action(run, no_task_reason)

                    if no_task_reason == NoTaskReason.BLOCKED_BY_GATE:
                        blocked_step = None
                        for step in run.steps:
                            for task in step.tasks:
                                if task.status in (
                                    TaskStatus.PENDING,
                                    TaskStatus.BUILDING,
                                    TaskStatus.VERIFYING,
                                ):
                                    blocked_step = step
                                    break
                            if blocked_step is not None:
                                break

                        step_id = blocked_step.id if blocked_step else ""
                        logger.info(
                            f"Run {run_id}: blocked by human_approval gate "
                            f"on step {step_id}, pausing until approval"
                        )
                        event = ApprovalRequested(
                            timestamp=datetime.now(timezone.utc),
                            run_id=run_id,
                            event_type="approval_requested",
                            step_id=step_id,
                        )
                        await self._callbacks.broadcaster.emit_log_event(event)
                    elif no_task_reason == NoTaskReason.ALL_COMPLETE:
                        logger.info(
                            f"Run {run_id}: all steps complete, ensuring run is in terminal state"
                        )
                    elif no_task_reason == NoTaskReason.FAN_OUT_IN_PROGRESS:
                        logger.warning(
                            f"Run {run_id}: fan-out task in progress but "
                            "no executor driving it — pausing for recovery"
                        )
                    else:
                        logger.info(f"Run {run_id}: no task — {no_task_reason.value}")

                    # Act on the decision — unregister before internal pauses
                    if action.kind == "pause":
                        unregister_active_run(run_id)
                        await service.pause_run(run_id, reason=action.pause_reason or "unknown")
                        await session.commit()
                    elif action.kind in ("complete", "fail"):
                        await repo.save(run)
                        await session.commit()
                        logger.info(f"Run {run_id}: safety-net completion → {run.status.value}")
                    break

                # no_task_reason is None → task_state is set
                assert task_state is not None

                effective_config, stale_reason = self._callbacks.prepare_codex_config(
                    agent_type, agent_config
                )
                if stale_reason is not None:
                    logger.info(
                        f"Run {run_id}: task {task_state.id}: Codex session "
                        f"discarded ({stale_reason}); new attempt will start fresh"
                    )

                logger.info(
                    f"Run {run_id}: executing task {task_state.id} ({task_state.config_id})"
                )
                was_recovering = task_state.status == TaskStatus.RECOVERING

                # Guard against infinite recovery loops
                if was_recovering and task_state.id in recovery_attempted:
                    logger.warning(
                        f"Run {run_id}: task {task_state.id} still RECOVERING "
                        "after previous recovery attempt — pausing"
                    )
                    unregister_active_run(run_id)
                    await service.pause_run(run_id, reason="recovery_loop")
                    await session.commit()
                    break
                if was_recovering:
                    recovery_attempted.add(task_state.id)

                try:
                    await self._callbacks.execute_task(
                        run,
                        task_state,
                        service,
                        agent_type,
                        effective_config,
                        summary_cache=summary_cache,
                        session=session,
                    )
                    await session.commit()
                except GateBlockedError as e:
                    logger.warning(
                        f"Run {run_id}: task {task_state.id} checklist gate "
                        f"blocked on submit: {e}. "
                        "Agent ran but could not satisfy the gate — pausing run."
                    )
                    unregister_active_run(run_id)
                    await service.pause_run(run_id, reason="gate_blocked")
                    await session.commit()
                    break
                except AgentCancelledError:
                    logger.info(f"Run {run_id}: agent cancelled — pausing run")
                    unregister_active_run(run_id)
                    await service.pause_run(run_id, reason="agent_cancelled")
                    await session.commit()
                    break
                except AgentNotAvailableError as e:
                    logger.error(f"Run {run_id}: agent not available: {e}")
                    await self._callbacks.broadcaster.emit_error_event(
                        run_id, task_state, "AgentNotAvailableError", str(e)
                    )
                    await self._callbacks.attempt_store.store_attempt_output(
                        run_id, task_state.id, [], str(e)
                    )
                    unregister_active_run(run_id)
                    await service.pause_run(
                        run_id, reason="agent_not_available", error_detail=str(e)
                    )
                    await session.commit()
                    break
                except AgentExecutionError as e:
                    logger.error(f"Run {run_id}: agent execution error: {e}")
                    await self._callbacks.broadcaster.emit_error_event(
                        run_id, task_state, "AgentExecutionError", str(e)
                    )
                    await self._callbacks.attempt_store.store_attempt_output(
                        run_id, task_state.id, [], str(e)
                    )
                    unregister_active_run(run_id)
                    await service.pause_run(
                        run_id, reason="agent_execution_error", error_detail=str(e)
                    )
                    await session.commit()
                    break
                except Exception as e:
                    logger.exception(f"Run {run_id}: unexpected error: {e}")
                    await self._callbacks.broadcaster.emit_error_event(
                        run_id, task_state, type(e).__name__, str(e)
                    )
                    try:
                        unregister_active_run(run_id)
                        await service.pause_run(
                            run_id,
                            reason="unexpected_error",
                            error_detail=str(e),
                        )
                        await session.commit()
                    except Exception:
                        logger.exception(f"Run {run_id}: failed to pause run after error")
                    break
