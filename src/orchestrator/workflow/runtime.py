"""RunWorkflow - the single owner of run execution.

RunWorkflow wraps the executor loop and is created by AgentRunnerExecutor
for each active run.  It:

  1. Registers itself in the active-workflow registry so WorkflowService can
     route external pause/resume/cancel signals through the signal queue.
  2. Calls on_signal() at the top of every iteration to drain and apply
     pending signals before doing any task work.
  3. Contains the main while-True execution loop (previously in
     AgentRunnerExecutor._run_agent_loop).
  4. Provides a stub for scheduled_resume_at polling.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from orchestrator.config.enums import RunStatus, TaskStatus
from orchestrator.runners.errors import (
    AgentCancelledError,
    AgentExecutionError,
    AgentNotAvailableError,
)
from orchestrator.workflow.errors import GateBlockedError
from orchestrator.workflow.signals import (
    DbSignalTransport,
    SignalQueue,
    WorkflowSignal,
    register_active_run,
    unregister_active_run,
)
from orchestrator.workflow.summary_cache import SummaryCache

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from orchestrator.config.enums import AgentRunnerType
    from orchestrator.runners.execution.attempt_store import AttemptStore
    from orchestrator.runners.execution.event_broadcaster import EventBroadcaster
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


class RunWorkflow:
    """Single owner of run execution for one active run.

    All executor internals that RunWorkflow needs are passed explicitly via
    __init__ parameters (bound to the executor's private members inside
    AgentRunnerExecutor._run_agent_loop, which is fine since that method is
    part of the same class).  This keeps RunWorkflow's own attributes public
    so static type checkers do not raise reportPrivateUsage errors.
    """

    def __init__(
        self,
        run_id: str,
        agent_type: AgentRunnerType,
        agent_config: dict[str, Any],
        *,
        # Executor services — provided by AgentRunnerExecutor._run_agent_loop
        session_factory: async_sessionmaker[AsyncSession],
        create_service: Callable[..., Any],
        monitor_agent_health: Callable[..., Any],
        heartbeat: Callable[[str], None],
        find_next_task: Callable[..., Any],
        broadcaster: EventBroadcaster,
        prepare_codex_config: Callable[..., Any],
        execute_task: Callable[..., Any],
        attempt_store: AttemptStore,
        running_tasks: dict[str, asyncio.Task[None]],
        heartbeats: dict[str, datetime],
    ) -> None:
        self.run_id = run_id
        self.agent_type = agent_type
        self.agent_config = agent_config

        # Executor services (public attributes — no underscore)
        self.session_factory = session_factory
        self.create_service = create_service
        self.monitor_agent_health = monitor_agent_health
        self.heartbeat = heartbeat
        self.find_next_task = find_next_task
        self.broadcaster = broadcaster
        self.prepare_codex_config = prepare_codex_config
        self.execute_task = execute_task
        self.attempt_store = attempt_store
        self.running_tasks = running_tasks
        self.heartbeats = heartbeats

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entry point.  Registers workflow, runs loop, cleans up.

        Executor creates this instance and awaits .run() inside the
        background asyncio Task.
        """
        run_id = self.run_id
        agent_type = self.agent_type

        # Background health monitor (same as before)
        health_monitor_task = asyncio.create_task(self.monitor_agent_health(run_id, agent_type))

        register_active_run(run_id)
        try:
            await self._run_loop()
        except asyncio.CancelledError:
            # Server shutdown/reload cancels asyncio tasks. Use "server_shutdown"
            # reason so startup recovery can auto-resume these runs.
            logger.warning(f"Run {run_id}: agent loop cancelled (server shutdown?), pausing run")
            unregister_active_run(run_id)
            try:
                async with self.session_factory() as session:
                    service = await self.create_service(session)
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
                async with self.session_factory() as session:
                    service = await self.create_service(session)
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
                async with self.session_factory() as session:
                    from orchestrator.db.repositories import RunRepository

                    repo = RunRepository(session)
                    run = await repo.get(run_id)
                    if run.status == RunStatus.ACTIVE:
                        logger.warning(
                            f"Run {run_id}: executor exiting with run still ACTIVE "
                            "— pausing (safety net)"
                        )
                        service = await self.create_service(session)
                        await service.pause_run(run_id, reason="executor_exited")
                        await session.commit()
            except Exception:
                logger.exception(f"Run {run_id}: safety-net pause failed — run may be left ACTIVE")

            self.running_tasks.pop(run_id, None)
            self.heartbeats.pop(run_id, None)
            logger.info(f"Run {run_id}: agent loop ended")

    async def on_signal(self, session: AsyncSession, service: WorkflowService) -> bool:
        """Drain pending signals and apply the first actionable one.

        Called at the top of each iteration of the execution loop.  Returns
        True if the loop should stop (signal was applied that transitions the
        run out of ACTIVE state).

        Signals are processed in FIFO order (by created_at).  Each signal is
        marked processed_at exactly once — the DbSignalTransport guarantees
        idempotent consumption.
        """
        transport = DbSignalTransport(session)
        queue = SignalQueue(transport)
        signals = await queue.drain(self.run_id)

        for signal in signals:
            if signal.signal_type == WorkflowSignal.PAUSE:
                reason = (
                    signal.payload.get("reason", "signal_pause")
                    if signal.payload
                    else "signal_pause"
                )
                logger.info(f"Run {self.run_id}: applying PAUSE signal (reason={reason})")
                unregister_active_run(self.run_id)
                await service.pause_run(self.run_id, reason=reason)
                return True

            elif signal.signal_type == WorkflowSignal.CANCEL:
                logger.info(f"Run {self.run_id}: applying CANCEL signal")
                unregister_active_run(self.run_id)
                await service.cancel_run(self.run_id)
                return True

            elif signal.signal_type == WorkflowSignal.RESUME:
                # RESUME while already running — ignore (no-op)
                logger.debug(f"Run {self.run_id}: ignoring RESUME signal (already running)")

            # ACTIVITY_COMPLETED / ACTIVITY_VERIFIED — reserved for future use
            else:
                logger.debug(f"Run {self.run_id}: unhandled signal {signal.signal_type.value}")

        return False

    # ------------------------------------------------------------------
    # Scheduled-resume stub
    # ------------------------------------------------------------------

    async def _scheduled_resume_check(
        self, session: AsyncSession, service: WorkflowService
    ) -> None:
        """Check scheduled_resume_at and auto-resume if the time has passed.

        Stub implementation: reads the scheduled_resume_at column and logs
        if it's in the past.  Full implementation would transition the run
        back to ACTIVE — deferred to the timer milestone.
        """
        from sqlalchemy import select

        from orchestrator.db.models import RunModel

        stmt = select(RunModel.scheduled_resume_at).where(RunModel.id == self.run_id)
        result = await session.execute(stmt)
        scheduled_at: datetime | None = result.scalar_one_or_none()

        if scheduled_at is not None:
            now = datetime.now(timezone.utc)
            # Normalise naive datetimes from SQLite
            if scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
            if scheduled_at <= now:
                logger.info(
                    f"Run {self.run_id}: scheduled_resume_at {scheduled_at} "
                    "has passed — auto-resume pending (stub, not yet implemented)"
                )

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
        from orchestrator.db.repositories import RunRepository
        from orchestrator.runners.executor import NoTaskReason, resolve_no_task_action
        from orchestrator.workflow.events import ApprovalRequested

        run_id = self.run_id
        agent_type = self.agent_type
        agent_config = self.agent_config

        # Track tasks whose recovery was already attempted in this session.
        recovery_attempted: set[str] = set()

        # Run-scoped summary cache: reuse summaries from earlier tasks.
        summary_cache = SummaryCache()

        while True:
            async with self.session_factory() as session:
                service = await self.create_service(session)
                repo = RunRepository(session)

                run = await repo.get(run_id)

                # Stop if run is no longer active
                if run.status != RunStatus.ACTIVE:
                    logger.info(f"Run {run_id}: status is {run.status.value}, stopping agent loop")
                    break

                # Record heartbeat
                self.heartbeat(run_id)

                # Drain and apply pending signals at the top of each iteration
                if await self.on_signal(session, service):
                    await session.commit()
                    break

                # Scheduled-resume stub (no-op for now)
                await self._scheduled_resume_check(session, service)

                # Find the next actionable task
                task_state, no_task_reason = self.find_next_task(run)

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
                        await self.broadcaster.emit_log_event(event)
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

                effective_config, stale_reason = self.prepare_codex_config(agent_type, agent_config)
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
                    await self.execute_task(
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
                    await self.broadcaster.emit_error_event(
                        run_id, task_state, "AgentNotAvailableError", str(e)
                    )
                    await self.attempt_store.store_attempt_output(run_id, task_state.id, [], str(e))
                    unregister_active_run(run_id)
                    await service.pause_run(
                        run_id, reason="agent_not_available", error_detail=str(e)
                    )
                    await session.commit()
                    break
                except AgentExecutionError as e:
                    logger.error(f"Run {run_id}: agent execution error: {e}")
                    await self.broadcaster.emit_error_event(
                        run_id, task_state, "AgentExecutionError", str(e)
                    )
                    await self.attempt_store.store_attempt_output(run_id, task_state.id, [], str(e))
                    unregister_active_run(run_id)
                    await service.pause_run(
                        run_id, reason="agent_execution_error", error_detail=str(e)
                    )
                    await session.commit()
                    break
                except Exception as e:
                    logger.exception(f"Run {run_id}: unexpected error: {e}")
                    await self.broadcaster.emit_error_event(
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
