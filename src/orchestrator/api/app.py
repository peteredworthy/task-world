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
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.envfiles.cleanup import EnvFileCleanup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: create tables on startup, dispose engine on shutdown."""
    from orchestrator.runners.monitor import AgentMonitor
    from orchestrator.db.repositories import RunRepository

    await init_db(app.state.engine)

    # Recover active runs on startup - check for dead agents and pause them
    session_factory = app.state.session_factory
    global_config = app.state.global_config

    # Create agent_monitor instance with session_factory (no bound session).
    # Pass the shared lock_manager so on_agent_died can release orphaned locks.
    agent_monitor = AgentMonitor(
        session_factory,
        global_config,
        lock_manager=getattr(app.state, "lock_manager", None),
    )
    app.state.agent_monitor = agent_monitor

    try:
        # Check all ACTIVE runs and pause those with dead agents
        # Each on_agent_died call creates its own session and commits
        paused_runs = await agent_monitor.recover_active_runs_on_startup()
        if paused_runs:
            logger.info(f"Startup recovery: moved {len(paused_runs)} runs to PAUSED (dead agents)")
        else:
            logger.info("Startup recovery: no dead agents found")

        # Re-spawn executor loops for ACTIVE runs whose agents are still alive.
        # After a server reload, the asyncio tasks that drive the agent loop are
        # lost even though the agent subprocess may still be running. Without
        # re-spawning, these runs are orphaned: the agent finishes but nobody
        # handles the next phase (verification, next task, run completion).
        if hasattr(app.state, "agent_executor"):
            from orchestrator.config.enums import AgentRunnerType as _AT

            executor = app.state.agent_executor
            async with session_factory() as session:
                from orchestrator.db.repositories import RunRepository as _RR

                repo = _RR(session)
                active_runs = await repo.list_by_status(RunStatus.ACTIVE)

            for run in active_runs:
                if run.agent_type and run.agent_type in (
                    _AT.CLI_SUBPROCESS,
                    _AT.OPENHANDS_LOCAL,
                    _AT.OPENHANDS_DOCKER,
                    _AT.CODEX_SERVER,
                    _AT.CLAUDE_SDK,
                ):
                    if not executor.is_running(run.id):
                        spawned = executor.spawn_for_run(run.id, run.agent_type, run.agent_config)
                        if spawned:
                            logger.info(
                                f"Startup recovery: re-spawned executor loop for "
                                f"active run {run.id} ({run.agent_type.value})"
                            )

            # Auto-resume runs that were paused due to server shutdown.
            # When the server reloads, it cancels all running executor tasks and
            # marks those runs as paused with reason "server_shutdown". On the next
            # startup we restore them to ACTIVE and re-spawn the executor loop so
            # they continue from where they left off without user intervention.
            async with session_factory() as session:
                from orchestrator.db.repositories import RunRepository as _RR2

                repo2 = _RR2(session)
                paused_runs_all = await repo2.list_by_status(RunStatus.PAUSED)
                shutdown_runs = [
                    r
                    for r in paused_runs_all
                    if r.pause_reason in ("server_shutdown", "agent_not_running_on_startup")
                    and r.agent_type is not None
                    and r.agent_type
                    in (
                        _AT.CLI_SUBPROCESS,
                        _AT.OPENHANDS_LOCAL,
                        _AT.OPENHANDS_DOCKER,
                        _AT.CODEX_SERVER,
                        _AT.CLAUDE_SDK,
                    )
                ]

            for run in shutdown_runs:
                try:
                    # If worktree is enabled but the directory is missing, recreate it
                    # before resuming.  This happens when the server crashed before
                    # cleanup ran or when the directory was removed by the startup
                    # cleanup for an older run.
                    if run.worktree_enabled and run.worktree_path:
                        from pathlib import Path as _Path

                        wt_path = _Path(run.worktree_path)
                        if not wt_path.exists() or not (wt_path / ".git").exists():
                            try:
                                from orchestrator.git.worktree import WorktreeManager as _WTM

                                _repos_dir = global_config.paths.get_repos_path()
                                _wt_dir = global_config.paths.get_worktrees_path()
                                _repo_path = _repos_dir / run.repo_name
                                if _repo_path.is_dir() and run.source_branch:
                                    _wt_mgr = _WTM(_repo_path, _wt_dir)
                                    _wt_mgr.ensure_exists(
                                        run.id,
                                        run.source_branch,
                                        worktree_path=run.worktree_path,
                                    )
                                    logger.info(
                                        f"Startup recovery: recreated missing worktree "
                                        f"for run {run.id}"
                                    )
                                else:
                                    logger.warning(
                                        f"Startup recovery: cannot recreate worktree for "
                                        f"run {run.id} (repo '{run.repo_name}' not found "
                                        f"or no source_branch); skipping auto-resume"
                                    )
                                    continue
                            except Exception as _wt_err:
                                logger.warning(
                                    f"Startup recovery: worktree recreation failed for "
                                    f"run {run.id}: {_wt_err}; skipping auto-resume"
                                )
                                continue

                    async with session_factory() as session:
                        from orchestrator.db.repositories import RunRepository as _RR3
                        from orchestrator.db.event_store import EventStore as _ES3
                        from orchestrator.workflow.event_logger import (
                            PersistentEventEmitter as _PEE3,
                        )
                        from orchestrator.workflow.service import WorkflowService as _WS3
                        from orchestrator.workflow.auto_verify import LocalAutoVerifyRunner as _AVR

                        repo3 = _RR3(session)
                        event_store3 = _ES3(session)
                        emitter3 = _PEE3(event_store3)
                        svc = _WS3(
                            session=session,
                            repo=repo3,
                            event_store=event_store3,
                            event_emitter=emitter3,
                            submit_event_registry=app.state.submit_event_registry,
                            auto_verify_runner=_AVR(),
                            lock_manager=getattr(app.state, "lock_manager", None),
                        )
                        await svc.resume_run(run.id)
                        await session.commit()

                    _agent_type = run.agent_type
                    assert _agent_type is not None  # filtered above
                    spawned = executor.spawn_for_run(run.id, _agent_type, run.agent_config)
                    if spawned:
                        logger.info(
                            f"Startup recovery: auto-resumed run {run.id} "
                            f"({_agent_type.value}) after server shutdown"
                        )
                except Exception as resume_err:
                    logger.warning(
                        f"Startup recovery: failed to auto-resume run {run.id}: {resume_err}"
                    )
    except Exception as e:
        # If recovery fails (e.g., during first startup with no tables),
        # log but don't crash the application
        logger.warning(f"Startup recovery failed: {e}")

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
                    wt_mgr = WorktreeManager(repo_dir, worktrees_dir)
                    total_removed += wt_mgr.cleanup_expired(
                        all_run_ids, run_completed_at, retention
                    )
            if total_removed:
                logger.info(f"Cleaned up {total_removed} expired/orphaned worktree(s)")
    except Exception as e:
        logger.warning(f"Worktree cleanup failed: {e}")

    yield

    # Cancel all running agent background tasks before disposing the engine.
    # Without this, background sessions try to rollback on a closed connection
    # causing "OperationalError: no active connection" during shutdown.
    if hasattr(app.state, "agent_executor"):
        from asyncio import Task as _AsyncTask

        from orchestrator.runners.executor import AgentRunnerExecutor

        executor: AgentRunnerExecutor = app.state.agent_executor
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

    app = FastAPI(title="Orchestrator", version="0.1.0", lifespan=_lifespan)

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

    # Agent tool detector
    from orchestrator.runners.claude_sdk import ClaudeSDKAgent
    from orchestrator.runners.cli import ClaudeCliQuotaAgent
    from orchestrator.runners.codex_server import CodexServerAgent
    from orchestrator.runners.detector import ToolDetector
    from orchestrator.runners.openhands import OpenHandsAgent

    app.state.tool_detector = ToolDetector(
        agents=[OpenHandsAgent(), CodexServerAgent(), ClaudeCliQuotaAgent(), ClaudeSDKAgent()]
    )

    # Shared submit event registry (singleton for cross-service notification)
    from orchestrator.workflow.service import SubmitEventRegistry

    app.state.submit_event_registry = SubmitEventRegistry()

    # Shared lock manager (singleton for task-level pessimistic locking)
    from orchestrator.workflow.locks import InMemoryLockManager

    app.state.lock_manager = InMemoryLockManager()

    # Env file store (manages environment file snapshots)
    app.state.envfile_store = EnvFileStore()

    # Env file lifecycle (manages snapshots across run/task lifecycle)
    app.state.env_lifecycle = EnvFileLifecycle(app.state.envfile_store)

    # Test runner for review workbench test execution
    from orchestrator.review.test_runner import TestRunner

    app.state.test_runner = TestRunner()

    # Agent executor for spawning managed agents (created here so it's available
    # in tests that don't run the lifespan)
    from orchestrator.runners.executor import AgentRunnerExecutor

    # Disable agent spawning for in-memory SQLite (tests), unless explicitly enabled
    if spawn_agents is None:
        spawn_agents = db_path != ":memory:"

    # Note: agent_monitor will be set in lifespan if available, but AgentRunnerExecutor
    # can lazy-initialize it if needed. This avoids circular dependencies.
    app.state.agent_executor = AgentRunnerExecutor(
        session_factory=app.state.session_factory,
        global_config=global_cfg,
        lock_manager=app.state.lock_manager,
        submit_event_registry=app.state.submit_event_registry,
        agent_monitor=getattr(app.state, "agent_monitor", None),
        connection_manager=app.state.connection_manager,
        spawn_agents=spawn_agents,
    )

    register_error_handlers(app)

    # Register routers with auth dependency
    from orchestrator.api.routers.runners import router as agents_router
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
        from orchestrator.db.event_store import EventStore
        from orchestrator.db.repositories import RunRepository
        from orchestrator.mcp.tools import ToolHandler
        from orchestrator.workflow.event_logger import PersistentEventEmitter
        from orchestrator.workflow.service import WorkflowService

        session_factory = self._app.state.session_factory
        env_lifecycle = getattr(self._app.state, "env_lifecycle", None)
        settings = getattr(self._app.state, "settings", None)
        repos_dir = settings.repos_dir if settings else None
        async with session_factory() as session:
            repo = RunRepository(session)
            event_store = EventStore(session)
            emitter = PersistentEventEmitter(event_store)
            service = WorkflowService(
                session=session,
                repo=repo,
                event_store=event_store,
                event_emitter=emitter,
                submit_event_registry=self._app.state.submit_event_registry,
                lock_manager=self._app.state.lock_manager,
                env_lifecycle=env_lifecycle,
            )
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
    from orchestrator.mcp.server import OrchestratorMCPServer

    handler = _SessionPerCallHandler(app)
    mcp_server = OrchestratorMCPServer(handler=handler)  # type: ignore[arg-type]
    app.state.mcp_server = mcp_server

    mcp_asgi = mcp_server.sse_app

    if auth_config.auth_disabled:
        app.mount("/mcp", mcp_asgi)  # type: ignore[arg-type]
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
