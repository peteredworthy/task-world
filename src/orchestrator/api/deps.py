"""Dependency injection for FastAPI endpoints."""

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.auth import AuthConfig
from orchestrator.api.websocket import ConnectionManager
from orchestrator.config.enums import RoutineSource
from orchestrator.config.global_config import GlobalConfig
from orchestrator.db import EventStore
from orchestrator.db import RunRepository
from orchestrator.workflow import LocalAutoVerifyRunner
from orchestrator.workflow import PersistentEventEmitter
from orchestrator.workflow import DbSignalTransport, SignalTransport, WorkflowEvent
from orchestrator.workflow.service import WorkflowService
from orchestrator.runners.executor import AgentRunnerExecutor
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.git import TestRunner


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Get the session factory from app state."""
    return request.app.state.session_factory  # type: ignore[no-any-return]


async def get_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session from the app's session factory."""
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        yield session


async def get_signal_transport(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SignalTransport:
    """Return the signal transport for the current request.

    If a transport override is stored in ``app.state.signal_transport`` (e.g.
    an ``InMemorySignalTransport`` injected by tests), that instance is
    returned directly.  Otherwise a ``DbSignalTransport`` bound to the current
    session is created and returned.
    """
    override: SignalTransport | None = getattr(request.app.state, "signal_transport", None)
    if override is not None:
        return override
    return DbSignalTransport(session)


async def get_run_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunRepository:
    return RunRepository(session)


async def get_event_store(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> EventStore:
    return EventStore(session)


def get_env_lifecycle(request: Request) -> EnvFileLifecycle | None:
    """Get the env file lifecycle from app state, if configured."""
    return getattr(request.app.state, "env_lifecycle", None)


def get_global_config(request: Request) -> GlobalConfig:
    """Get global configuration from app state."""
    return request.app.state.global_config  # type: ignore[no-any-return]


async def get_workflow_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    event_store: Annotated[EventStore, Depends(get_event_store)],
    env_lifecycle: Annotated[EnvFileLifecycle | None, Depends(get_env_lifecycle)],
    global_config: Annotated[GlobalConfig, Depends(get_global_config)],
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
        auto_verify_runner=LocalAutoVerifyRunner(),
        lock_manager=request.app.state.lock_manager,
        global_config=global_config,
        env_lifecycle=env_lifecycle,
    )


async def get_event_emitter(
    request: Request,
    event_store: Annotated[EventStore, Depends(get_event_store)],
) -> PersistentEventEmitter:
    """Create a PersistentEventEmitter wired to WebSocket broadcast."""
    emitter = PersistentEventEmitter(event_store)
    manager: ConnectionManager = request.app.state.connection_manager

    def _on_event(event: WorkflowEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast_event(event))
        except RuntimeError:
            pass

    emitter.add_listener(_on_event)
    return emitter


def get_routine_dirs(request: Request) -> list[tuple[Path, RoutineSource]]:
    """Get routine directories from app state."""
    return request.app.state.routine_dirs  # type: ignore[no-any-return]


def get_auth_config(request: Request) -> AuthConfig:
    """Get auth configuration from app state."""
    return request.app.state.auth_config  # type: ignore[no-any-return]


def get_repos_path(request: Request) -> Path:
    """Get the repos directory path from global config."""
    config: GlobalConfig = request.app.state.global_config
    return config.paths.get_repos_path()


def get_worktrees_path(request: Request) -> Path:
    """Get the worktrees directory path from global config."""
    config: GlobalConfig = request.app.state.global_config
    return config.paths.get_worktrees_path()


def get_runner_executor(request: Request) -> AgentRunnerExecutor:
    """Get the agent executor from app state."""
    return request.app.state.runner_executor  # type: ignore[no-any-return]


def get_envfile_store(request: Request) -> EnvFileStore:
    """Get the env file store from app state."""
    return request.app.state.envfile_store  # type: ignore[no-any-return]


def get_test_runner(request: Request) -> TestRunner:
    """Get the TestRunner singleton from app state."""
    return request.app.state.test_runner  # type: ignore[no-any-return]


def get_current_user() -> str:
    """Get current user for human interaction actions.

    For now, returns a default user. Will be wired to auth system later.
    """
    return "default-user"
