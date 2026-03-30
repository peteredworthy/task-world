"""Signal consumer loop for the workflow system.

Polls the pending_signals table every 100ms, dispatching signals to typed
handlers.  Concurrent across run_ids (one asyncio.Task per run_id); serial
FIFO processing within each run_id.

Delivery tracking:
  - ``delivered_at`` is stamped BEFORE the handler is invoked.
  - ``handled_at`` is stamped AFTER the handler returns successfully.
  - If the handler raises, ``handled_at`` stays NULL → signal is eligible
    for redelivery on the next startup.

This module is the single-queue signal consumer, wired into the app lifespan
in ``orchestrator.api.app``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.workflow.signals.runtime import RunWorkflow
from orchestrator.workflow.signals.signals import WorkflowSignal

if TYPE_CHECKING:
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry of active RunWorkflow instances (consumer-owned)
#
# These functions are the sole owners of the active-workflow registry.
# Only this module (and its test helpers) should import or call them.
# ---------------------------------------------------------------------------

_active_run_ids: set[str] = set()


def register_active_run(run_id: str) -> None:
    """Mark a run as having an active RunWorkflow driving it."""
    _active_run_ids.add(run_id)


def unregister_active_run(run_id: str) -> None:
    """Remove a run from the active-workflow registry."""
    _active_run_ids.discard(run_id)


def has_active_workflow(run_id: str) -> bool:
    """Return True if a RunWorkflow is currently executing for run_id."""
    return run_id in _active_run_ids


class SignalConsumer:
    """Consumer loop for the pending_signals queue.

    Parameters
    ----------
    session_factory:
        Async SQLAlchemy session factory.
    create_service:
        Async callable ``(session) -> WorkflowService`` — same pattern used
        throughout the executor.
    poll_interval:
        Seconds between poll ticks (default 0.1 s = 100 ms).
    workflow_runner:
        Optional async callable that is awaited for each new RunWorkflow
        after RUN_START / RESUME.  When None, workflows are created and
        registered but not started (useful in Phase 2 unit tests).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        create_service: Callable[..., Awaitable[WorkflowService]],
        *,
        poll_interval: float = 0.1,
        workflow_runner: Callable[[RunWorkflow], Awaitable[None]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._create_service = create_service
        self._poll_interval = poll_interval
        self._workflow_runner = workflow_runner

        # RunWorkflow instances owned by this consumer (keyed by run_id)
        self._active_workflows: dict[str, RunWorkflow] = {}
        # Per-run signal-processing tasks
        self._run_tasks: dict[str, asyncio.Task[None]] = {}

        self._stop_event = asyncio.Event()
        self._poll_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the consumer: redeliver crashed signals, then begin polling."""
        await self._redeliver_on_startup()
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        """Stop the consumer gracefully."""
        self._stop_event.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Main poll loop — runs every _poll_interval until stopped."""
        while not self._stop_event.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("SignalConsumer: error in poll tick")

            # Sleep for the poll interval, but exit immediately if stopped.
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=self._poll_interval,
                )
                break  # stop_event fired
            except asyncio.TimeoutError:
                pass  # normal — continue polling

    async def _tick(self) -> None:
        """One poll cycle: find run_ids with pending signals, ensure tasks exist."""
        run_ids = await self._find_pending_run_ids()
        for run_id in run_ids:
            existing = self._run_tasks.get(run_id)
            if existing is None or existing.done():
                self._run_tasks[run_id] = asyncio.create_task(self._process_run(run_id))

    async def _find_pending_run_ids(self) -> list[str]:
        """Return distinct run_ids that have unhandled, undelivered signals."""
        from sqlalchemy import select

        from orchestrator.db import PendingSignalModel

        async with self._session_factory() as session:
            stmt = (
                select(PendingSignalModel.run_id)
                .where(
                    PendingSignalModel.handled_at.is_(None),
                    PendingSignalModel.delivered_at.is_(None),
                )
                .order_by(PendingSignalModel.id)
                .distinct()
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Per-run serial processing
    # ------------------------------------------------------------------

    async def _process_run(self, run_id: str) -> None:
        """Drain all pending signals for *run_id* serially in FIFO (PK) order."""
        while True:
            signal_id = await self._fetch_next_signal_id(run_id)
            if signal_id is None:
                break
            await self._dispatch_signal_by_id(signal_id)

    async def _fetch_next_signal_id(self, run_id: str) -> int | None:
        """Return the PK of the lowest-id unhandled, undelivered signal for *run_id*."""
        from sqlalchemy import select

        from orchestrator.db import PendingSignalModel

        async with self._session_factory() as session:
            stmt = (
                select(PendingSignalModel.id)
                .where(
                    PendingSignalModel.run_id == run_id,
                    PendingSignalModel.handled_at.is_(None),
                    PendingSignalModel.delivered_at.is_(None),
                )
                .order_by(PendingSignalModel.id)
                .limit(1)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Signal dispatch
    # ------------------------------------------------------------------

    async def _dispatch_signal_by_id(self, signal_id: int) -> None:
        """Set delivered_at, invoke handler, set handled_at on success.

        This is the single dispatch path used by both the normal poll loop
        and the startup redelivery code, satisfying R3.
        """
        from sqlalchemy import select

        from orchestrator.db import PendingSignalModel

        async with self._session_factory() as session:
            stmt = select(PendingSignalModel).where(PendingSignalModel.id == signal_id)
            result = await session.execute(stmt)
            signal_model = result.scalar_one_or_none()
            if signal_model is None:
                return

            # R3: stamp delivered_at BEFORE handler invocation
            signal_model.delivered_at = datetime.now(timezone.utc)
            await session.flush()

            service = await self._create_service(session)
            payload: dict[str, Any] | None = (
                json.loads(signal_model.payload) if signal_model.payload else None
            )
            signal_type = WorkflowSignal(signal_model.signal_type)
            run_id = signal_model.run_id

            try:
                await self._handle_signal(run_id, signal_type, payload, session, service)
                # R3: stamp handled_at AFTER successful handler completion
                signal_model.handled_at = datetime.now(timezone.utc)
            except Exception:
                logger.exception(
                    "SignalConsumer: error handling %s for run %s",
                    signal_type.value,
                    run_id,
                )
                # R3: handled_at stays NULL — eligible for redelivery

            await session.commit()

    async def _handle_signal(
        self,
        run_id: str,
        signal_type: WorkflowSignal,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """Dispatch to the appropriate typed handler."""
        if signal_type == WorkflowSignal.RUN_START:
            await self._handle_run_start(run_id, payload, session, service)
        elif signal_type == WorkflowSignal.RESUME:
            await self._handle_resume(run_id, payload, session, service)
        elif signal_type == WorkflowSignal.PAUSE:
            await self._handle_pause(run_id, payload, session, service)
        elif signal_type == WorkflowSignal.CANCEL:
            await self._handle_cancel(run_id, payload, session, service)
        elif signal_type == WorkflowSignal.ACTIVITY_COMPLETED:
            await self._handle_activity_completed(run_id, payload, session, service)
        elif signal_type == WorkflowSignal.ACTIVITY_VERIFIED:
            await self._handle_activity_verified(run_id, payload, session, service)
        else:
            logger.warning(
                "SignalConsumer: unhandled signal type %s for run %s",
                signal_type.value,
                run_id,
            )

    # ------------------------------------------------------------------
    # Typed handlers (R2)
    # ------------------------------------------------------------------

    async def _handle_run_start(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """RUN_START: DRAFT → ACTIVE, create RunWorkflow, register."""
        run = await service.apply_start_run(run_id)
        workflow = RunWorkflow(
            run_id=run_id,
            agent_type=run.agent_type,
            agent_config=run.agent_config,
        )
        register_active_run(run_id)
        self._active_workflows[run_id] = workflow
        logger.info("SignalConsumer: RUN_START for %s — workflow registered", run_id)

        if self._workflow_runner is not None:
            asyncio.create_task(self._safe_run_workflow(run_id, workflow))

    async def _handle_resume(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """RESUME: PAUSED → ACTIVE, create RunWorkflow, register."""
        from orchestrator.config.enums import AgentRunnerType as _AT

        agent_type: _AT | None = None
        agent_config: dict[str, Any] | None = None
        resume_strategy: str | None = None
        if payload:
            if "agent_type" in payload:
                agent_type = _AT(payload["agent_type"])
            agent_config = payload.get("agent_config")
            resume_strategy = payload.get("resume_strategy")

        run = await service.apply_resume_run(
            run_id,
            agent_type=agent_type,
            agent_config=agent_config,
            resume_strategy=resume_strategy,
        )
        workflow = RunWorkflow(
            run_id=run_id,
            agent_type=run.agent_type,
            agent_config=run.agent_config,
        )
        register_active_run(run_id)
        self._active_workflows[run_id] = workflow
        logger.info("SignalConsumer: RESUME for %s — workflow registered", run_id)

        if self._workflow_runner is not None:
            asyncio.create_task(self._safe_run_workflow(run_id, workflow))

    async def _handle_pause(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """PAUSE: with active workflow → unregister, then apply PAUSED directly."""
        reason: str = (payload.get("reason") if payload else None) or "signal_pause"
        error_detail: str | None = payload.get("error_detail") if payload else None

        if run_id in self._active_workflows:
            # Unregister so the RunWorkflow loop detects status != ACTIVE and exits.
            unregister_active_run(run_id)
            del self._active_workflows[run_id]
            logger.info("SignalConsumer: PAUSE for %s with active workflow — unregistered", run_id)

        await service.apply_pause_run(run_id, reason=reason, error_detail=error_detail)
        logger.info("SignalConsumer: PAUSE applied for %s (reason=%s)", run_id, reason)

    async def _handle_cancel(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """CANCEL: with active workflow → unregister; then apply FAILED."""
        reason: str | None = payload.get("reason") if payload else None

        if run_id in self._active_workflows:
            unregister_active_run(run_id)
            del self._active_workflows[run_id]
            logger.info("SignalConsumer: CANCEL for %s with active workflow — unregistered", run_id)

        await service.apply_cancel_run(run_id, reason=reason)
        logger.info("SignalConsumer: CANCEL applied for %s", run_id)

    async def _handle_activity_completed(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """ACTIVITY_COMPLETED: deliver to RunWorkflow if active, else direct service call."""
        workflow = self._active_workflows.get(run_id)
        if workflow is not None:
            await workflow.handle_activity_completed(session, service, payload)
        else:
            task_id: str | None = (payload or {}).get("task_id")
            if task_id:
                await service.apply_submission(run_id, task_id)
            else:
                logger.warning("SignalConsumer: ACTIVITY_COMPLETED for %s missing task_id", run_id)

    async def _handle_activity_verified(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """ACTIVITY_VERIFIED: deliver to RunWorkflow if active, else direct service call."""
        workflow = self._active_workflows.get(run_id)
        if workflow is not None:
            await workflow.handle_activity_verified(session, service, payload)
        else:
            task_id: str | None = (payload or {}).get("task_id")
            if task_id:
                await service.apply_verification(run_id, task_id)
            else:
                logger.warning("SignalConsumer: ACTIVITY_VERIFIED for %s missing task_id", run_id)

    # ------------------------------------------------------------------
    # Workflow task wrapper
    # ------------------------------------------------------------------

    async def _safe_run_workflow(self, run_id: str, workflow: RunWorkflow) -> None:
        """Run *workflow* via the injected runner, cleaning up on completion."""
        try:
            if self._workflow_runner is not None:
                await self._workflow_runner(workflow)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SignalConsumer: workflow for %s failed", run_id)
        finally:
            self._active_workflows.pop(run_id, None)
            unregister_active_run(run_id)

    # ------------------------------------------------------------------
    # Startup redelivery (R4)
    # ------------------------------------------------------------------

    async def _redeliver_on_startup(self) -> None:
        """Re-dispatch signals that were delivered but never handled (crash recovery).

        Query: ``delivered_at IS NOT NULL AND handled_at IS NULL``
        Filtered to runs with no active RunWorkflow.
        Re-dispatched through the normal _dispatch_signal_by_id path so that
        delivered_at is refreshed and handled_at is set on success.
        """
        from sqlalchemy import select

        from orchestrator.db import PendingSignalModel

        async with self._session_factory() as session:
            stmt = (
                select(PendingSignalModel.id, PendingSignalModel.run_id)
                .where(
                    PendingSignalModel.delivered_at.is_not(None),
                    PendingSignalModel.handled_at.is_(None),
                )
                .order_by(PendingSignalModel.id)
            )
            result = await session.execute(stmt)
            rows = list(result.all())

        redelivery_ids: list[int] = [
            signal_id for signal_id, run_id in rows if not has_active_workflow(run_id)
        ]

        if redelivery_ids:
            logger.info(
                "SignalConsumer: startup redelivery — %d signal(s) to re-dispatch",
                len(redelivery_ids),
            )

        for signal_id in redelivery_ids:
            await self._dispatch_signal_by_id(signal_id)
