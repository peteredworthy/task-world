"""Dependency injection for FastAPI endpoints."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestrator.api.websocket import ConnectionManager
from orchestrator.config.enums import RoutineSource
from orchestrator.db.event_store import EventStore
from orchestrator.db.repositories import RunRepository
from orchestrator.workflow.event_logger import PersistentEventEmitter
from orchestrator.workflow.events import WorkflowEvent
from orchestrator.workflow.service import WorkflowService


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session from the app's session factory."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_run_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunRepository:
    return RunRepository(session)


async def get_event_store(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventStore:
    return EventStore(session)


async def get_workflow_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    event_store: Annotated[EventStore, Depends(get_event_store)],
) -> WorkflowService:
    emitter = PersistentEventEmitter(event_store)

    # Wire events to WebSocket broadcast
    manager: ConnectionManager = request.app.state.connection_manager

    def _on_event(event: WorkflowEvent) -> None:
        """Schedule async WebSocket broadcast from sync listener callback."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast_event(event))
        except RuntimeError:
            pass  # asyncio.get_running_loop() raises when no loop is running (e.g. tests)

    emitter.add_listener(_on_event)

    return WorkflowService(
        session=session,
        repo=repo,
        event_store=event_store,
        event_emitter=emitter,
        submit_event_registry=request.app.state.submit_event_registry,
    )


def get_routine_dirs(request: Request) -> list[tuple[Path, RoutineSource]]:
    """Get routine directories from app state."""
    return request.app.state.routine_dirs  # type: ignore[no-any-return]
