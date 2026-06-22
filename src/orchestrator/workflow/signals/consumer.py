"""Signal consumer loop for the workflow system.

Polls the events_v2 table every 100ms, dispatching signals to typed
handlers.  Concurrent across run_ids (one asyncio.Task per run_id); serial
FIFO processing within each run_id.

Delivery semantics:
  - SignalProcessed event is appended AFTER the handler returns successfully.
  - If the handler raises, no SignalProcessed is committed → signal is eligible
    for redelivery on the next startup.

This module is the single-queue signal consumer, wired into the app lifespan
in ``orchestrator.api.app``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.workflow.signals.runtime import RunWorkflow
from orchestrator.workflow.signals.signals import WorkflowSignal

if TYPE_CHECKING:
    from orchestrator.db import RunLifecycleProjector
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


class SignalConsumer:
    """Consumer loop for the events_v2 signal queue.

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
    workflow_preparer:
        Optional async callable that prepares required run resources before
        RUN_START / RESUME transitions the run to ACTIVE.
    projector:
        Optional RunLifecycleProjector; a new one is created if not provided.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        create_service: Callable[..., Awaitable[WorkflowService]],
        *,
        poll_interval: float = 0.1,
        workflow_runner: Callable[[RunWorkflow], Awaitable[None]] | None = None,
        graph_runner: Callable[[str], Awaitable[None]] | None = None,
        workflow_preparer: Callable[[str, dict[str, Any] | None], Awaitable[bool]] | None = None,
        projector: RunLifecycleProjector | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._create_service = create_service
        self._poll_interval = poll_interval
        self._workflow_runner = workflow_runner
        self._graph_runner = graph_runner
        self._workflow_preparer = workflow_preparer
        if projector is None:
            from orchestrator.db import RunLifecycleProjector

            projector = RunLifecycleProjector()
        self._projector = projector

        # RunWorkflow instances owned by this consumer (keyed by run_id)
        self._active_workflows: dict[str, RunWorkflow] = {}
        self._active_graph_runs: set[str] = set()
        # Per-run signal-processing tasks
        self._run_tasks: dict[str, asyncio.Task[None]] = {}

        self._stop_event = asyncio.Event()
        self._poll_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the consumer: rebuild projector, redeliver crashed signals, begin polling."""
        await self._rebuild_projector()
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
    # Projector rebuild
    # ------------------------------------------------------------------

    async def _rebuild_projector(self) -> None:
        """Rebuild the RunLifecycleProjector from persisted RunStatusChanged events."""
        from orchestrator.db import EventV2Model
        from orchestrator.workflow import RunStatusChanged

        async with self._session_factory() as session:
            result = await session.execute(
                select(EventV2Model)
                .where(EventV2Model.event_type == "run_status_changed")
                .order_by(EventV2Model.position)
            )
            rows = list(result.scalars())

        events: list[RunStatusChanged] = []
        for row in rows:
            try:
                data = json.loads(row.payload)
                event = RunStatusChanged.model_validate(data)
                events.append(event)
            except Exception:
                pass

        await self._projector.rebuild(events, session=None)  # type: ignore[arg-type]

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
        """Return distinct run_ids that have unhandled SignalEnqueued events in events_v2."""
        from orchestrator.db import EventV2Model

        async with self._session_factory() as session:
            # Fetch all SignalEnqueued events
            result = await session.execute(
                select(EventV2Model.aggregate_id, EventV2Model.position)
                .where(EventV2Model.event_type == "signal_enqueued")
                .order_by(EventV2Model.position)
            )
            enqueued_rows = list(result.all())

            if not enqueued_rows:
                return []

            # Fetch all processed positions
            result2 = await session.execute(
                select(EventV2Model.payload).where(EventV2Model.event_type == "signal_processed")
            )
            processed_payloads = list(result2.scalars())

        processed_positions: set[int] = set()
        for p in processed_payloads:
            try:
                data = json.loads(p)
                pos = data.get("enqueued_position")
                if isinstance(pos, int):
                    processed_positions.add(pos)
            except (json.JSONDecodeError, AttributeError):
                pass

        pending_run_ids: list[str] = []
        seen: set[str] = set()
        for run_id, position in enqueued_rows:
            if position not in processed_positions and run_id not in seen:
                pending_run_ids.append(run_id)
                seen.add(run_id)

        return pending_run_ids

    # ------------------------------------------------------------------
    # Per-run serial processing
    # ------------------------------------------------------------------

    async def _process_run(self, run_id: str) -> None:
        """Drain all pending signals for *run_id* serially in FIFO (position) order."""
        while True:
            signal_data = await self._fetch_next_event_signal(run_id)
            if signal_data is None:
                break
            if not await self._dispatch_event_signal(run_id, signal_data):
                break

    async def _fetch_next_event_signal(
        self, run_id: str
    ) -> tuple[int, WorkflowSignal, dict[str, Any] | None] | None:
        """Return (enqueued_position, signal_type, payload) for the next unprocessed signal."""
        from orchestrator.db import EventV2Model

        async with self._session_factory() as session:
            result = await session.execute(
                select(EventV2Model.position, EventV2Model.payload)
                .where(
                    EventV2Model.aggregate_id == run_id,
                    EventV2Model.event_type == "signal_enqueued",
                )
                .order_by(EventV2Model.position)
            )
            enqueued_rows = list(result.all())

            if not enqueued_rows:
                return None

            result2 = await session.execute(
                select(EventV2Model.payload).where(
                    EventV2Model.aggregate_id == run_id,
                    EventV2Model.event_type == "signal_processed",
                )
            )
            processed_payloads = list(result2.scalars())

        processed_positions: set[int] = set()
        for p in processed_payloads:
            try:
                data = json.loads(p)
                pos = data.get("enqueued_position")
                if isinstance(pos, int):
                    processed_positions.add(pos)
            except (json.JSONDecodeError, AttributeError):
                pass

        for position, payload_str in enqueued_rows:
            if position in processed_positions:
                continue
            try:
                payload_data = json.loads(payload_str)
                raw_type = payload_data.get("signal_type", "")
                signal_type = WorkflowSignal(raw_type)
                payload: dict[str, Any] | None = payload_data.get("payload")
                return position, signal_type, payload
            except (ValueError, KeyError):
                continue

        return None

    # ------------------------------------------------------------------
    # Signal dispatch
    # ------------------------------------------------------------------

    async def _dispatch_event_signal(
        self,
        run_id: str,
        signal_data: tuple[int, WorkflowSignal, dict[str, Any] | None],
    ) -> bool:
        """Run handler, then append SignalProcessed only after handler success.

        Handler effects and the processed marker commit atomically. If the
        handler fails, no SignalProcessed event is appended, leaving the
        signal eligible for redelivery.
        """
        from orchestrator.db import (
            commit_with_event_outbox,
            create_wired_event_store_v2,
            rollback_with_event_outbox,
        )
        from orchestrator.workflow import SignalProcessed

        from orchestrator.workflow import InvalidTransitionError

        enqueued_position, signal_type, payload = signal_data

        async with self._session_factory() as session:
            service = await self._create_service(session)
            try:
                await self._handle_signal(run_id, signal_type, payload, session, service)
                store = create_wired_event_store_v2(session)
                processed_event = SignalProcessed(
                    run_id=run_id,
                    event_type="signal_processed",
                    enqueued_position=enqueued_position,
                )
                await store.append([processed_event])
            except InvalidTransitionError:
                # Signal is stale — run already moved past this state.
                # Rollback the failed attempt then mark processed so the
                # signal is not retried indefinitely.
                await rollback_with_event_outbox(session)
                logger.warning(
                    "SignalConsumer: stale %s for run %s (invalid transition) — discarding",
                    signal_type.value,
                    run_id,
                )
                async with self._session_factory() as fresh_session:
                    fresh_store = create_wired_event_store_v2(fresh_session)
                    stale_processed = SignalProcessed(
                        run_id=run_id,
                        event_type="signal_processed",
                        enqueued_position=enqueued_position,
                    )
                    await fresh_store.append([stale_processed])
                    await commit_with_event_outbox(fresh_session)
                return True
            except Exception:
                await rollback_with_event_outbox(session)
                logger.exception(
                    "SignalConsumer: error handling %s for run %s — rolled back",
                    signal_type.value,
                    run_id,
                )
                return False
            await commit_with_event_outbox(session)
        return True

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
    # Typed handlers
    # ------------------------------------------------------------------

    async def _handle_run_start(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """RUN_START: DRAFT → ACTIVE, create the selected run driver, register."""
        if self._workflow_preparer is not None:
            prepared = await self._workflow_preparer(run_id, payload)
            if not prepared:
                logger.info(
                    "SignalConsumer: RUN_START for %s did not activate; preparation failed",
                    run_id,
                )
                return

        run = await service.apply_start_run(run_id)
        if getattr(run, "execution_mode", "legacy") == "graph":
            if self.arm_graph_run(run_id):
                logger.info("SignalConsumer: RUN_START for %s — graph driver registered", run_id)
            return

        workflow = RunWorkflow(
            run_id=run_id,
            agent_runner_type=run.agent_runner_type,
            agent_runner_config=run.agent_runner_config,
        )
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

        agent_runner_type: _AT | None = None
        agent_runner_config: dict[str, Any] | None = None
        resume_strategy: str | None = None
        if payload:
            if "agent_runner_type" in payload:
                agent_runner_type = _AT(payload["agent_runner_type"])
            agent_runner_config = payload.get("agent_runner_config")
            resume_strategy = payload.get("resume_strategy")

        current_run = await service.get_run(run_id)
        if self._status_value(getattr(current_run, "status", None)) == "active":
            logger.info(
                "SignalConsumer: ignoring stale RESUME for already active run %s",
                run_id,
            )
            if run_id not in self._active_workflows:
                workflow = RunWorkflow(
                    run_id=run_id,
                    agent_runner_type=current_run.agent_runner_type,
                    agent_runner_config=current_run.agent_runner_config,
                )
                self._active_workflows[run_id] = workflow
                if self._workflow_runner is not None:
                    asyncio.create_task(self._safe_run_workflow(run_id, workflow))
            return

        if self._workflow_preparer is not None:
            prepared = await self._workflow_preparer(run_id, payload)
            if not prepared:
                logger.info(
                    "SignalConsumer: RESUME for %s did not activate; preparation failed",
                    run_id,
                )
                return

        run = await service.apply_resume_run(
            run_id,
            agent_runner_type=agent_runner_type,
            agent_runner_config=agent_runner_config,
            resume_strategy=resume_strategy,
        )
        if getattr(run, "execution_mode", "legacy") == "graph":
            # Graph runs resume onto the (re-enterable) GraphRunDriver, not the
            # legacy RunWorkflow. The driver picks up from the durable graph
            # position without re-seeding.
            if self.arm_graph_run(run_id):
                logger.info("SignalConsumer: RESUME for %s — graph driver re-armed", run_id)
            return

        workflow = RunWorkflow(
            run_id=run_id,
            agent_runner_type=run.agent_runner_type,
            agent_runner_config=run.agent_runner_config,
        )
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
        """PAUSE: with active workflow → remove; then apply PAUSED directly."""
        reason: str = (payload.get("reason") if payload else None) or "signal_pause"
        error_detail: str | None = payload.get("error_detail") if payload else None

        if run_id in self._active_workflows:
            del self._active_workflows[run_id]
            logger.info("SignalConsumer: PAUSE for %s with active workflow — removed", run_id)

        await service.apply_pause_run(run_id, reason=reason, error_detail=error_detail)
        logger.info("SignalConsumer: PAUSE applied for %s (reason=%s)", run_id, reason)

    async def _handle_cancel(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """CANCEL: with active workflow → remove; then apply FAILED."""
        reason: str | None = payload.get("reason") if payload else None

        if run_id in self._active_workflows:
            del self._active_workflows[run_id]
            logger.info("SignalConsumer: CANCEL for %s with active workflow — removed", run_id)

        current_run = await service.get_run(run_id)
        if getattr(current_run, "execution_mode", "legacy") == "graph":
            from orchestrator.workflow.graph_driver import apply_graph_cancel_until_terminal

            self._active_graph_runs.discard(run_id)
            await apply_graph_cancel_until_terminal(
                self._session_factory,
                run_id,
                reason=reason,
            )

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
                if await self._run_is_paused(run_id, service):
                    logger.info(
                        "SignalConsumer: ignoring stale ACTIVITY_COMPLETED for paused run %s",
                        run_id,
                    )
                    return
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
                if await self._run_is_paused(run_id, service):
                    logger.info(
                        "SignalConsumer: ignoring stale ACTIVITY_VERIFIED for paused run %s",
                        run_id,
                    )
                    return
                await service.apply_verification(run_id, task_id)
            else:
                logger.warning("SignalConsumer: ACTIVITY_VERIFIED for %s missing task_id", run_id)

    async def _run_is_paused(self, run_id: str, service: WorkflowService) -> bool:
        """Return whether run-delivered activity is stale because the run is paused."""
        run = await service.get_run(run_id)
        return self._status_value(getattr(run, "status", None)) == "paused"

    @staticmethod
    def _status_value(status: Any) -> Any:
        return getattr(status, "value", status)

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

    def arm_graph_run(self, run_id: str) -> bool:
        """Start (or re-arm) the graph driver for a run, guarding double-arm.

        Used by RUN_START, RESUME, and startup recovery. Returns True if a
        driver task was started, False if no graph runner is configured or the
        run is already being driven. The GraphRunDriver is re-enterable, so a
        re-arm after a restart resumes the run from its durable graph position
        without re-seeding.
        """
        if self._graph_runner is None:
            return False
        if run_id in self._active_graph_runs:
            return False
        self._active_graph_runs.add(run_id)
        asyncio.create_task(self._safe_run_graph_driver(run_id))
        return True

    async def _safe_run_graph_driver(self, run_id: str) -> None:
        """Run a graph driver via the injected callback, cleaning up on completion."""
        try:
            if self._graph_runner is not None:
                await self._graph_runner(run_id)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("SignalConsumer: graph driver for %s failed", run_id)
        finally:
            self._active_graph_runs.discard(run_id)

    # ------------------------------------------------------------------
    # Startup redelivery
    # ------------------------------------------------------------------

    async def _redeliver_on_startup(self) -> None:
        """Re-dispatch signals for runs with no active workflow (crash recovery).

        Queries events_v2 for run_ids with unprocessed SignalEnqueued events.
        Filters to runs where is_active() is False (no active RunWorkflow).
        Re-dispatched through the normal _process_run path.
        """
        run_ids = await self._find_pending_run_ids()

        redelivery_ids = [run_id for run_id in run_ids if not self._projector.is_active(run_id)]

        if redelivery_ids:
            logger.info(
                "SignalConsumer: startup redelivery — %d run(s) with pending signals",
                len(redelivery_ids),
            )

        for run_id in redelivery_ids:
            await self._process_run(run_id)
