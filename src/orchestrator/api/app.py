"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from orchestrator.api.errors import register_error_handlers
from orchestrator.api.websocket import ConnectionManager
from orchestrator.config.enums import RoutineSource
from orchestrator.db.connection import create_engine, create_session_factory, init_db


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: create tables on startup, dispose engine on shutdown."""
    await init_db(app.state.engine)
    yield
    await app.state.engine.dispose()


def create_app(
    db_path: str = "orchestrator.db",
    routine_dirs: list[tuple[Path, RoutineSource]] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        db_path: Path to the SQLite database file.
        routine_dirs: Directories to scan for routines, with their source type.
    """
    app = FastAPI(title="Orchestrator", version="0.1.0", lifespan=_lifespan)

    # Store dependencies on app.state (no global state)
    engine = create_engine(db_path)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.routine_dirs = routine_dirs or []
    app.state.connection_manager = ConnectionManager()

    # Agent tool detector
    from orchestrator.agents.detector import ToolDetector

    app.state.tool_detector = ToolDetector()

    # Shared submit event registry (singleton for cross-service notification)
    from orchestrator.workflow.service import SubmitEventRegistry

    app.state.submit_event_registry = SubmitEventRegistry()

    register_error_handlers(app)

    # Register routers
    from orchestrator.api.routers.agents import router as agents_router
    from orchestrator.api.routers.routines import router as routines_router
    from orchestrator.api.routers.runs import router as runs_router
    from orchestrator.api.routers.tasks import router as tasks_router

    app.include_router(agents_router)
    app.include_router(routines_router)
    app.include_router(runs_router)
    app.include_router(tasks_router)

    # Mount MCP SSE transport at /mcp
    _mount_mcp_sse(app)

    @app.get("/health")
    async def health() -> dict[str, str]:  # type: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.websocket("/ws/runs/{run_id}")
    async def websocket_endpoint(websocket: WebSocket, run_id: str) -> None:  # type: ignore[reportUnusedFunction]
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
            )
            handler = ToolHandler(service)
            return await handler.handle(tool_name, arguments)


def _mount_mcp_sse(app: FastAPI) -> None:
    """Create and mount the MCP SSE transport.

    Creates an OrchestratorMCPServer backed by a session-per-call handler
    and mounts it at ``/mcp``, exposing ``/mcp/sse`` and ``/mcp/messages``.
    """
    from orchestrator.mcp.server import OrchestratorMCPServer

    handler = _SessionPerCallHandler(app)
    mcp_server = OrchestratorMCPServer(handler=handler)  # type: ignore[arg-type]
    app.state.mcp_server = mcp_server
    app.mount("/mcp", mcp_server.sse_app)  # type: ignore[arg-type]
