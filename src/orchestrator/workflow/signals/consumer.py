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
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, Protocol

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.workflow.signals.runtime import RunWorkflow
from orchestrator.workflow.signals.signals import WorkflowSignal

if TYPE_CHECKING:
    from orchestrator.db import RunLifecycleProjector
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)

_GRAPH_CRASH_PAUSE_ATTEMPTS = 3
_GRAPH_LIVENESS_RECONCILE_INTERVAL_SECONDS = 30.0
_GRAPH_LIVENESS_RECONCILE_BATCH_SIZE = 100
_GRAPH_LIVENESS_REARM_ATTEMPTS = 3
_GRAPH_STAGED_SUBMISSION_DEADLINE_SECONDS = 300.0


class _LivenessClock(Protocol):
    def now(self) -> datetime: ...


class _SystemLivenessClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class GraphLifecycleQuiescenceError(RuntimeError):
    """Raised when a graph run cannot prove all execution ownership is gone."""


def _parse_utc_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


class GraphDriverOwnership(BaseModel):
    """Bounded public readback for one consumer-owned graph driver."""

    model_config = {"frozen": True}

    run_id: str
    owned: bool
    generation: int = Field(ge=0)
    task_state: Literal["absent", "running", "finished", "cancelled"]
    reconciliation_attempts: int = Field(ge=0)


class GraphLivenessReconciliation(BaseModel):
    """Result of one bounded graph-driver ownership reconciliation page."""

    model_config = {"frozen": True}

    scanned: int = Field(ge=0)
    graph_runs: int = Field(ge=0)
    already_owned: int = Field(ge=0)
    rearmed_run_ids: tuple[str, ...] = ()
    pause_enqueued_run_ids: tuple[str, ...] = ()
    failed_run_ids: tuple[str, ...] = ()
    next_cursor: str | None = None


class _GraphRuntimeStall(BaseModel):
    model_config = {"frozen": True}

    action: Literal[
        "stalled_submission_rearmed",
        "expired_runtime_lease_rearmed",
        "runner_runtime_missing_rearmed",
    ]
    execution_id: str | None
    deadline_at: datetime | None
    root_error: str


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
        graph_execution_quiescence_preparer: Callable[[str, bool, bool], None] | None = None,
        graph_execution_quiescer: Callable[[str, bool, bool], Awaitable[None]] | None = None,
        graph_safe_effect_drainer: Callable[[str, str, bool], Awaitable[None]] | None = None,
        graph_owner_checker: Callable[[str], bool] | None = None,
        graph_run_status_checker: Callable[[str], Awaitable[bool]] | None = None,
        workflow_preparer: Callable[[str, dict[str, Any] | None], Awaitable[bool]] | None = None,
        projector: RunLifecycleProjector | None = None,
        journal_max_bytes: int = 64 * 1024 * 1024,
        graph_reconcile_interval: float = _GRAPH_LIVENESS_RECONCILE_INTERVAL_SECONDS,
        graph_reconcile_batch_size: int = _GRAPH_LIVENESS_RECONCILE_BATCH_SIZE,
        graph_reconcile_max_attempts: int = _GRAPH_LIVENESS_REARM_ATTEMPTS,
        graph_staged_submission_deadline: float = _GRAPH_STAGED_SUBMISSION_DEADLINE_SECONDS,
        liveness_clock: _LivenessClock | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._create_service = create_service
        self._poll_interval = poll_interval
        self._workflow_runner = workflow_runner
        self._graph_runner = graph_runner
        self._graph_execution_quiescence_preparer = graph_execution_quiescence_preparer
        self._graph_execution_quiescer = graph_execution_quiescer
        self._graph_safe_effect_drainer = graph_safe_effect_drainer
        self._graph_owner_checker = graph_owner_checker
        self._graph_run_status_checker = graph_run_status_checker
        self._workflow_preparer = workflow_preparer
        if projector is None:
            from orchestrator.db import RunLifecycleProjector

            projector = RunLifecycleProjector()
        self._projector = projector
        self._journal_max_bytes = journal_max_bytes
        if graph_reconcile_interval <= 0:
            raise ValueError("graph_reconcile_interval must be positive")
        if graph_reconcile_batch_size < 1:
            raise ValueError("graph_reconcile_batch_size must be positive")
        if graph_reconcile_max_attempts < 1:
            raise ValueError("graph_reconcile_max_attempts must be positive")
        if graph_staged_submission_deadline <= 0:
            raise ValueError("graph_staged_submission_deadline must be positive")
        self._graph_reconcile_interval = graph_reconcile_interval
        self._graph_reconcile_batch_size = graph_reconcile_batch_size
        self._graph_reconcile_max_attempts = graph_reconcile_max_attempts
        self._graph_staged_submission_deadline = graph_staged_submission_deadline
        self._liveness_clock = liveness_clock or _SystemLivenessClock()

        # RunWorkflow instances owned by this consumer (keyed by run_id)
        self._active_workflows: dict[str, RunWorkflow] = {}
        self._active_graph_runs: set[str] = set()
        # A graph run has an owned task as well as a membership marker.  The
        # task is required to fence pause/cancel against a live driver before a
        # later resume can transfer ownership to a new driver.
        self._graph_driver_tasks: dict[str, asyncio.Task[None]] = {}
        self._graph_driver_generations: dict[str, int] = {}
        self._graph_admission_blocked: set[str] = set()
        self._graph_quiescence_locks: dict[str, asyncio.Lock] = {}
        self._graph_reconcile_after_run_id: str | None = None
        # ``stop()`` marks the graph drivers it owns before cancelling them so
        # their cancellation handler can durably record a recoverable shutdown
        # pause instead of silently dropping an ACTIVE row with a live lease.
        self._server_shutdown_graph_runs: set[str] = set()
        # Per-run signal-processing tasks
        self._run_tasks: dict[str, asyncio.Task[None]] = {}

        self._stop_event = asyncio.Event()
        self._poll_task: asyncio.Task[None] | None = None
        self._graph_reconcile_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the consumer: rebuild projector, redeliver crashed signals, begin polling."""
        await self._rebuild_projector()
        await self._redeliver_on_startup()
        self._poll_task = asyncio.create_task(self._poll_loop())
        if self._graph_runner is not None:
            self._graph_reconcile_task = asyncio.create_task(self._graph_reconcile_loop())

    async def stop(self) -> None:
        """Stop the consumer gracefully."""
        self._stop_event.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._graph_reconcile_task is not None:
            self._graph_reconcile_task.cancel()
            try:
                await self._graph_reconcile_task
            except asyncio.CancelledError:
                pass
        for run_id in tuple(self._graph_driver_tasks):
            await self._quiesce_graph_run(run_id, server_shutdown=True)

    async def _graph_reconcile_loop(self) -> None:
        """Periodically recover graph rows that lost their in-process driver."""
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=self._graph_reconcile_interval,
                )
                return
            except asyncio.TimeoutError:
                pass
            try:
                await self.reconcile_graph_liveness_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SignalConsumer: graph liveness reconciliation failed")

    async def reconcile_graph_liveness_once(self) -> GraphLivenessReconciliation:
        """Reconcile one bounded page of ACTIVE graph rows against driver ownership.

        A graph driver is responsible for converting expired leases and staged
        submissions into durable recovery outcomes when it is re-entered.  This
        scan supplies the independent runtime trigger for that recovery.  A
        driver that repeatedly disappears without recording any lifecycle
        disposition is stopped through the ordinary signal queue, keeping the
        HTTP/executor boundary single-writer invariant intact.
        """
        from orchestrator.config import RunStatus
        from orchestrator.db import RunRepository

        async with self._session_factory() as session:
            records = await RunRepository(session).list_liveness_records_by_status(
                RunStatus.ACTIVE,
                after_run_id=self._graph_reconcile_after_run_id,
                limit=self._graph_reconcile_batch_size,
            )
        if not records and self._graph_reconcile_after_run_id is not None:
            self._graph_reconcile_after_run_id = None
            async with self._session_factory() as session:
                records = await RunRepository(session).list_liveness_records_by_status(
                    RunStatus.ACTIVE,
                    limit=self._graph_reconcile_batch_size,
                )

        self._graph_reconcile_after_run_id = (
            records[-1].id if len(records) == self._graph_reconcile_batch_size else None
        )
        graph_runs = [record for record in records if record.execution_mode == "graph"]
        already_owned = 0
        rearmed: list[str] = []
        pause_enqueued: list[str] = []
        failed: list[str] = []

        for record in graph_runs:
            ownership = self.graph_driver_ownership(record.id)
            try:
                observation, progress_changed, runtime_stall = await self._observe_graph_runtime(
                    record.id, ownership
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failed.append(record.id)
                logger.exception(
                    "SignalConsumer: could not persist graph liveness observation for %s",
                    record.id,
                )
                continue

            attempts = 0 if progress_changed else observation.no_progress_attempts
            if ownership.owned and runtime_stall is None:
                already_owned += 1
                continue

            if ownership.owned and runtime_stall is not None:
                try:
                    await self._quiesce_graph_lifecycle(
                        record.id,
                        reason=runtime_stall.root_error,
                        runner_loss=True,
                    )
                except GraphLifecycleQuiescenceError:
                    failed.append(record.id)
                    logger.exception(
                        "SignalConsumer: graph liveness could not quiesce %s",
                        record.id,
                    )
                    continue
                ownership = self.graph_driver_ownership(record.id)

            if attempts < self._graph_reconcile_max_attempts:
                self._graph_admission_blocked.discard(record.id)
                if await self.arm_graph_run(record.id):
                    attempts += 1
                    await self._set_graph_reconcile_action(
                        observation,
                        ownership=self.graph_driver_ownership(record.id),
                        attempts=attempts,
                        action=(
                            runtime_stall.action
                            if runtime_stall is not None
                            else "missing_driver_rearmed"
                        ),
                        root_error=(
                            runtime_stall.root_error if runtime_stall is not None else None
                        ),
                    )
                    rearmed.append(record.id)
                    logger.warning(
                        "SignalConsumer: graph liveness re-armed ACTIVE run %s "
                        "without an owned driver (attempt %d/%d)",
                        record.id,
                        attempts,
                        self._graph_reconcile_max_attempts,
                    )
                else:
                    failed.append(record.id)
                continue

            error_detail = (
                "Graph run remained active without an owned driver after "
                f"{attempts} bounded reconciliation attempts; the last driver "
                "ended without a durable lifecycle disposition."
            )
            try:
                async with self._session_factory() as session:
                    service = await self._create_service(session)
                    await service.pause_run(
                        record.id,
                        reason="graph_driver_liveness_exhausted",
                        error_detail=error_detail,
                    )
                pause_enqueued.append(record.id)
                await self._set_graph_reconcile_action(
                    observation,
                    ownership=ownership,
                    attempts=attempts,
                    action="pause_enqueued",
                    root_error=error_detail,
                )
                logger.error(
                    "SignalConsumer: graph liveness exhausted for %s; PAUSE enqueued",
                    record.id,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                failed.append(record.id)
                logger.exception(
                    "SignalConsumer: failed to enqueue graph liveness pause for %s",
                    record.id,
                )

        return GraphLivenessReconciliation(
            scanned=len(records),
            graph_runs=len(graph_runs),
            already_owned=already_owned,
            rearmed_run_ids=tuple(rearmed),
            pause_enqueued_run_ids=tuple(pause_enqueued),
            failed_run_ids=tuple(failed),
            next_cursor=self._graph_reconcile_after_run_id,
        )

    async def _observe_graph_runtime(
        self,
        run_id: str,
        ownership: GraphDriverOwnership,
    ) -> tuple[Any, bool, _GraphRuntimeStall | None]:
        """Persist bounded semantic progress and return stall/retry facts."""
        from orchestrator.db import (
            EventV2Model,
            GraphRuntimeSupervisionRecord,
            GraphRuntimeSupervisionRepository,
        )
        from orchestrator.graph import execution_attempts_view, leases_view
        from orchestrator.graph_runtime import GraphEventStore, graph_aggregate_id
        from sqlalchemy import func

        now = self._liveness_clock.now()
        async with self._session_factory() as session:
            store = GraphEventStore(session)
            checkpoint = await store.read_current_projection_view(run_id)
            attempts = (
                execution_attempts_view(checkpoint.projection) if checkpoint is not None else {}
            )
            leases = leases_view(checkpoint.projection) if checkpoint is not None else {}
            runtime_rows = list(
                await session.scalars(
                    select(EventV2Model)
                    .where(
                        EventV2Model.aggregate_id == run_id,
                        EventV2Model.event_type == "graph_runner_runtime_observed",
                    )
                    .order_by(EventV2Model.position.desc())
                    .limit(40)
                )
            )
            latest_runtime_by_execution: dict[str, dict[str, Any]] = {}
            for row in runtime_rows:
                payload = json.loads(row.payload)
                execution_id = payload.get("execution_id")
                if (
                    isinstance(execution_id, str)
                    and execution_id not in latest_runtime_by_execution
                ):
                    latest_runtime_by_execution[execution_id] = payload
            semantic_facts = {
                "run_state": (
                    checkpoint.projection.lifecycle.run_state if checkpoint is not None else None
                ),
                "attempts": [
                    [execution_id, value.state, value.completion_disposition, value.recovery_id]
                    for execution_id, value in sorted(attempts.items())
                ],
                "leases": [
                    [lease_id, value.state, value.generation, value.execution_id]
                    for lease_id, value in sorted(leases.items())
                ],
                "runner_runtime": [
                    [
                        execution_id,
                        payload.get("runner_type"),
                        payload.get("state"),
                        payload.get("timestamp"),
                        payload.get("pid"),
                        payload.get("reason"),
                    ]
                    for execution_id, payload in sorted(latest_runtime_by_execution.items())
                ],
            }
            progress_fingerprint = hashlib.sha256(
                json.dumps(semantic_facts, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            existing = await GraphRuntimeSupervisionRepository(session).get(run_id)
            progress_changed = (
                existing is None or existing.progress_fingerprint != progress_fingerprint
            )

            staged = sorted(
                (value for value in attempts.values() if value.state == "submission_staged"),
                key=lambda value: value.execution_id,
            )
            witnessed = sum(value.state == "completion_witnessed" for value in attempts.values())
            finalized = sum(value.state == "finalized" for value in attempts.values())
            disposition_counts: dict[str, int] = {}
            for value in attempts.values():
                if value.completion_disposition is not None:
                    disposition_counts[value.completion_disposition] = (
                        disposition_counts.get(value.completion_disposition, 0) + 1
                    )
            active_leases = [lease for lease in leases.values() if lease.state == "active"]
            expired_active_leases = [
                lease
                for lease in active_leases
                if lease.expires_at is not None and _parse_utc_timestamp(lease.expires_at) <= now
            ]
            missing_runtime_states = {
                "invalid_metadata",
                "unreported",
                "never_started",
                "missing",
            }
            missing_runtime_lease = next(
                (
                    lease
                    for lease in active_leases
                    if isinstance(lease.execution_id, str)
                    and latest_runtime_by_execution.get(lease.execution_id, {}).get("state")
                    in missing_runtime_states
                ),
                None,
            )
            expired_lease = min(
                expired_active_leases,
                key=lambda lease: _parse_utc_timestamp(lease.expires_at or now.isoformat()),
                default=None,
            )
            stalled_execution_id = (
                staged[0].execution_id
                if staged
                else (
                    missing_runtime_lease.execution_id
                    if missing_runtime_lease is not None
                    else expired_lease.execution_id
                    if expired_lease is not None
                    else None
                )
            )
            staged_at = now
            if stalled_execution_id is not None:
                staged_timestamp = await session.scalar(
                    select(EventV2Model.timestamp)
                    .where(
                        EventV2Model.aggregate_id == graph_aggregate_id(run_id),
                        EventV2Model.event_type == "runner_submission_staged",
                        func.json_extract(EventV2Model.payload, "$.payload.execution_id")
                        == stalled_execution_id,
                    )
                    .order_by(EventV2Model.position.desc())
                    .limit(1)
                )
                if isinstance(staged_timestamp, str):
                    staged_at = _parse_utc_timestamp(staged_timestamp)
            staged_deadline = (
                staged_at + timedelta(seconds=self._graph_staged_submission_deadline)
                if staged
                else None
            )
            expired_deadline = (
                _parse_utc_timestamp(expired_lease.expires_at)
                if expired_lease is not None and expired_lease.expires_at is not None
                else None
            )
            stall_deadline = staged_deadline or expired_deadline
            runtime_stall: _GraphRuntimeStall | None = None
            if missing_runtime_lease is not None:
                runtime_payload = latest_runtime_by_execution.get(
                    missing_runtime_lease.execution_id or "", {}
                )
                detail = runtime_payload.get("root_error") or runtime_payload.get("reason")
                runtime_stall = _GraphRuntimeStall(
                    action="runner_runtime_missing_rearmed",
                    execution_id=missing_runtime_lease.execution_id,
                    deadline_at=stall_deadline,
                    root_error=(
                        str(detail)[:1_000]
                        if detail
                        else "the verified runner process identity is missing"
                    ),
                )
            elif staged and staged_deadline is not None and now >= staged_deadline:
                runtime_stall = _GraphRuntimeStall(
                    action="stalled_submission_rearmed",
                    execution_id=staged[0].execution_id,
                    deadline_at=staged_deadline,
                    root_error=(
                        "runner submission remained staged without a completion witness "
                        f"through {staged_deadline.isoformat()}"
                    ),
                )
            elif expired_lease is not None:
                runtime_stall = _GraphRuntimeStall(
                    action="expired_runtime_lease_rearmed",
                    execution_id=expired_lease.execution_id,
                    deadline_at=expired_deadline,
                    root_error=(
                        "active runner lease expired without a current executor heartbeat "
                        f"at {expired_deadline.isoformat() if expired_deadline else 'unknown'}"
                    ),
                )
            no_progress_attempts = (
                (
                    0
                    if progress_changed or (checkpoint is not None and checkpoint.terminal)
                    else existing.no_progress_attempts
                )
                if existing is not None
                else 0
            )
            record = GraphRuntimeSupervisionRecord(
                run_id=run_id,
                observed_position=checkpoint.position if checkpoint is not None else 0,
                progress_fingerprint=progress_fingerprint,
                last_progress_at=(
                    now if progress_changed or existing is None else existing.last_progress_at
                ),
                last_reconciled_at=now,
                no_progress_attempts=no_progress_attempts,
                driver_generation=ownership.generation,
                driver_state=ownership.task_state,
                last_action="progress_observed" if progress_changed else "observed",
                stalled_execution_id=stalled_execution_id,
                stall_deadline_at=stall_deadline,
                staged_count=len(staged),
                witnessed_count=witnessed,
                finalized_count=finalized,
                active_lease_count=len(active_leases),
                expired_lease_count=len(expired_active_leases),
                disposition_counts=disposition_counts,
                root_error=None,
            )
            repository = GraphRuntimeSupervisionRepository(session)
            await repository.put(record)
            await session.commit()
        return record, progress_changed, runtime_stall

    async def _set_graph_reconcile_action(
        self,
        observation: Any,
        *,
        ownership: GraphDriverOwnership,
        attempts: int,
        action: str,
        root_error: str | None = None,
    ) -> None:
        from dataclasses import replace

        from orchestrator.db import (
            GraphRuntimeSupervisionRepository,
            commit_with_event_outbox,
            create_wired_event_store_v2,
        )
        from orchestrator.workflow import GraphRuntimeReconciled

        updated = replace(
            observation,
            last_reconciled_at=self._liveness_clock.now(),
            no_progress_attempts=attempts,
            driver_generation=ownership.generation,
            driver_state=ownership.task_state,
            last_action=action,
            root_error=root_error,
        )
        async with self._session_factory() as session:
            event = GraphRuntimeReconciled(
                timestamp=updated.last_reconciled_at,
                run_id=updated.run_id,
                graph_position=updated.observed_position,
                progress_fingerprint=updated.progress_fingerprint,
                no_progress_attempts=updated.no_progress_attempts,
                driver_generation=updated.driver_generation,
                driver_state=updated.driver_state,
                action=updated.last_action,
                stalled_execution_id=updated.stalled_execution_id,
                stall_deadline_at=updated.stall_deadline_at,
                staged_count=updated.staged_count,
                witnessed_count=updated.witnessed_count,
                finalized_count=updated.finalized_count,
                active_lease_count=updated.active_lease_count,
                expired_lease_count=updated.expired_lease_count,
                disposition_counts=updated.disposition_counts,
                root_error=updated.root_error,
            )
            await create_wired_event_store_v2(
                session, journal_max_bytes=self._journal_max_bytes
            ).append(event)
            await GraphRuntimeSupervisionRepository(session).put(updated)
            await commit_with_event_outbox(session)

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

        from orchestrator.state.errors import RunNotFoundError
        from orchestrator.workflow import InvalidTransitionError, RetiredAgentRunnerError

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
            except (InvalidTransitionError, RetiredAgentRunnerError, RunNotFoundError):
                # Signal is stale — run already moved past this state.
                # Rollback the failed attempt then mark processed so the
                # signal is not retried indefinitely.
                await rollback_with_event_outbox(session)
                logger.warning(
                    "SignalConsumer: rejecting %s for run %s — discarding",
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
            except GraphLifecycleQuiescenceError as exc:
                await rollback_with_event_outbox(session)
                logger.exception(
                    "SignalConsumer: lifecycle quiescence incomplete for run %s; "
                    "signal remains pending",
                    run_id,
                )
                async with self._session_factory() as fresh_session:
                    fresh_service = await self._create_service(fresh_session)
                    await fresh_service.record_graph_quiescence_failure(
                        run_id,
                        error_detail=str(exc),
                    )
                return False
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
        from orchestrator.workflow.service import ensure_executable_agent_runner

        current_run = await service.get_run(run_id)
        ensure_executable_agent_runner(current_run.agent_runner_type)
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
            self._graph_admission_blocked.discard(run_id)
            if await self.arm_graph_run(run_id):
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
        from orchestrator.workflow.service import ensure_executable_agent_runner

        ensure_executable_agent_runner(current_run.agent_runner_type, agent_runner_type)
        if self._status_value(getattr(current_run, "status", None)) == "active":
            ensure_executable_agent_runner(current_run.agent_runner_type)
            logger.info(
                "SignalConsumer: ignoring stale RESUME for already active run %s",
                run_id,
            )
            if getattr(current_run, "execution_mode", "legacy") == "graph":
                if await self.arm_graph_run(run_id):
                    logger.info(
                        "SignalConsumer: active RESUME for %s — graph driver re-armed",
                        run_id,
                    )
                return
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

        # Import only when the graph resume path needs the typed boundary
        # failure.  Importing graph_runtime while workflow is initializing
        # creates a runner/workflow cycle during application startup.
        from orchestrator.graph_runtime import GraphEventStore, GraphReadModelUnavailable

        try:
            if getattr(current_run, "execution_mode", "legacy") == "graph":
                # Explicit operator resume is also the supported upgrade path
                # for graph runs that predate the dedicated runtime checkpoint.
                # The maintenance replay is keyset-batched; ordinary runtime
                # reads remain bounded to the checkpoint plus its small tail.
                await GraphEventStore(session).ensure_runtime_projection_checkpoint(run_id)
            run = await service.apply_resume_run(
                run_id,
                agent_runner_type=agent_runner_type,
                agent_runner_config=agent_runner_config,
                resume_strategy=resume_strategy,
            )
        except GraphReadModelUnavailable as exc:
            # ``apply_resume_run`` probes the bounded graph checkpoint to
            # decide whether an operator reopen marker is needed.  The probe
            # must not leak through the signal loop (which would redeliver the
            # same RESUME forever while leaving an ambiguous PAUSED row).
            await service.apply_pause_run(
                run_id,
                reason="graph_read_model_unavailable",
                error_detail=str(exc),
            )
            logger.warning(
                "SignalConsumer: RESUME for %s remains paused; graph read model unavailable",
                run_id,
            )
            return
        if getattr(run, "execution_mode", "legacy") == "graph":
            # Graph runs resume onto the (re-enterable) GraphRunDriver, not the
            # legacy RunWorkflow. The driver picks up from the durable graph
            # position without re-seeding.
            self._graph_admission_blocked.discard(run_id)
            if await self.arm_graph_run(run_id):
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

        await self._quiesce_graph_lifecycle(
            run_id,
            reason=reason,
            retry_after_recovery=True,
        )

        await service.apply_pause_run(run_id, reason=reason, error_detail=error_detail)
        logger.info("SignalConsumer: PAUSE applied for %s (reason=%s)", run_id, reason)

    async def _handle_cancel(
        self,
        run_id: str,
        payload: dict[str, Any] | None,
        session: AsyncSession,
        service: WorkflowService,
    ) -> None:
        """CANCEL: with active workflow → remove; then apply CANCELLED."""
        reason: str | None = payload.get("reason") if payload else None

        if run_id in self._active_workflows:
            del self._active_workflows[run_id]
            logger.info("SignalConsumer: CANCEL for %s with active workflow — removed", run_id)

        current_run = await service.get_run(run_id)
        if getattr(current_run, "execution_mode", "legacy") == "graph":
            from orchestrator.workflow.graph_driver import apply_graph_cancel_until_terminal

            await self._quiesce_graph_lifecycle(
                run_id,
                reason=reason or "manual_cancel",
                retry_after_recovery=False,
            )
            await apply_graph_cancel_until_terminal(
                self._session_factory,
                run_id,
                reason=reason,
                journal_max_bytes=self._journal_max_bytes,
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

    async def arm_graph_run(self, run_id: str) -> bool:
        """Start (or re-arm) the graph driver for a run, guarding double-arm.

        Used by RUN_START, RESUME, and startup recovery. Returns True if a
        driver task was started, False if no graph runner is configured or the
        run is already being driven. The GraphRunDriver is re-enterable, so a
        re-arm after a restart resumes the run from its durable graph position
        without re-seeding.
        """
        if self._graph_runner is None:
            return False
        if run_id in self._graph_admission_blocked:
            return False
        if self._graph_run_status_checker is not None:
            active = await self._graph_run_status_checker(run_id)
        else:
            from orchestrator.config import RunStatus
            from orchestrator.db import RunRepository

            async with self._session_factory() as session:
                run = await RunRepository(session).get(run_id)
            active = run.status == RunStatus.ACTIVE
        if not active or run_id in self._graph_admission_blocked:
            return False
        if run_id in self._active_graph_runs:
            return False
        logger.info("SignalConsumer: arming graph driver for %s", run_id)
        self._active_graph_runs.add(run_id)
        generation = self._graph_driver_generations.get(run_id, 0) + 1
        self._graph_driver_generations[run_id] = generation
        self._graph_driver_tasks[run_id] = asyncio.create_task(
            self._safe_run_graph_driver(run_id, generation)
        )
        return True

    async def _quiesce_graph_lifecycle(
        self,
        run_id: str,
        *,
        reason: str,
        runner_loss: bool = False,
        retry_after_recovery: bool = False,
    ) -> None:
        """Fence admission, remove every owner, and prove graph leases are inactive."""
        self._graph_admission_blocked.add(run_id)
        lock = self._graph_quiescence_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            try:
                if self._graph_execution_quiescence_preparer is not None:
                    self._graph_execution_quiescence_preparer(
                        run_id,
                        runner_loss,
                        retry_after_recovery,
                    )
                await self._quiesce_graph_run(run_id)
                if self._graph_execution_quiescer is not None:
                    await self._graph_execution_quiescer(
                        run_id,
                        runner_loss,
                        retry_after_recovery,
                    )
                if self._graph_safe_effect_drainer is not None:
                    await self._graph_safe_effect_drainer(
                        run_id,
                        reason,
                        retry_after_recovery,
                    )
                if self.graph_driver_ownership(run_id).owned:
                    raise GraphLifecycleQuiescenceError(
                        f"graph driver ownership remains for run {run_id}"
                    )
                if self._graph_owner_checker is not None and self._graph_owner_checker(run_id):
                    raise GraphLifecycleQuiescenceError(
                        f"runner process ownership remains for run {run_id}"
                    )
                if (
                    self._graph_safe_effect_drainer is not None
                    and await self._active_graph_lease_count(run_id)
                ):
                    raise GraphLifecycleQuiescenceError(
                        f"active graph leases remain for run {run_id}"
                    )
            except asyncio.CancelledError:
                raise
            except GraphLifecycleQuiescenceError:
                raise
            except Exception as exc:
                raise GraphLifecycleQuiescenceError(
                    f"graph lifecycle quiescence failed for run {run_id}: {exc}"
                ) from exc

    async def _active_graph_lease_count(self, run_id: str) -> int:
        from orchestrator.graph import leases_view
        from orchestrator.graph_runtime import GraphEventStore

        async with self._session_factory() as session:
            checkpoint = await GraphEventStore(session).read_current_projection_view(run_id)
        if checkpoint is None:
            return 0
        return sum(lease.state == "active" for lease in leases_view(checkpoint.projection).values())

    def graph_driver_ownership(self, run_id: str) -> GraphDriverOwnership:
        """Return bounded public ownership facts without exposing task containers."""
        task = self._graph_driver_tasks.get(run_id)
        if task is None:
            task_state: Literal["absent", "running", "finished", "cancelled"] = "absent"
        elif task.cancelled():
            task_state = "cancelled"
        elif task.done():
            task_state = "finished"
        else:
            task_state = "running"
        return GraphDriverOwnership(
            run_id=run_id,
            owned=(run_id in self._active_graph_runs and task is not None and not task.done()),
            generation=self._graph_driver_generations.get(run_id, 0),
            task_state=task_state,
            reconciliation_attempts=0,
        )

    async def _quiesce_graph_run(self, run_id: str, *, server_shutdown: bool = False) -> None:
        """Cancel and await this consumer's graph driver before ownership moves."""
        task = self._graph_driver_tasks.get(run_id)
        if task is not None and not task.done():
            if server_shutdown:
                self._server_shutdown_graph_runs.add(run_id)
            logger.info(
                "SignalConsumer: cancelling graph driver for %s (server_shutdown=%s)",
                run_id,
                server_shutdown,
            )
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._graph_driver_tasks.pop(run_id, None)
        self._active_graph_runs.discard(run_id)

    async def _safe_run_graph_driver(self, run_id: str, generation: int) -> None:
        """Run a graph driver via the injected callback, cleaning up on completion."""
        try:
            if self._graph_runner is not None:
                await self._graph_runner(run_id)
        except asyncio.CancelledError:
            if run_id in self._server_shutdown_graph_runs:
                # Do this while the application still owns a live database
                # engine.  Cancellation is deliberately re-raised below so
                # shutdown semantics remain intact.
                from orchestrator.workflow.graph_driver import apply_graph_server_shutdown_pause

                try:
                    await apply_graph_server_shutdown_pause(
                        self._session_factory,
                        self._create_service,
                        run_id,
                        journal_max_bytes=self._journal_max_bytes,
                    )
                except Exception:
                    logger.exception(
                        "SignalConsumer: failed to persist graph shutdown pause for %s", run_id
                    )
                finally:
                    self._server_shutdown_graph_runs.discard(run_id)
            logger.info("SignalConsumer: graph driver for %s cancelled", run_id)
            raise
        except Exception as exc:
            logger.exception("SignalConsumer: graph driver for %s failed", run_id)
            # ``GraphRunDriver`` owns its ordinary drive-loop pause bridge, but
            # construction, seed, and other setup failures can escape before
            # that bridge is entered.  The consumer is the last lifecycle
            # owner still guaranteed to be present.  Persist the exact failure
            # rather than silently discarding the task and stranding ACTIVE.
            # A driver that already paused itself is observed as PAUSED and is
            # left untouched, so this does not duplicate its transition.
            await self._pause_crashed_graph_run(run_id, error_detail=str(exc))
        finally:
            # A stale task must never clear a newer driver's ownership marker.
            if self._graph_driver_generations.get(run_id) == generation:
                self._graph_driver_tasks.pop(run_id, None)
                self._active_graph_runs.discard(run_id)

    async def _pause_crashed_graph_run(self, run_id: str, *, error_detail: str) -> None:
        """Best-effort durable pause of an ACTIVE/STOPPING escaped graph run.

        Each retry constructs both a fresh session and a fresh service.  That
        matters for setup failures caused by a poisoned transaction or stale
        connection: reusing either object would make a bounded retry illusory.
        A concurrent terminal transition wins because every attempt rereads
        the run before applying the pause.
        """
        for attempt in range(1, _GRAPH_CRASH_PAUSE_ATTEMPTS + 1):
            try:
                async with self._session_factory() as session:
                    service = await self._create_service(session)
                    run = await service.get_run(run_id)
                    if self._status_value(getattr(run, "status", None)) not in {
                        "active",
                        "stopping",
                    }:
                        return
                    await service.pause_run(
                        run_id,
                        reason="graph_driver_crashed",
                        error_detail=error_detail,
                    )
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                if attempt == _GRAPH_CRASH_PAUSE_ATTEMPTS:
                    # This is the last-resort lifecycle bridge.  Preserve the
                    # original runner error on every attempted transition and
                    # absorb persistence exhaustion so the graph task cannot
                    # produce a second, unobserved exception.
                    logger.exception(
                        "SignalConsumer: failed to persist graph crash pause for %s "
                        "after %d attempts",
                        run_id,
                        _GRAPH_CRASH_PAUSE_ATTEMPTS,
                    )
                    return
                logger.warning(
                    "SignalConsumer: graph crash pause attempt %d/%d failed for %s; "
                    "retrying with a fresh session",
                    attempt,
                    _GRAPH_CRASH_PAUSE_ATTEMPTS,
                    run_id,
                    exc_info=True,
                )

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
