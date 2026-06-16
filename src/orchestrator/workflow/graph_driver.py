"""Production driver for graph-backed runs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.config.enums import RunStatus
from datetime import UTC, datetime
from uuid import uuid4

from orchestrator.config.models import RoutineConfig
from orchestrator.git import dirty_paths, find_leaked_paths, resolve_main_worktree
from orchestrator.graph import (
    EventEnvelope,
    project_leases,
    project_node_states,
    project_ready_nodes,
    project_run_state,
    project_task_states,
)
from orchestrator.graph.commands import Clock, IdGenerator
from orchestrator.graph_runtime import (
    GraphController,
    GraphDispatchContext,
    GraphDispatchExecutor,
    GraphEventStore,
    OutboxDispatcher,
    build_graph_runtime,
    recover,
    reconcile_runtime,
    seed_run,
)

if TYPE_CHECKING:
    from orchestrator.workflow.service import WorkflowService

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class GraphRunOutcome:
    run_id: str
    run_state: str | None
    completed: bool
    blocked_reason: str | None = None


def _empty_str_dict() -> dict[str, str]:
    return {}


@dataclass(frozen=True)
class GraphProjectionSnapshot:
    run_state: str | None
    ready_nodes: list[str]
    active_leases: dict[str, dict[str, Any]]
    schedulable_nodes: list[str]
    task_states: dict[str, str]
    node_states: dict[str, str] = field(default_factory=_empty_str_dict)
    failed_node_reasons: dict[str, str] = field(default_factory=_empty_str_dict)


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
    ) -> Any: ...


class GraphLoopDispatcher(Protocol):
    async def dispatch_pending(self) -> Any: ...


class GraphLoopExecutor(Protocol):
    async def wait_for_all(self) -> None: ...


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
        on_agent_output: Callable[[GraphDispatchContext, list[str]], Awaitable[None]] | None = None,
        on_agent_usage: Callable[[GraphDispatchContext, Any], Awaitable[None]] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._create_service = create_service
        self._clock = clock or SystemClock()
        self._id_gen = id_gen or UuidIdGenerator()
        self._runtime_builder = runtime_builder or build_graph_runtime
        self._dispatcher_factory = dispatcher_factory or OutboxDispatcher
        self._on_agent_output = on_agent_output
        self._on_agent_usage = on_agent_usage

    async def run(self, run_id: str) -> GraphRunOutcome:
        run = await self._get_run(run_id)
        if run.execution_mode != "graph":
            return GraphRunOutcome(
                run_id=run_id,
                run_state=None,
                completed=False,
                blocked_reason="run is not graph execution_mode",
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
            )
            await self._bootstrap_graph_lifecycle(run_id)

        runtime_kwargs: dict[str, Any] = {
            "worktree_path": Path(run.worktree_path),
            "runner_type": run.agent_runner_type,
            "runner_config": run.agent_runner_config,
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
                await reconcile_runtime(controller, executor, report)
            except Exception:
                logger.exception(
                    "GraphRunDriver: recovery for %s failed; proceeding to drive", run_id
                )

        # Worktree-isolation guard: snapshot the repo's MAIN worktree dirty set
        # before driving, so any path the run leaks into it (an agent escaping its
        # worktree) is flagged immediately rather than discovered later via failing
        # tests. See git/contamination.py and the repos-symlink contamination note.
        main_worktree = await asyncio.to_thread(resolve_main_worktree, Path(run.worktree_path))
        before_dirty: set[str] = (
            await asyncio.to_thread(dirty_paths, main_worktree) if main_worktree else set()
        )

        async def _still_active() -> bool:
            current = await self._get_run(run_id)
            return current.status == RunStatus.ACTIVE

        outcome = await self.drive_to_quiescence(
            run_id,
            controller=controller,
            dispatcher=dispatcher,
            executor=executor,
            read_projection=self._read_projection,
            should_continue=_still_active,
        )
        # Only bridge graph state onto a run that is still ACTIVE. If the run was
        # cancelled/paused/failed out from under the driver, leave its status as
        # the operator/other path set it.
        current = await self._get_run(run_id)
        if current.status == RunStatus.ACTIVE:
            if outcome.completed:
                await self._apply_complete(run_id)
            else:
                await self._apply_pause(run_id, "graph_blocked", outcome.blocked_reason)

        if main_worktree is not None:
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
        previous_signature: tuple[Any, ...] | None = None
        while True:
            # Stop driving if the run was cancelled/paused/failed externally, so
            # an operator action (or a failed bridge) halts the agent-dispatch
            # loop instead of retrying dead agents indefinitely.
            if should_continue is not None and not await should_continue():
                return classify_graph_outcome(run_id, await read_projection(run_id))
            position = await controller.current_position(run_id)
            await controller.handle_command(
                run_id,
                position,
                "schedule_tick",
                {
                    "lease_seconds": 300,
                    "max_grants": 10,
                    "base_snapshot_id": "routine-snapshot",
                },
            )
            await dispatcher.dispatch_pending()
            await executor.wait_for_all()
            projection = await read_projection(run_id)
            if (
                not projection.ready_nodes
                and not projection.active_leases
                and not projection.schedulable_nodes
            ):
                if _should_complete_graph(projection):
                    position = await controller.current_position(run_id)
                    await controller.handle_command(run_id, position, "complete")
                    projection = await read_projection(run_id)
                return classify_graph_outcome(run_id, projection)
            # No-progress guard: schedule_tick emits audit events (e.g.
            # node_deferred) every call, so raw event position always advances.
            # Compare a signature of meaningful state instead. wait_for_all()
            # blocks while an agent is genuinely running, so reaching here with
            # an unchanged signature means a dispatched execution finished
            # without producing a callback or agent_died, leaving a lease held
            # with nothing schedulable. Repeating cannot help — return a blocked
            # outcome so the run pauses (and can be recovered) rather than
            # spinning a core.
            signature = _progress_signature(projection)
            if signature == previous_signature:
                return classify_graph_outcome(run_id, projection)
            previous_signature = signature

    async def _bootstrap_graph_lifecycle(self, run_id: str) -> None:
        events = await self._read_events(run_id)
        run_state = project_run_state(events)
        controller = GraphController(self._session_factory, self._clock, self._id_gen)
        if run_state is None:
            position = await controller.current_position(run_id)
            result = await controller.handle_command(run_id, position, "accept_run")
            await controller.handle_command(run_id, result.projection_position, "start")
        elif run_state == "draft":
            position = await controller.current_position(run_id)
            result = await controller.handle_command(run_id, position, "accept_run")
            await controller.handle_command(run_id, result.projection_position, "start")
        elif run_state == "queued":
            position = await controller.current_position(run_id)
            await controller.handle_command(run_id, position, "start")

    async def _read_projection(self, run_id: str) -> GraphProjectionSnapshot:
        events = await self._read_events(run_id)
        return _snapshot_from_events(events)

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

    async def _apply_complete(self, run_id: str) -> None:
        async with self._session_factory() as session:
            service = await self._create_service(session)
            await service.apply_complete_run(run_id)

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


def _progress_signature(projection: GraphProjectionSnapshot) -> tuple[Any, ...]:
    """A signature of meaningful drive state, ignoring audit-only churn.

    Two consecutive drive iterations with the same signature mean no progress
    was made (no lease/state/task transition), so the loop must stop instead of
    spinning on schedule_tick's per-tick audit events.
    """
    leases = tuple(
        sorted(
            (lease_id, str(lease.get("state")), str(lease.get("node_id")))
            for lease_id, lease in projection.active_leases.items()
        )
    )
    return (
        projection.run_state,
        tuple(sorted(projection.ready_nodes)),
        tuple(sorted(projection.schedulable_nodes)),
        tuple(sorted(projection.task_states.items())),
        leases,
    )


def _snapshot_from_events(events: list[EventEnvelope]) -> GraphProjectionSnapshot:
    leases = project_leases(events)
    node_states = project_node_states(events)
    active_leases = {
        lease_id: lease for lease_id, lease in leases.items() if lease.get("state") == "active"
    }
    return GraphProjectionSnapshot(
        run_state=project_run_state(events),
        ready_nodes=project_ready_nodes(events),
        active_leases=active_leases,
        schedulable_nodes=[
            node_id
            for node_id, state in node_states.items()
            if state in {"planned", "blocked", "ready"}
        ],
        task_states=project_task_states(events),
        node_states=node_states,
        failed_node_reasons=_failed_node_reasons(events),
    )


def _failed_node_reasons(events: list[EventEnvelope]) -> dict[str, str]:
    reasons: dict[str, str] = {}
    for event in events:
        node_id = event.payload.get("node_id")
        if not isinstance(node_id, str):
            continue
        if event.event_type == "agent_died":
            reason = event.payload.get("reason")
            if isinstance(reason, str):
                reasons[node_id] = reason
        elif event.event_type == "node_state_changed":
            if event.payload.get("new_state") != "failed":
                continue
            reason = event.payload.get("reason")
            if isinstance(reason, str):
                reasons[node_id] = reason
    return reasons


def _should_complete_graph(projection: GraphProjectionSnapshot) -> bool:
    return (
        projection.run_state == "active"
        and bool(projection.task_states)
        and all(state == "accepted" for state in projection.task_states.values())
    )


def classify_graph_outcome(
    run_id: str,
    projection: GraphProjectionSnapshot,
) -> GraphRunOutcome:
    if projection.run_state == "completed":
        return GraphRunOutcome(run_id=run_id, run_state=projection.run_state, completed=True)
    return GraphRunOutcome(
        run_id=run_id,
        run_state=projection.run_state,
        completed=False,
        blocked_reason=_blocked_reason(projection),
    )


def _blocked_reason(projection: GraphProjectionSnapshot) -> str:
    if projection.run_state in {"paused", "pausing"}:
        return "graph paused"
    if projection.run_state in {"failed", "cancelled"}:
        return f"graph {projection.run_state}"
    if projection.run_state is None:
        return "graph has not started"
    if projection.ready_nodes:
        return f"graph has ready node(s) not dispatched: {', '.join(sorted(projection.ready_nodes)[:3])}"
    if projection.active_leases:
        leased_nodes = sorted(
            str(lease.get("node_id"))
            for lease in projection.active_leases.values()
            if lease.get("node_id") is not None
        )
        if leased_nodes:
            return f"graph has active lease(s) without callback: {', '.join(leased_nodes[:3])}"
    failed_nodes = sorted(
        node_id for node_id, state in projection.node_states.items() if state == "failed"
    )
    if failed_nodes:
        details: list[str] = []
        for node_id in failed_nodes[:3]:
            reason = projection.failed_node_reasons.get(node_id)
            details.append(f"{node_id}: {reason}" if reason else node_id)
        suffix = "" if len(failed_nodes) <= 3 else f" (+{len(failed_nodes) - 3} more)"
        return f"graph has failed node(s): {', '.join(details)}{suffix}"
    return "graph quiescent without completion"
