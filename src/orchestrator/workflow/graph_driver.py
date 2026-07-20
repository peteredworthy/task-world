"""Production driver for graph-backed runs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.artifacts import ArtifactRootResolver, ArtifactStoreResolver

from orchestrator.config.enums import AgentRunnerType, RunStatus
from datetime import UTC, datetime
from uuid import uuid4

from orchestrator.config.models import RoutineConfig
from orchestrator.db import is_retriable_sqlite_write_conflict
from orchestrator.git import dirty_paths, find_leaked_paths, resolve_main_worktree
from orchestrator.graph import (
    Actor,
    ActorKind,
    EventEnvelope,
    GraphProjectionSnapshot,
    GraphRunOutcome,
    GraphCommandContext,
    project_active_lease_wait_plan,
    project_graph_completion_eligible,
    project_graph_outcome,
    project_graph_projection_snapshot,
    project_run_state,
)
from orchestrator.graph.commands import Clock, IdGenerator
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    StaleProjectionError,
    build_graph_runtime,
    recover,
    reconcile_graph,
    reconcile_runtime,
    seed_run,
)

if TYPE_CHECKING:
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


# How many times one drive_to_quiescence call will agent_died-recover the same
# node before giving up and letting the run pause graph_blocked. Small on
# purpose: a transient orphaning cause (e.g. a one-off rejected submit)
# resolves on the first re-dispatch, while a persistent cause fails the same
# way every time — 3 attempts distinguishes the two without burning agent
# spend on a node the kernel will not bound itself (no max_attempts).
MAX_NODE_RECOVERIES_PER_DRIVE = 3


SUPPORTED_GRAPH_RUNNER_TYPES = frozenset(
    {
        AgentRunnerType.CODEX_SERVER,
    }
)


# Persisted, consume-once discriminator written to a run row's pause_reason by
# WorkflowService.apply_resume_run when — and only when — an operator resumes a
# FAILED graph run (row FAILED -> ACTIVE while the kernel run_state stays
# "failed"). The driver's ACTIVE branch reopens the kernel ONLY when it sees this
# marker, then clears it immediately. Without the marker, a row that is ACTIVE
# with a failed kernel is a *crash-window stranded* run (the kernel autonomously
# failed — e.g. a recovery-planner no-successor sweep — and the process died
# before run() could persist the row FAILED). Those must self-heal by falling
# through to the drive loop (which re-classifies failed and _apply_fail persists
# FAILED), NOT be silently un-failed under a falsely-asserted operator role.
# It is persisted so it survives a crash between the operator resume and the
# driver start, and consumed (cleared) so a *later* autonomous failure + re-arm
# is not replayed as another spurious reopen.
GRAPH_OPERATOR_REOPEN_PAUSE_REASON = "graph_operator_reopen"


class SystemClock:
    """Wall-clock time source for production graph runs (real lease expiry)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIdGenerator:
    """Globally-unique id source for production graph runs.

    Event ids must be unique across driver invocations: the graph_outbox table
    is keyed by event_id, so a re-driven/resumed run that regenerated sequential
    ids would collide with already-stored outbox rows. UUIDs avoid that.
    """

    def next_id(self, prefix: str = "") -> str:
        return f"{prefix}-{uuid4().hex}"


async def apply_graph_cancel_until_terminal(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: str,
    *,
    reason: str | None = None,
    journal_max_bytes: int = 64 * 1024 * 1024,
) -> None:
    """Durably cancel graph runtime state before external callbacks can win.

    Run-row lifecycle still flows through the signal queue. This helper only
    records graph-kernel cancellation facts, including lease revocation and
    terminal graph state, so active runner callbacks are rejected consistently.
    """
    controller = GraphController(
        session_factory,
        SystemClock(),
        UuidIdGenerator(),
        auto_dispatch=False,
        journal_max_bytes=journal_max_bytes,
    )
    del reason
    delay_seconds = 0.05

    for attempt in range(4):
        projection = await controller.read_projection(run_id)
        run_state = projection["run_state"]
        if run_state is None or run_state in {"cancelled", "completed", "failed"}:
            return

        position = await controller.current_position(run_id)
        if position == 0:
            return
        try:
            result = await controller.handle_command(
                run_id,
                position,
                "cancel",
                context=GraphCommandContext(
                    run_id=run_id,
                    current_graph_position=position,
                ),
            )
        except StaleProjectionError:
            continue
        except OperationalError as exc:
            if not is_retriable_sqlite_write_conflict(exc) or attempt == 3:
                raise
            await asyncio.sleep(delay_seconds)
            delay_seconds *= 2
            continue

        if any(
            event.event_type == "run_lifecycle_changed"
            and event.payload.get("to_state") == "cancelled"
            for event in result.events
        ):
            return
        if any(
            event.event_type == "command_rejected" and event.payload.get("command_type") == "cancel"
            for event in result.events
        ):
            return

    logger.warning("Graph cancel for %s stayed stale after retries", run_id)


async def _graph_seed_run_config(
    run_config: dict[str, Any],
    worktree_path: Path,
) -> dict[str, Any]:
    seed_config = dict(run_config)
    if not _should_read_dynamic_feature_spec(seed_config):
        return seed_config

    feature_spec_path = str(seed_config["feature_spec_path"])
    content = await asyncio.to_thread(_read_relative_text, worktree_path, feature_spec_path)
    if content is not None:
        seed_config["feature_spec_content"] = content
        seed_config["feature_spec_content_source"] = "worktree"
        return seed_config

    main_worktree = await asyncio.to_thread(resolve_main_worktree, worktree_path)
    if main_worktree is None:
        return seed_config
    content = await asyncio.to_thread(_read_relative_text, main_worktree, feature_spec_path)
    if content is not None:
        seed_config["feature_spec_content"] = content
        seed_config["feature_spec_content_source"] = "main_worktree_fallback"
    return seed_config


def _should_read_dynamic_feature_spec(run_config: dict[str, Any]) -> bool:
    feature_spec_path = run_config.get("feature_spec_path")
    if not isinstance(feature_spec_path, str) or not feature_spec_path.strip():
        return False
    feature_spec_content = run_config.get("feature_spec_content")
    return not isinstance(feature_spec_content, str) or not feature_spec_content.strip()


def _read_relative_text(root: Path, relative_path: str) -> str | None:
    requested = Path(relative_path)
    if requested.is_absolute() or ".." in requested.parts:
        return None
    root_resolved = root.resolve()
    candidate = (root_resolved / requested).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    try:
        return candidate.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


class GraphLoopController(Protocol):
    async def current_position(self, run_id: str) -> int: ...

    async def handle_command(
        self,
        run_id: str,
        expected_position: int,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        context: GraphCommandContext | None = None,
    ) -> Any: ...


class GraphLoopDispatcher(Protocol):
    async def dispatch_pending(self, *, run_id: str | None = None) -> Any: ...

    async def earliest_pending_retry_at(self, *, run_id: str | None = None) -> datetime | None: ...


class GraphLoopExecutor(Protocol):
    def is_running(self, execution_id: str) -> bool: ...

    async def wait_for_all(
        self,
        *,
        timeout_seconds: float | None = None,
        active_execution_ids: set[str] | None = None,
    ) -> None: ...


async def _drive_with_transient_retries(
    operation: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    delay_seconds = 0.05
    for attempt in range(attempts):
        try:
            return await operation()
        except OperationalError as exc:
            if not is_retriable_sqlite_write_conflict(exc) or attempt == attempts - 1:
                raise
            await sleep(delay_seconds)
            delay_seconds *= 2
    raise AssertionError("unreachable")  # pragma: no cover


class GraphRunDriver:
    """Self-advancing production loop for graph-mode runs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        create_service: Callable[[AsyncSession], Awaitable["WorkflowService"]],
        *,
        clock: Clock | None = None,
        id_gen: IdGenerator | None = None,
        runtime_builder: Callable[..., tuple[GraphController, GraphDispatchExecutor]] | None = None,
        dispatcher_factory: Callable[
            [async_sessionmaker[AsyncSession], GraphDispatchExecutor, Clock],
            OutboxDispatcher,
        ]
        | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
        on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
        artifact_stores: ArtifactStoreResolver | None = None,
        journal_max_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self._session_factory = session_factory
        self._create_service = create_service
        self._clock = clock or SystemClock()
        self._id_gen = id_gen or UuidIdGenerator()
        self._runtime_builder = runtime_builder or build_graph_runtime
        self._dispatcher_factory = dispatcher_factory or OutboxDispatcher
        self._sleep = sleep
        self._on_agent_output = on_agent_output
        self._on_agent_usage = on_agent_usage
        self._artifact_stores = artifact_stores or ArtifactStoreResolver(ArtifactRootResolver())
        self._journal_max_bytes = journal_max_bytes

    async def run(self, run_id: str) -> GraphRunOutcome:
        run = await self._get_run(run_id)
        if run.execution_mode != "graph":
            return GraphRunOutcome(
                run_id=run_id,
                run_state=None,
                completed=False,
                blocked_reason="run is not graph execution_mode",
            )
        if run.agent_runner_type == AgentRunnerType.RETIRED:
            return GraphRunOutcome(
                run_id=run_id,
                run_state=None,
                completed=False,
                blocked_reason=(
                    "Graph execution requires an active runner; unsupported runner 'retired'."
                ),
            )
        if run.status == RunStatus.DRAFT:
            await self._apply_start(run_id)
            run = await self._get_run(run_id)
        elif run.status == RunStatus.PAUSED:
            # Re-armed after a restart / recoverable pause: return the run to
            # ACTIVE so the lifecycle bridge can complete it from a valid state.
            await self._apply_resume(run_id)
            run = await self._get_run(run_id)

        if not run.worktree_path:
            await self._apply_pause(run_id, "graph_worktree_missing", "Graph run has no worktree")
            return GraphRunOutcome(
                run_id=run_id,
                run_state=None,
                completed=False,
                blocked_reason="Graph run has no worktree",
            )
        if run.agent_runner_type is None:
            await self._apply_pause(
                run_id,
                "graph_runner_missing",
                "Graph run has no agent runner type",
            )
            return GraphRunOutcome(
                run_id=run_id,
                run_state=None,
                completed=False,
                blocked_reason="Graph run has no agent runner type",
            )
        if run.agent_runner_type not in SUPPORTED_GRAPH_RUNNER_TYPES:
            supported = ", ".join(
                sorted(runner_type.value for runner_type in SUPPORTED_GRAPH_RUNNER_TYPES)
            )
            runner_type = run.agent_runner_type.value
            message = (
                "Graph execution requires a runner with native graph callback tools; "
                f"unsupported runner '{runner_type}'. Supported runners: {supported}."
            )
            await self._apply_pause(run_id, "graph_runner_unsupported", message)
            return GraphRunOutcome(
                run_id=run_id,
                run_state=None,
                completed=False,
                blocked_reason=message,
            )

        controller_position = await self._current_position(run_id)
        is_fresh = controller_position == 0
        if controller_position == 0:
            if run.routine_embedded is None:
                await self._apply_pause(
                    run_id,
                    "graph_routine_missing",
                    "Graph run has no embedded routine",
                )
                return GraphRunOutcome(
                    run_id=run_id,
                    run_state=None,
                    completed=False,
                    blocked_reason="Graph run has no embedded routine",
                )
            routine = RoutineConfig.model_validate(run.routine_embedded)
            seed_run_config = await _graph_seed_run_config(
                run.config,
                Path(run.worktree_path),
            )
            await seed_run(
                self._session_factory,
                routine,
                run_id=run_id,
                clock=self._clock,
                id_gen=self._id_gen,
                source_path=run.routine_path,
                source_ref=run.routine_commit,
                run_config=seed_run_config,
                journal_max_bytes=self._journal_max_bytes,
            )
            await self._bootstrap_graph_lifecycle(run_id)
        elif (
            run.status == RunStatus.ACTIVE
            and run.pause_reason == GRAPH_OPERATOR_REOPEN_PAUSE_REASON
        ):
            # Operator reopen bridge. WorkflowService.apply_resume_run flips a
            # FAILED graph run's row to ACTIVE (an operator-only reopen — see
            # _is_graph_run / RUN_LIFECYCLE_TRANSITIONS), but the durable graph
            # run_state stays "failed". Without moving the kernel too, the drive
            # loop below would classify the run failed and immediately re-fail
            # it, so the operator resume would appear to succeed yet do nothing.
            # Issue the kernel resume command(s) here so the graph actually
            # reopens, keeping the row status and kernel run_state in step.
            #
            # Gated on the persisted GRAPH_OPERATOR_REOPEN_PAUSE_REASON marker
            # (set by apply_resume_run) so a row that is ACTIVE with a failed
            # kernel but NO operator resume — the crash-window stranded-ACTIVE
            # incident, re-armed by select_graph_runs_to_rearm — is NOT
            # spuriously un-failed here. Such a run has no marker and falls
            # through to the drive loop, which re-classifies the failed kernel
            # and lets _apply_fail persist FAILED (the pre-reopen self-heal).
            # Clear the marker immediately after acting so a later autonomous
            # failure + re-arm cannot replay the reopen.
            await self._reopen_failed_graph_lifecycle(run_id)
            await self._clear_reopen_marker(run_id)

        main_worktree = await asyncio.to_thread(resolve_main_worktree, Path(run.worktree_path))
        if main_worktree is None:
            raise ValueError("cannot resolve main project root for graph run")
        runtime_kwargs: dict[str, Any] = {
            "worktree_path": Path(run.worktree_path),
            "runner_type": run.agent_runner_type,
            "runner_config": run.agent_runner_config,
            "artifact_store": await self._artifact_stores.for_run(run),
        }
        if self._on_agent_output is not None:
            runtime_kwargs["on_agent_output"] = self._on_agent_output
        if self._on_agent_usage is not None:
            runtime_kwargs["on_agent_usage"] = self._on_agent_usage
        controller, executor = self._runtime_builder(
            self._session_factory,
            self._clock,
            self._id_gen,
            **runtime_kwargs,
        )
        dispatcher = self._dispatcher_factory(self._session_factory, executor, self._clock)

        # Recover in-flight side effects only when RESUMING an already-seeded run
        # (re-armed after a restart / recoverable pause). A freshly seeded run
        # has nothing in flight, so recovery is skipped. recover() idempotently
        # redispatches pending outbox rows on THIS executor and reconcile_runtime
        # converts leases whose executions are gone into agent_died so the kernel
        # reschedules them — single executor across recovery and the drive loop.
        # Recovery is best-effort priming: if it fails, fall through to the drive
        # loop (its own schedule_tick/dispatch_pending redispatches pending work,
        # and the no-progress guard handles a dead lease) rather than killing the
        # driver task.
        if not is_fresh:
            try:
                report = await recover(self._session_factory, dispatcher, run_id=run_id)
                await reconcile_graph(controller, run_id=run_id)
                await reconcile_runtime(controller, executor, report)
            except Exception:
                logger.exception(
                    "GraphRunDriver: recovery for %s failed; proceeding to drive", run_id
                )

        # Worktree-isolation guard: snapshot the repo's MAIN worktree dirty set
        # before driving, so any path the run leaks into it (an agent escaping its
        # worktree) is flagged immediately rather than discovered later via failing
        # tests. See git/contamination.py and the repos-symlink contamination note.
        before_dirty: set[str] = (
            await asyncio.to_thread(dirty_paths, main_worktree) if main_worktree else set()
        )

        async def _still_active() -> bool:
            current = await self._get_run(run_id)
            return current.status == RunStatus.ACTIVE

        try:
            outcome = await _drive_with_transient_retries(
                lambda: self.drive_to_quiescence(
                    run_id,
                    controller=controller,
                    dispatcher=dispatcher,
                    executor=executor,
                    read_projection=self._read_projection,
                    should_continue=_still_active,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Crash-path bridge. A driver-loop exception (e.g. a transient
            # "database is locked" escaping outbox bookkeeping) would otherwise
            # propagate to _safe_run_graph_driver, which logs and DISCARDS it —
            # leaving the run ACTIVE with no driver, no pause_reason, and no
            # re-arm (the stranded-ACTIVE incident). Pause the run
            # graph_driver_crashed so the stall is visible and resumable,
            # mirroring the graph_blocked bridge below; a later resume re-arms
            # the driver and dispatches bound-and-ready nodes on the first tick.
            # Re-raise so _safe_run_graph_driver still logs the failure.
            logger.exception("GraphRunDriver: drive loop for %s crashed; pausing run", run_id)
            await self._apply_pause(run_id, "graph_driver_crashed", str(exc))
            raise
        # Only bridge graph state onto a run that is still ACTIVE. If the run was
        # cancelled/paused/failed out from under the driver, leave its status as
        # the operator/other path set it.
        current = await self._get_run(run_id)
        if current.status == RunStatus.ACTIVE:
            if outcome.completed:
                await self._apply_complete(run_id)
            elif outcome.run_state == "failed":
                await self._apply_fail(run_id, outcome.blocked_reason)
            else:
                await self._apply_pause(run_id, "graph_blocked", outcome.blocked_reason)

        leaked = find_leaked_paths(
            before_dirty, await asyncio.to_thread(dirty_paths, main_worktree)
        )
        if leaked:
            logger.error(
                "GraphRunDriver: run %s leaked %d path(s) into the repo main "
                "worktree %s: %s — worktree-isolation breach; investigate before "
                "trusting main",
                run_id,
                len(leaked),
                main_worktree,
                sorted(leaked)[:20],
            )
        return outcome

    async def _handle_command_at_head(
        self,
        controller: GraphLoopController,
        run_id: str,
        command_type: str,
        payload: dict[str, object] | None = None,
        *,
        attempts: int = 5,
        actor: Actor | None = None,
    ) -> Any:
        """Issue a driver command at the current event-log head, retrying stale races.

        The loop reads the head position and then appends, while agent REST
        callbacks append concurrently — so the read position can be stale by
        the time the command lands (UNIQUE violation on events_v2 surfaced as
        StaleProjectionError). The loop's own commands (schedule_tick,
        complete) are safe to re-issue at the new head, so re-read and retry
        instead of letting the race kill the driver.
        """
        delay_seconds = 0.01
        for attempt in range(attempts):
            position = await controller.current_position(run_id)
            try:
                return await controller.handle_command(
                    run_id,
                    position,
                    command_type,
                    payload,
                    context=GraphCommandContext(
                        run_id=run_id,
                        current_graph_position=position,
                        actor=actor,
                    ),
                )
            except (OperationalError, StaleProjectionError) as exc:
                if not isinstance(
                    exc, StaleProjectionError
                ) and not is_retriable_sqlite_write_conflict(exc):
                    raise
                if attempt == attempts - 1:
                    raise
                await asyncio.sleep(delay_seconds)
                delay_seconds *= 2
        raise AssertionError("unreachable")  # pragma: no cover

    async def drive_to_quiescence(
        self,
        run_id: str,
        *,
        controller: GraphLoopController,
        dispatcher: GraphLoopDispatcher,
        executor: GraphLoopExecutor,
        read_projection: Callable[[str], Awaitable[GraphProjectionSnapshot]],
        should_continue: Callable[[], Awaitable[bool]] | None = None,
    ) -> GraphRunOutcome:
        previous_position: int | None = None
        # Lease ids the driver has already attempted to revoke via a
        # synthesized agent_died during this call. Bounds the recovery below:
        # a lease that the kernel refuses to revoke (command_rejected, or a
        # race that already resolved it) is never retried, so this loop
        # cannot live-lock on one stuck lease even if state never changes.
        recovered_lease_ids: set[str] = set()
        # Per-node recovery budget, the fail-safe backstop behind the two
        # bounds above. The kernel's max_attempts is the primary bound when
        # present, but it is opportunistic: dynamically-created nodes (planner
        # create_node/create_gate/... patch ops) carry no max_attempts, and
        # without one the kernel's v1 policy requeues the node with a FRESH
        # lease_id on every agent_died — defeating the lease_id dedup and,
        # for a persistent orphaning cause, spinning this loop hot forever.
        # Counting recoveries per node_id is immune to lease_id churn: once a
        # node exceeds the budget the driver stops recovering it and the
        # existing blocked-outcome return fires, restoring the pre-fix
        # fail-safe (pause graph_blocked for an operator).
        node_recovery_counts: dict[str, int] = {}
        while True:
            # Stop driving if the run was cancelled/paused/failed externally, so
            # an operator action (or a failed bridge) halts the agent-dispatch
            # loop instead of retrying dead agents indefinitely.
            if should_continue is not None and not await should_continue():
                return project_graph_outcome(run_id, await read_projection(run_id))
            await self._handle_command_at_head(
                controller,
                run_id,
                "schedule_tick",
                {
                    # 3600, not 300: the kernel's expiry sweep races the driver's
                    # renewal pass, and under projection-replay load (large event
                    # logs) renewals slip past a 5-minute TTL — four finished W3
                    # verifications were discarded as callback_rejected_stale on
                    # 2026-07-05 before this was widened. Long-running verifier
                    # sessions legitimately exceed 300s; orphan detection is
                    # handled by executor liveness, not lease expiry.
                    "lease_seconds": 3600,
                    "max_grants": 10,
                    "base_snapshot_id": "routine-snapshot",
                },
            )
            await dispatcher.dispatch_pending(run_id=run_id)
            wait_projection = await read_projection(run_id)
            clock = getattr(self, "_clock", None) or getattr(controller, "_clock", SystemClock())
            wait_plan = project_active_lease_wait_plan(wait_projection, clock.now())
            await executor.wait_for_all(
                timeout_seconds=wait_plan.timeout_seconds,
                active_execution_ids=wait_plan.execution_ids,
            )
            projection = await read_projection(run_id)
            if await _renew_running_expired_leases(
                run_id,
                controller,
                executor,
                projection,
                clock.now(),
            ):
                previous_position = None
                continue
            if (
                not projection.ready_nodes
                and not projection.active_leases
                and not projection.schedulable_nodes
            ):
                if project_graph_completion_eligible(projection):
                    await self._handle_command_at_head(controller, run_id, "complete")
                    projection = await read_projection(run_id)
                elif projection.run_state == "active":
                    await self._handle_command_at_head(
                        controller,
                        run_id,
                        "reconcile",
                    )
                    projection = await read_projection(run_id)
                    if (
                        projection.ready_nodes
                        or projection.active_leases
                        or projection.schedulable_nodes
                    ):
                        previous_position = None
                        continue
                return project_graph_outcome(run_id, projection)
            # No-progress guard: compare the event-log head AFTER the loop has
            # finished its schedule/dispatch/wait/read/renew/quiescence pass.
            # wait_for_all() blocks while an agent is genuinely running, so
            # reaching here with the same head position means a dispatched
            # execution finished without producing a callback or agent_died,
            # leaving a lease held with nothing schedulable. Before giving up,
            # try to recover any such orphaned lease ourselves (emit
            # agent_died so the kernel revokes it and reschedules the node)
            # rather than pausing the run graph_blocked with a lease that will
            # only be revoked if an operator manually resumes it later. Only
            # return blocked once recovery has nothing left to try.
            position = await controller.current_position(run_id)
            if position == previous_position:
                next_retry_at = await dispatcher.earliest_pending_retry_at(run_id=run_id)
                now = clock.now()
                if next_retry_at is not None:
                    next_retry_at = _align_datetime_timezone(next_retry_at, now)
                if next_retry_at is not None and next_retry_at > now:
                    await self._sleep((next_retry_at - now).total_seconds())
                    previous_position = None
                    continue
                if await _recover_orphaned_active_leases(
                    run_id,
                    controller,
                    executor,
                    projection,
                    recovered_lease_ids,
                    node_recovery_counts,
                ):
                    previous_position = None
                    continue
                return project_graph_outcome(run_id, projection)
            previous_position = position

    async def _bootstrap_graph_lifecycle(self, run_id: str) -> None:
        # Routed through _handle_command_at_head (not a raw controller call)
        # so a transient "database is locked" from unrelated concurrent
        # writers elsewhere in the DB — plausible even for a just-seeded run,
        # since SQLite's write lock is process/file-wide, not per-run — is
        # retried here instead of escaping run() uncaught and stranding the
        # run ACTIVE with no driver (see the graph_driver_crashed comment
        # below for the analogous risk in the main drive loop).
        events = await self._read_events(run_id)
        run_state = project_run_state(events)
        controller = GraphController(
            self._session_factory,
            self._clock,
            self._id_gen,
            journal_max_bytes=self._journal_max_bytes,
        )
        if run_state is None or run_state == "draft":
            await self._handle_command_at_head(controller, run_id, "accept_run")
            await self._handle_command_at_head(controller, run_id, "start")
        elif run_state == "queued":
            await self._handle_command_at_head(controller, run_id, "start")

    async def _reopen_failed_graph_lifecycle(self, run_id: str) -> bool:
        """Reopen a graph run that an operator resumed from FAILED.

        The kernel gates the ``failed -> resuming`` edge on an operator/human
        ``actor_role`` (see _apply_lifecycle_command / REOPEN_ACTOR_ROLES), so
        only this sanctioned driver path — reached solely after an operator
        resume flipped the run row to ACTIVE — can un-fail a run; an agent
        cannot. Reopening takes two lifecycle commands (failed -> resuming ->
        active); the second is ungated. A crash between them leaves the run
        "resuming", from which a re-arm issues only the remaining command.
        Returns True when a reopen command was issued.

        Routed through _handle_command_at_head so a transient "database is
        locked" is retried instead of stranding the run ACTIVE with a still-
        failed kernel (mirrors _bootstrap_graph_lifecycle).
        """
        events = await self._read_events(run_id)
        run_state = project_run_state(events)
        if run_state not in {"failed", "resuming"}:
            return False
        controller = GraphController(
            self._session_factory,
            self._clock,
            self._id_gen,
            journal_max_bytes=self._journal_max_bytes,
        )
        actor = Actor(kind=ActorKind.HUMAN, id="human-operator", role="operator")
        if run_state == "failed":
            await self._handle_command_at_head(controller, run_id, "resume", actor=actor)
        await self._handle_command_at_head(controller, run_id, "resume", actor=actor)
        return True

    async def _read_projection(self, run_id: str) -> GraphProjectionSnapshot:
        events = await self._read_events(run_id)
        return project_graph_projection_snapshot(events)

    async def _read_events(self, run_id: str) -> list[EventEnvelope]:
        async with self._session_factory() as session:
            return await GraphEventStore(session).read_run(run_id)

    async def _current_position(self, run_id: str) -> int:
        async with self._session_factory() as session:
            return await GraphEventStore(session).current_position(run_id)

    async def _get_run(self, run_id: str) -> Any:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            return await service.get_run(run_id)

    async def _apply_start(self, run_id: str) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            await service.apply_start_run(run_id)

    async def _apply_resume(self, run_id: str) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            await service.apply_resume_run(run_id, resume_strategy="continue")

    async def _clear_reopen_marker(self, run_id: str) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            await service.clear_graph_reopen_marker(run_id)

    async def _apply_complete(self, run_id: str) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            await service.apply_complete_run(run_id)

    async def _apply_fail(self, run_id: str, reason: str | None = None) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            await service.apply_fail_run(run_id, reason=reason or "graph failed")

    async def _apply_pause(
        self,
        run_id: str,
        reason: str,
        error_detail: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            run = await service.get_run(run_id)
            if run.status in (RunStatus.ACTIVE, RunStatus.STOPPING):
                await service.apply_pause_run(run_id, reason=reason, error_detail=error_detail)


async def _renew_running_expired_leases(
    run_id: str,
    controller: GraphLoopController,
    executor: GraphLoopExecutor,
    projection: GraphProjectionSnapshot,
    now: datetime,
) -> bool:
    renewed = False
    for lease in projection.active_leases.values():
        if not _active_lease_expired(lease, now):
            continue
        execution_id = lease.get("execution_id")
        if not isinstance(execution_id, str) or not executor.is_running(execution_id):
            continue
        lease_id = lease.get("lease_id")
        node_id = lease.get("node_id")
        if not isinstance(lease_id, str) or not isinstance(node_id, str):
            continue
        payload: dict[str, object] = {
            "lease_id": lease_id,
            "node_id": node_id,
            "ttl_seconds": 3600,
        }
        generation = lease.get("generation")
        if isinstance(generation, int) and not isinstance(generation, bool):
            payload["generation"] = generation
        delay_seconds = 0.01
        for attempt in range(5):
            try:
                result = await controller.handle_command(
                    run_id,
                    (position := await controller.current_position(run_id)),
                    "record_heartbeat",
                    payload,
                    context=GraphCommandContext(
                        run_id=run_id,
                        current_graph_position=position,
                    ),
                )
            except (OperationalError, StaleProjectionError) as exc:
                if not isinstance(
                    exc, StaleProjectionError
                ) and not is_retriable_sqlite_write_conflict(exc):
                    raise
                if attempt == 4:
                    raise
                await asyncio.sleep(delay_seconds)
                delay_seconds *= 2
                continue
            renewed = renewed or any(event.event_type == "lease_renewed" for event in result.events)
            break
    return renewed


async def _recover_orphaned_active_leases(
    run_id: str,
    controller: GraphLoopController,
    executor: GraphLoopExecutor,
    projection: GraphProjectionSnapshot,
    recovered_lease_ids: set[str],
    node_recovery_counts: dict[str, int],
) -> bool:
    """Revoke active leases whose dispatched execution is no longer live on
    THIS executor, so the kernel reschedules (or, once retries are exhausted,
    fails) the node instead of the run staying wedged on a dead lease.

    Mirrors ``graph_runtime.dispatch.reconcile_runtime``'s startup recovery
    (leases with a gone execution become ``agent_died``) for the analogous
    mid-run case: a dispatched execution can finish without an accepted
    callback or an explicit agent_died — e.g. its submit was rejected — and
    the driver's own executor is the only thing that can say the execution
    is no longer live, since a single executor instance spans recovery and
    the drive loop.

    Three bounds keep this from spinning the drive loop forever:

    1. Each lease_id is attempted at most once per drive call
       (``recovered_lease_ids``, owned by the caller and shared across
       iterations): a lease the kernel refuses to revoke (command_rejected —
       e.g. a race already resolved it) is never retried.
    2. Passing ``max_attempts`` (the node's compiled retry budget, when the
       node has one) lets the kernel's own agent_died-retry budget in
       ``_apply_agent_died`` fail the node terminally — same as the runtime's
       normal death path in ``graph_runtime.dispatch._agent_died``. This is
       the primary bound for compiled nodes.
    3. ``node_recovery_counts`` (per node_id, owned by the caller) caps
       recoveries at ``MAX_NODE_RECOVERIES_PER_DRIVE`` regardless of the
       other two. Required because bound 2 is opportunistic — dynamically
       created nodes (planner patch ops) carry no max_attempts, so the
       kernel's v1 policy requeues them with a FRESH lease_id every time,
       defeating bound 1. Once a node exhausts this budget the driver stops
       recovering it and the drive loop's blocked-outcome return fires,
       restoring the pre-recovery fail-safe (pause graph_blocked).
    """
    recovered = False
    for lease in projection.active_leases.values():
        lease_id = lease.get("lease_id")
        if not isinstance(lease_id, str) or lease_id in recovered_lease_ids:
            continue
        node_id = lease.get("node_id")
        node_state = projection.node_states.get(node_id) if isinstance(node_id, str) else None
        if node_state != "running":
            # Deliberately narrower than reconcile_runtime's startup check
            # (which also treats "leased" as orphaned — safe there because a
            # freshly restarted process hasn't dispatched anything yet). Mid
            # drive-loop, "leased" is an ordinary transient state between a
            # lease grant and dispatch_pending() actually starting it (or,
            # for a kind with no matching agent, a real "nothing can ever
            # dispatch this" block that the existing active-lease-without-
            # callback classification already reports correctly). Only a
            # node already "running" matches the incident this recovers: a
            # dispatched execution that finished without producing a
            # callback or agent_died.
            continue
        execution_id = lease.get("execution_id")
        if isinstance(execution_id, str) and execution_id and executor.is_running(execution_id):
            # Still genuinely running on this executor — not orphaned.
            continue

        if isinstance(node_id, str):
            if node_recovery_counts.get(node_id, 0) >= MAX_NODE_RECOVERIES_PER_DRIVE:
                continue
            node_recovery_counts[node_id] = node_recovery_counts.get(node_id, 0) + 1
        recovered_lease_ids.add(lease_id)
        payload: dict[str, object] = {
            "lease_id": lease_id,
            "reason": "runtime_execution_missing_no_callback",
        }
        max_attempts = (
            projection.node_max_attempts.get(node_id) if isinstance(node_id, str) else None
        )
        if isinstance(max_attempts, int):
            payload["max_attempts"] = max_attempts
        if isinstance(execution_id, str) and execution_id:
            payload["execution_id"] = execution_id
        try:
            result = await controller.handle_command(
                run_id,
                (position := await controller.current_position(run_id)),
                "agent_died",
                payload,
                context=GraphCommandContext(
                    run_id=run_id,
                    current_graph_position=position,
                ),
            )
        except StaleProjectionError:
            continue
        if any(event.event_type == "agent_died" for event in result.events):
            recovered = True
    return recovered


def _active_lease_expired(lease: dict[str, Any], now: datetime) -> bool:
    expires_at = lease.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    try:
        expires_at_dt = datetime.fromisoformat(expires_at)
    except ValueError:
        return False
    if expires_at_dt.tzinfo is None:
        expires_at_dt = expires_at_dt.replace(tzinfo=UTC)
    return expires_at_dt <= now


def _align_datetime_timezone(value: datetime, reference: datetime) -> datetime:
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
