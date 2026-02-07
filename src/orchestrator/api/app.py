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
from orchestrator.config.enums import RoutineSource
from orchestrator.config.global_config import load_global_config
from orchestrator.db.connection import create_engine, create_session_factory, init_db
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.envfiles.cleanup import EnvFileCleanup

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: create tables on startup, dispose engine on shutdown."""
    from orchestrator.agents.monitor import AgentMonitor
    from orchestrator.db.event_store import EventStore
    from orchestrator.db.repositories import RunRepository

    await init_db(app.state.engine)

    # Recover active runs on startup - check for dead agents and pause them
    session_factory = app.state.session_factory
    global_config = app.state.global_config

    # Create agent_monitor instance
    async with session_factory() as session:
        repo = RunRepository(session)
        event_store = EventStore(session)
        agent_monitor = AgentMonitor(repo, event_store, global_config)

        # Store agent_monitor in app.state for later use
        app.state.agent_monitor = agent_monitor

        try:
            # Check all ACTIVE runs and pause those with dead agents
            paused_runs = await agent_monitor.recover_active_runs_on_startup()
            if paused_runs:
                logger.info(
                    f"Startup recovery: moved {len(paused_runs)} runs to PAUSED (dead agents)"
                )
            else:
                logger.info("Startup recovery: no dead agents found")
        except Exception as e:
            # If recovery fails (e.g., during first startup with no tables),
            # log but don't crash the application
            logger.warning(f"Startup recovery failed: {e}")

        # Clean up orphaned env file snapshots
        if hasattr(app.state, "envfile_store"):
            try:
                cleanup = EnvFileCleanup(app.state.envfile_store)
                active_ids: set[str] = {run.id for run in await repo.list_all()}
                removed = cleanup.cleanup_deleted_runs(active_ids)
                if removed:
                    logger.info(f"Cleaned up {removed} orphaned env file snapshot(s)")
            except Exception as e:
                logger.warning(f"Env file cleanup failed: {e}")

    yield
    await app.state.engine.dispose()


def create_app(
    db_path: str | None = None,
    routine_dirs: list[tuple[Path, RoutineSource]] | None = None,
    auth_disabled: bool | None = None,
    jwt_secret: str | None = None,
    spawn_agents: bool | None = None,
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
    """
    # Load global config for defaults
    global_cfg = load_global_config()

    if db_path is None:
        db_path = global_cfg.database.path

    if routine_dirs is None and global_cfg.routines.dirs:
        routine_dirs = [(Path(d), RoutineSource.LOCAL) for d in global_cfg.routines.dirs]

    app = FastAPI(title="Orchestrator", version="0.1.0", lifespan=_lifespan)

    # CORS
    cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
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
    from orchestrator.agents.detector import ToolDetector

    app.state.tool_detector = ToolDetector()

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

    # Agent executor for spawning managed agents (created here so it's available
    # in tests that don't run the lifespan)
    from orchestrator.agents.executor import AgentExecutor

    # Disable agent spawning for in-memory SQLite (tests), unless explicitly enabled
    if spawn_agents is None:
        spawn_agents = db_path != ":memory:"

    app.state.agent_executor = AgentExecutor(
        session_factory=app.state.session_factory,
        global_config=global_cfg,
        lock_manager=app.state.lock_manager,
        submit_event_registry=app.state.submit_event_registry,
        spawn_agents=spawn_agents,
    )

    register_error_handlers(app)

    # Register routers with auth dependency
    from orchestrator.api.routers.agents import router as agents_router
    from orchestrator.api.routers.clarifications import router as clarifications_router
    from orchestrator.api.routers.config import router as config_router
    from orchestrator.api.routers.envfiles import router as envfiles_router
    from orchestrator.api.routers.projects import router as projects_router
    from orchestrator.api.routers.routines import router as routines_router
    from orchestrator.api.routers.runs import router as runs_router
    from orchestrator.api.routers.tasks import router as tasks_router

    auth_deps = [Depends(require_auth)]
    app.include_router(agents_router, dependencies=auth_deps)
    app.include_router(clarifications_router, dependencies=auth_deps)
    app.include_router(config_router, dependencies=auth_deps)
    app.include_router(envfiles_router, dependencies=auth_deps)
    app.include_router(projects_router, dependencies=auth_deps)
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
            handler = ToolHandler(service)
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
