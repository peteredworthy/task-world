"""FastAPI application factory."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from orchestrator.api.auth import (
    AuthConfig,
    create_token,
    get_require_auth,
    get_require_ws_auth,
    resolve_auth_config,
)
from orchestrator.api.errors import register_error_handlers
from orchestrator.api.websocket import BatchingConnectionManager, ConnectionManager
from orchestrator.config.enums import RoutineSource, RunStatus
from orchestrator.config.global_config import GlobalConfig, load_global_config
from orchestrator.db import create_engine, create_session_factory, init_db
from orchestrator.state.models import Run
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.envfiles.cleanup import EnvFileCleanup

logger = logging.getLogger(__name__)


def _is_startup_recoverable_pause_reason(reason: str | None) -> bool:
    """Return True when a paused run should be auto-resumed on startup.

    `executor_not_started` is a transient safety marker written just before the
    executor loop begins. If the process dies after writing that marker but
    before the first loop iteration clears it, the run is left paused even
    though the correct recovery action is to continue from the current state.

    Cascade reasons (`parent_*`) reflect *why* a child was paused (their parent
    was being controlled) but recoverability is determined by the underlying
    reason, so strip the prefix before checking. A child paused as
    `parent_server_shutdown` is just as recoverable as one paused with
    `server_shutdown` directly.
    """
    if reason is None:
        return False
    canonical = reason.removeprefix("parent_")
    return canonical in (
        "server_shutdown",
        "agent_not_running_on_startup",
        "executor_not_started",
    )


_STARTUP_RECOVERY_RUN_STAGGER_SECONDS = 0.25


def _topological_sort_children_first(runs: list[Run]) -> list[Run]:
    """Order runs so each run appears after every descendant in the input set.

    Uses each run's `parent_run_id` link. Runs whose parent is not in the input
    set (typical: parent is ACTIVE, terminal, or unrelated) are treated as
    roots and emitted last among their tree level. Cycles cannot occur given
    the parent/child invariant but are tolerated defensively.
    """
    by_id = {r.id: r for r in runs}
    children_of: dict[str, list[str]] = {r.id: [] for r in runs}
    roots: list[str] = []
    for r in runs:
        pid = r.parent_run_id
        if pid in by_id:
            children_of[pid].append(r.id)
        else:
            roots.append(r.id)

    ordered: list[Run] = []
    visited: set[str] = set()

    def visit(run_id: str) -> None:
        if run_id in visited:
            return
        visited.add(run_id)
        for child_id in children_of.get(run_id, []):
            visit(child_id)
        ordered.append(by_id[run_id])

    for root_id in roots:
        visit(root_id)
    # Defensive: any cycle-bound nodes the root walk missed.
    for r in runs:
        visit(r.id)
    return ordered


async def _run_startup_recovery(app: FastAPI) -> None:
    """Recover and resume runs after the HTTP server has finished startup."""
    import asyncio as _asyncio

    from orchestrator.config.enums import AgentRunnerType as _AT
    from orchestrator.db import RunRepository

    session_factory = app.state.session_factory
    global_config = app.state.global_config
    runner_monitor = getattr(app.state, "runner_monitor", None)

    managed_runner_types = (
        _AT.CLI_SUBPROCESS,
        _AT.OPENHANDS_LOCAL,
        _AT.OPENHANDS_DOCKER,
        _AT.CODEX_SERVER,
        _AT.CLAUDE_SDK,
    )

    try:
        if runner_monitor is not None:
            # Check all ACTIVE runs and pause those with dead agents. Each
            # on_agent_died call creates its own session and commits.
            paused_runs = await runner_monitor.recover_active_runs_on_startup()
            if paused_runs:
                logger.info(
                    f"Startup recovery: moved {len(paused_runs)} runs to PAUSED (dead agents)"
                )
            else:
                logger.info("Startup recovery: no dead agents found")

        if not hasattr(app.state, "runner_executor"):
            return

        executor = app.state.runner_executor
        service_factory = app.state.service_factory

        # Re-spawn executor loops for ACTIVE runs whose agents are still alive.
        # After a server reload, the asyncio tasks that drive the agent loop are
        # lost even though the agent subprocess may still be running. Without
        # re-spawning, these runs are orphaned: the agent finishes but nobody
        # handles the next phase (verification, next task, run completion).
        async with session_factory() as session:
            repo = RunRepository(session)
            active_runs = await repo.list_by_status(RunStatus.ACTIVE, include_action_logs=False)

        for run in active_runs:
            if run.agent_runner_type and run.agent_runner_type in managed_runner_types:
                if not executor.is_running(run.id):
                    spawned = executor.spawn_for_run(
                        run.id, run.agent_runner_type, run.agent_runner_config
                    )
                    if spawned:
                        logger.info(
                            f"Startup recovery: re-spawned executor loop for "
                            f"active run {run.id} ({run.agent_runner_type.value})"
                        )
                        await _asyncio.sleep(_STARTUP_RECOVERY_RUN_STAGGER_SECONDS)

        # Auto-resume runs that were paused by restart-recoverable causes.
        # When the server reloads, it cancels running executor tasks and marks
        # those runs as paused with reason "server_shutdown". The executor also
        # writes a transient "executor_not_started" marker before the first loop
        # iteration; if a shutdown lands in that window, startup recovery must
        # continue from current state rather than leaving the run stranded.
        async with session_factory() as session:
            repo = RunRepository(session)
            paused_runs_all = await repo.list_by_status(RunStatus.PAUSED, include_action_logs=False)
            shutdown_runs = [
                r
                for r in paused_runs_all
                if _is_startup_recoverable_pause_reason(r.pause_reason)
                and r.agent_runner_type is not None
                and r.agent_runner_type in managed_runner_types
            ]

        # Resume children before parents. A super-parent run queries its
        # children's oversight state immediately on resume; if a child is still
        # paused, the parent sees a non-terminal blocker and routes to
        # `review_child_evidence` instead of continuing its workflow. By
        # bringing children up first, the parent observes them as ACTIVE (or
        # already terminal) when its own loop restarts.
        shutdown_runs = _topological_sort_children_first(shutdown_runs)

        for run in shutdown_runs:
            try:
                # If worktree is enabled but the directory is missing, recreate
                # it before resuming. This happens when the server crashed before
                # cleanup ran or when the directory was removed by the startup
                # cleanup for an older run.
                if run.worktree_enabled and run.worktree_path:
                    wt_path = Path(run.worktree_path)
                    if not wt_path.exists() or not (wt_path / ".git").exists():
                        try:
                            from orchestrator.git.worktree import WorktreeManager as _WTM

                            repos_dir = global_config.paths.get_repos_path()
                            worktrees_dir = global_config.paths.get_worktrees_path()
                            repo_path = repos_dir / run.repo_name
                            if repo_path.is_dir() and run.source_branch:
                                wt_mgr = _WTM(
                                    repo_path,
                                    worktrees_dir,
                                    server_port=global_config.server.port,
                                    worktree_base_port=global_config.server.worktree_base_port,
                                )
                                wt_mgr.ensure_exists(
                                    run.id,
                                    run.source_branch,
                                    worktree_path=run.worktree_path,
                                )
                                logger.info(
                                    f"Startup recovery: recreated missing worktree for run {run.id}"
                                )
                            else:
                                logger.warning(
                                    f"Startup recovery: cannot recreate worktree for "
                                    f"run {run.id} (repo '{run.repo_name}' not found "
                                    f"or no source_branch); skipping auto-resume"
                                )
                                continue
                        except Exception as wt_err:
                            logger.warning(
                                f"Startup recovery: worktree recreation failed for "
                                f"run {run.id}: {wt_err}; skipping auto-resume"
                            )
                            continue

                async with session_factory() as session:
                    svc = await service_factory(session)
                    await svc.apply_resume_run(run.id, resume_strategy="continue")
                    await session.commit()

                agent_runner_type = run.agent_runner_type
                assert agent_runner_type is not None  # filtered above
                spawned = executor.spawn_for_run(run.id, agent_runner_type, run.agent_runner_config)
                if spawned:
                    logger.info(
                        f"Startup recovery: auto-resumed run {run.id} "
                        f"({agent_runner_type.value}) after server shutdown"
                    )
                await _asyncio.sleep(_STARTUP_RECOVERY_RUN_STAGGER_SECONDS)
            except Exception as resume_err:
                logger.warning(
                    f"Startup recovery: failed to auto-resume run {run.id}: {resume_err}"
                )
    except _asyncio.CancelledError:
        raise
    except Exception as e:
        # If recovery fails (e.g., during first startup with no tables), log but
        # do not crash the application.
        logger.warning(f"Startup recovery failed: {e}")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: create tables on startup, dispose engine on shutdown."""
    from orchestrator.runners import AgentRunnerMonitor
    from orchestrator.db import RunRepository
    from orchestrator.api.deps import make_service_factory, make_workflow_runner

    await init_db(app.state.engine)

    session_factory = app.state.session_factory

    # Build and store the shared WorkflowService factory for background tasks
    # (signal consumer, stale-run sweeper, startup recovery, MCP handler).
    # Request handlers continue to use get_workflow_service() via Depends().
    service_factory = make_service_factory(
        connection_manager=app.state.connection_manager,
        lock_manager=getattr(app.state, "lock_manager", None),
        signal_transport_override=getattr(app.state, "signal_transport", None),
        global_config=app.state.global_config,
        env_lifecycle=getattr(app.state, "env_lifecycle", None),
    )
    app.state.service_factory = service_factory

    # Inject factory into executor so it uses the same service construction path
    # as the signal consumer and request handlers.
    if hasattr(app.state, "runner_executor"):
        app.state.runner_executor.set_service_factory(service_factory)

    # Seed factory-default agents (Planner, Builder, Verifier) if not present
    from orchestrator.runners import seed_default_agents

    async with session_factory() as _seed_session:
        await seed_default_agents(_seed_session)
    global_config = app.state.global_config

    # Create runner_monitor instance with session_factory (no bound session).
    # Pass the shared lock_manager so on_agent_died can release orphaned locks.
    runner_monitor = AgentRunnerMonitor(
        session_factory,
        global_config,
        lock_manager=getattr(app.state, "lock_manager", None),
    )
    app.state.runner_monitor = runner_monitor

    # Clean up orphaned env file snapshots
    if hasattr(app.state, "envfile_store"):
        try:
            async with session_factory() as session:
                repo = RunRepository(session)
                cleanup = EnvFileCleanup(app.state.envfile_store)
                active_ids: set[str] = {run.id for run in await repo.list_all()}
                removed = cleanup.cleanup_deleted_runs(active_ids)
                if removed:
                    logger.info(f"Cleaned up {removed} orphaned env file snapshot(s)")
        except Exception as e:
            logger.warning(f"Env file cleanup failed: {e}")

    # Clean up expired worktrees
    try:
        from datetime import timedelta

        from orchestrator.git.worktree import WorktreeManager

        async with session_factory() as session:
            repo = RunRepository(session)
            all_runs = await repo.list_all()

        all_run_ids = {r.id for r in all_runs}
        terminal = {RunStatus.COMPLETED, RunStatus.FAILED}
        run_completed_at = {
            r.id: r.completed_at
            for r in all_runs
            if r.status in terminal and r.completed_at is not None
        }
        retention = timedelta(days=global_config.paths.worktree_retention_days)

        repos_dir = global_config.paths.get_repos_path()
        worktrees_dir = global_config.paths.get_worktrees_path()

        if repos_dir.is_dir():
            total_removed = 0
            for repo_dir in repos_dir.iterdir():
                if repo_dir.is_dir() and (repo_dir / ".git").exists():
                    # Prune stale git worktree entries (directories deleted outside
                    # of WorktreeManager) so that cleanup_expired sees an accurate list.
                    import subprocess as _subproc

                    _subproc.run(
                        ["git", "worktree", "prune"],
                        cwd=repo_dir,
                        capture_output=True,
                    )
                    wt_mgr = WorktreeManager(
                        repo_dir,
                        worktrees_dir,
                        server_port=global_config.server.port,
                        worktree_base_port=global_config.server.worktree_base_port,
                    )
                    total_removed += wt_mgr.cleanup_expired(
                        all_run_ids, run_completed_at, retention
                    )
            if total_removed:
                logger.info(f"Cleaned up {total_removed} expired/orphaned worktree(s)")
    except Exception as e:
        logger.warning(f"Worktree cleanup failed: {e}")

    # Start periodic stale-run sweeper: detects runs stuck in ACTIVE with no
    # running executor task and pauses them. This is defense-in-depth against
    # edge cases where the executor loop exits without pausing the run.
    import asyncio as _asyncio

    stale_run_sweeper: _asyncio.Task[None] | None = None
    startup_recovery_task: _asyncio.Task[None] | None = None
    if hasattr(app.state, "runner_executor"):

        async def _sweep_stale_runs() -> None:
            executor = app.state.runner_executor
            while True:
                await _asyncio.sleep(60)  # Check every 60 seconds
                try:
                    async with session_factory() as session:
                        repo = RunRepository(session)
                        active_runs = await repo.list_by_status(
                            RunStatus.ACTIVE, include_action_logs=False
                        )
                    for run in active_runs:
                        if executor.is_running(run.id):
                            continue

                        # Double-check: is_running already considers both
                        # _running_tasks and heartbeat.  If we get here, the
                        # executor loop is genuinely gone.  Log heartbeat age
                        # for diagnostics.
                        last_hb = executor.last_heartbeat(run.id)
                        hb_info = (
                            f"last heartbeat {last_hb.isoformat()}"
                            if last_hb
                            else "no heartbeat recorded"
                        )
                        logger.warning(
                            f"Stale run sweeper: run {run.id} is ACTIVE but "
                            f"has no executor task ({hb_info}) — pausing"
                        )
                        try:
                            async with session_factory() as session:
                                svc = await service_factory(session)
                                await svc.apply_pause_run(run.id, reason="no_executor_running")
                                await session.commit()
                                logger.info(f"Stale run sweeper: paused run {run.id}")
                        except Exception as e:
                            logger.warning(f"Stale run sweeper: failed to pause run {run.id}: {e}")
                except _asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.warning(f"Stale run sweeper: error: {e}")

        stale_run_sweeper = _asyncio.create_task(_sweep_stale_runs())

    # Start signal consumer — must start before any signals can be enqueued (R3).
    from orchestrator.workflow import SignalConsumer

    signal_consumer = SignalConsumer(
        session_factory=session_factory,
        create_service=service_factory,
        workflow_runner=make_workflow_runner(getattr(app.state, "runner_executor", None)),
    )
    app.state.signal_consumer = signal_consumer
    await signal_consumer.start()

    # Register quota-capable agent instances for the tool detector.  Deferred
    # to lifespan so optional heavy SDKs (openhands.sdk ~1.5s) are not imported
    # at create_app() time.  Test fixtures skip lifespan, so quota stays None.
    try:
        from orchestrator.runners import (  # noqa: PLC0415
            ClaudeCliQuotaAgent,
            ClaudeSDKAgent,
            CodexServerAgent,
            OpenHandsAgent,
        )

        tool_detector = getattr(app.state, "tool_detector", None)
        if tool_detector is not None:
            for _agent in [
                OpenHandsAgent(),
                CodexServerAgent(),
                ClaudeCliQuotaAgent(),
                ClaudeSDKAgent(),
            ]:
                tool_detector.register_quota_agent(_agent)
    except Exception:
        pass  # Quota fetching is non-critical

    # Defer run recovery/resume until the lifespan is ready to yield. This lets
    # the HTTP server become reachable before old runs are reattached or
    # restarted, and it reduces SQLite contention during the boot path.
    startup_recovery_task = _asyncio.create_task(_run_startup_recovery(app))
    app.state.startup_recovery_task = startup_recovery_task

    yield

    if not startup_recovery_task.done():
        startup_recovery_task.cancel()
        try:
            await startup_recovery_task
        except _asyncio.CancelledError:
            pass

    # Stop signal consumer
    await signal_consumer.stop()

    # Cancel stale-run sweeper
    if stale_run_sweeper is not None:
        stale_run_sweeper.cancel()
        try:
            await stale_run_sweeper
        except _asyncio.CancelledError:
            pass

    # Cancel all running agent background tasks before disposing the engine.
    # Without this, background sessions try to rollback on a closed connection
    # causing "OperationalError: no active connection" during shutdown.
    if hasattr(app.state, "runner_executor"):
        from asyncio import Task as _AsyncTask

        from orchestrator.runners.executor import AgentRunnerExecutor

        executor: AgentRunnerExecutor = app.state.runner_executor
        pending_tasks: list[_AsyncTask[Any]] = []
        for run_id in list(executor._running_tasks):  # pyright: ignore[reportPrivateUsage]
            task = executor._running_tasks.pop(run_id, None)  # pyright: ignore[reportPrivateUsage]
            if task and not task.done():
                task.cancel()
                pending_tasks.append(task)
        if pending_tasks:
            import asyncio

            await asyncio.gather(*pending_tasks, return_exceptions=True)

    await app.state.engine.dispose()


def create_app(
    db_path: str | None = None,
    routine_dirs: list[tuple[Path, RoutineSource]] | None = None,
    auth_disabled: bool | None = None,
    jwt_secret: str | None = None,
    spawn_agents: bool | None = None,
    global_config: GlobalConfig | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the SQLite database file. Falls back to global config,
            then ``"orchestrator.db"``.
        routine_dirs: Directories to scan for routines, with their source type.
            Falls back to global config ``routines.dirs``.
        auth_disabled: Whether to disable authentication. Defaults to True.
        jwt_secret: JWT signing secret. Auto-generated if empty when auth is enabled.
        spawn_agents: Whether to spawn managed agents when runs start. Defaults to
            True for production, False when using in-memory SQLite (tests).
        global_config: Optional pre-built global configuration. Falls back to
            loading from ``~/.orchestrator/config.yaml``.
    """
    # Load global config for defaults
    global_cfg = global_config or load_global_config()

    if db_path is None:
        db_path = global_cfg.database.path

    if routine_dirs is None and global_cfg.routines.dirs:
        routine_dirs = [(Path(d), RoutineSource.LOCAL) for d in global_cfg.routines.dirs]

    app = FastAPI(
        title="Orchestrator",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    # CORS
    # Default to common local frontend origins so localhost/127.0.0.1 host swaps
    # don't trigger false "backend unreachable" errors in development.
    default_cors_origins = ",".join(
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ]
    )
    cors_origins = os.environ.get("CORS_ORIGINS", default_cors_origins).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store dependencies on app.state (no global state)
    engine = create_engine(db_path)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.routine_dirs = routine_dirs or []
    app.state.global_config = global_cfg

    # WebSocket connection manager (with optional batching)
    if global_cfg.websocket.batching_enabled:
        app.state.connection_manager = BatchingConnectionManager(
            batch_window=global_cfg.websocket.batch_window_seconds,
            batching_enabled=True,
        )
    else:
        app.state.connection_manager = ConnectionManager()

    # Authentication
    auth_config = resolve_auth_config(auth_disabled=auth_disabled, jwt_secret=jwt_secret)
    app.state.auth_config = auth_config

    if not auth_config.auth_disabled:
        token = create_token(auth_config)
        logger.info("Auth enabled. JWT secret: %s", auth_config.jwt_secret)
        logger.info("Auth enabled. Access token: %s", token)

    # Build auth dependencies
    require_auth = get_require_auth(auth_config)
    require_ws_auth = get_require_ws_auth(auth_config)

    # Auto-discover agent packages and register their factories
    from orchestrator.runners import discover_agents

    discover_agents()

    # Agent tool detector — no quota agents at create_app() time to avoid
    # importing optional heavy SDKs (openhands.sdk ~1.5s) on every worker startup.
    # Quota agents are registered in _lifespan (below), which only fires for
    # the live server — test fixtures using ASGITransport skip lifespan entirely.
    from orchestrator.runners import ToolDetector

    app.state.tool_detector = ToolDetector()

    # Shared lock manager (singleton for task-level pessimistic locking)
    from orchestrator.workflow.locks import InMemoryLockManager

    app.state.lock_manager = InMemoryLockManager()

    # Env file store (manages environment file snapshots)
    app.state.envfile_store = EnvFileStore()

    # Env file lifecycle (manages snapshots across run/task lifecycle)
    app.state.env_lifecycle = EnvFileLifecycle(app.state.envfile_store)

    # Test runner for review workbench test execution
    from orchestrator.git import TestRunner

    app.state.test_runner = TestRunner()

    # Run-scoped summary caches (keyed by run_id) for context_from artifact summaries.
    # Shared across requests so repeated prompt calls for the same run reuse cached results.
    app.state.summary_caches = {}  # dict[str, Any] — keyed by run_id

    # Create a preliminary service factory so background components (MCP handler,
    # executor) have a usable factory even in tests that skip the lifespan.
    # The lifespan will replace this with a fully-configured factory that includes
    # any signal_transport override injected by tests after create_app() returns.
    from orchestrator.api.deps import make_service_factory as _make_sf

    app.state.service_factory = _make_sf(
        connection_manager=app.state.connection_manager,
        lock_manager=app.state.lock_manager,
        global_config=global_cfg,
        env_lifecycle=app.state.env_lifecycle,
    )

    # Agent executor for spawning managed agents (created here so it's available
    # in tests that don't run the lifespan).
    # When WORKER_SEPARATE=true the executor runs in a separate worker process;
    # the API only enqueues signals via the DB and does NOT spawn agents itself.
    from orchestrator.runners.executor import AgentRunnerExecutor

    worker_separate = os.environ.get("WORKER_SEPARATE", "").lower() in ("1", "true", "yes")

    # Disable agent spawning for in-memory SQLite (tests), unless explicitly enabled
    if spawn_agents is None:
        if worker_separate:
            spawn_agents = False
        else:
            spawn_agents = db_path != ":memory:"

    # Note: runner_monitor will be set in lifespan if available, but AgentRunnerExecutor
    # can lazy-initialize it if needed. This avoids circular dependencies.
    app.state.runner_executor = AgentRunnerExecutor(
        session_factory=app.state.session_factory,
        global_config=global_cfg,
        lock_manager=app.state.lock_manager,
        runner_monitor=getattr(app.state, "runner_monitor", None),
        connection_manager=app.state.connection_manager,
        service_factory=app.state.service_factory,
        spawn_agents=spawn_agents,
    )

    if worker_separate:
        logger.info(
            "WORKER_SEPARATE=true: API will not spawn agents — executor runs in worker process"
        )

    register_error_handlers(app)

    # Register routers with auth dependency
    from orchestrator.api.routers.agents import router as agents_router
    from orchestrator.api.routers.runners import router as agent_runners_router
    from orchestrator.api.routers.clarifications import router as clarifications_router
    from orchestrator.api.routers.config import router as config_router
    from orchestrator.api.routers.envfiles import router as envfiles_router
    from orchestrator.api.routers.model_profiles import router as model_profiles_router
    from orchestrator.api.routers.repos import router as repos_router
    from orchestrator.api.routers.review import router as review_router
    from orchestrator.api.routers.routines import router as routines_router
    from orchestrator.api.routers.runs import router as runs_router
    from orchestrator.api.routers.tasks import router as tasks_router

    auth_deps = [Depends(require_auth)]
    app.include_router(agents_router, dependencies=auth_deps)
    app.include_router(agent_runners_router, dependencies=auth_deps)
    app.include_router(clarifications_router, dependencies=auth_deps)
    app.include_router(config_router, dependencies=auth_deps)
    app.include_router(envfiles_router, dependencies=auth_deps)
    app.include_router(model_profiles_router, dependencies=auth_deps)
    app.include_router(repos_router, dependencies=auth_deps)
    app.include_router(review_router, dependencies=auth_deps)
    app.include_router(routines_router, dependencies=auth_deps)
    app.include_router(runs_router, dependencies=auth_deps)
    app.include_router(tasks_router, dependencies=auth_deps)

    # Mount MCP SSE transport at /mcp (with auth middleware)
    _mount_mcp_sse(app, auth_config)

    @app.get("/health")
    async def health() -> dict[str, str]:  # type: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.websocket("/ws/runs/{run_id}")
    async def websocket_endpoint(  # type: ignore[reportUnusedFunction]
        websocket: WebSocket,
        run_id: str,
        _claims: dict[str, Any] | None = Depends(require_ws_auth),
    ) -> None:
        manager: ConnectionManager = app.state.connection_manager
        await manager.connect(run_id, websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            manager.disconnect(run_id, websocket)

    return app


class _SessionPerCallHandler:
    """MCP tool handler that creates a fresh DB session per tool call.

    Each MCP tool invocation gets its own session, repository, and
    WorkflowService so that concurrent SSE connections don't share
    mutable state.
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app

    async def handle(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from orchestrator.api.mcp.tools import ToolHandler

        session_factory = self._app.state.session_factory
        service_factory = self._app.state.service_factory
        settings = getattr(self._app.state, "settings", None)
        repos_dir = settings.repos_dir if settings else None
        async with session_factory() as session:
            service = await service_factory(session)
            handler = ToolHandler(service, repos_dir=repos_dir)
            return await handler.handle(tool_name, arguments)


def _mount_mcp_sse(app: FastAPI, auth_config: AuthConfig) -> None:
    """Create and mount the MCP SSE transport.

    Creates an OrchestratorMCPServer backed by a session-per-call handler
    and mounts it at ``/mcp``, exposing ``/mcp/sse`` and ``/mcp/messages``.

    When auth is enabled, wraps the MCP sub-app with middleware that checks
    for a valid Bearer token.
    """
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import JSONResponse
    from starlette.types import ASGIApp, Receive, Scope, Send

    from orchestrator.api.auth import InvalidTokenError, validate_token
    from orchestrator.api.mcp.server import ALL_TOOLS, OrchestratorMCPServer

    handler = _SessionPerCallHandler(app)
    mcp_server = OrchestratorMCPServer(handler=handler)  # type: ignore[arg-type]
    app.state.mcp_server = mcp_server

    mcp_asgi = mcp_server.sse_app

    class _ScopedMcpDispatcher:
        """Serve per-tool-allowlist orchestrator MCP servers under /mcp-scoped."""

        def __init__(self, inner_handler: _SessionPerCallHandler) -> None:
            self._handler = inner_handler
            self._apps: dict[str, ASGIApp] = {}

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http":
                response = JSONResponse(
                    status_code=404,
                    content={"detail": "Scoped MCP only supports HTTP transport"},
                )
                await response(scope, receive, send)
                return

            from urllib.parse import unquote

            raw_path = str(scope.get("path", "")).strip("/")
            if raw_path.startswith("mcp-scoped/"):
                raw_path = raw_path.removeprefix("mcp-scoped/")
            scope_key, _, rest = raw_path.partition("/")
            decoded_scope_key = unquote(scope_key)
            tool_names = {name for name in decoded_scope_key.split(",") if name}
            if not rest or not tool_names or not tool_names.issubset(ALL_TOOLS):
                response = JSONResponse(
                    status_code=404,
                    content={"detail": "Unknown scoped MCP tool set"},
                )
                await response(scope, receive, send)
                return

            scoped_app = self._apps.get(decoded_scope_key)
            if scoped_app is None:
                scoped_server = OrchestratorMCPServer(
                    handler=self._handler,  # type: ignore[arg-type]
                    allowed_tools=tool_names,
                )
                scoped_app = scoped_server.mcp.sse_app(mount_path="/")
                self._apps[decoded_scope_key] = scoped_app

            root_path = str(scope.get("root_path") or "").rstrip("/")
            if root_path.endswith("/mcp-scoped"):
                scoped_root_path = f"{root_path}/{decoded_scope_key}"
            else:
                scoped_root_path = f"{root_path}/mcp-scoped/{decoded_scope_key}"
            scoped_scope = dict(scope)
            if rest == "messages":
                scoped_scope["root_path"] = ""
                scoped_scope["path"] = "/messages/"
            elif rest.startswith("messages/"):
                scoped_scope["root_path"] = ""
                scoped_scope["path"] = f"/{rest}"
            else:
                scoped_scope["root_path"] = scoped_root_path
                scoped_scope["path"] = f"{scoped_root_path}/{rest}"
            await scoped_app(scoped_scope, receive, send)

    scoped_mcp_asgi = _ScopedMcpDispatcher(handler)

    if auth_config.auth_disabled:
        app.mount("/mcp", mcp_asgi)  # type: ignore[arg-type]
        app.mount("/mcp-scoped", scoped_mcp_asgi)  # type: ignore[arg-type]
    else:

        class _McpAuthMiddleware:
            """ASGI middleware that enforces Bearer token auth on MCP routes."""

            def __init__(self, inner_app: ASGIApp) -> None:
                self.app = inner_app

            async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                if scope["type"] == "http":
                    request = StarletteRequest(scope, receive, send)
                    auth_header = request.headers.get("authorization", "")
                    parts = auth_header.split(" ", 1)
                    if len(parts) != 2 or parts[0].lower() != "bearer":
                        response = JSONResponse(
                            status_code=401,
                            content={"detail": "Missing or invalid authorization header"},
                        )
                        await response(scope, receive, send)
                        return
                    try:
                        validate_token(auth_config, parts[1])
                    except InvalidTokenError:
                        response = JSONResponse(
                            status_code=401,
                            content={"detail": "Invalid token"},
                        )
                        await response(scope, receive, send)
                        return

                await self.app(scope, receive, send)

        app.mount("/mcp", _McpAuthMiddleware(mcp_asgi))  # type: ignore[arg-type]
        app.mount("/mcp-scoped", _McpAuthMiddleware(scoped_mcp_asgi))  # type: ignore[arg-type]

    # Serve architecture documentation site as static files
    _docs_dir = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "architecture-site"
    if _docs_dir.is_dir():
        app.mount("/docs", StaticFiles(directory=str(_docs_dir), html=True), name="docs")
