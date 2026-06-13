"""Dependency injection for FastAPI endpoints."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, TYPE_CHECKING

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestrator.api.auth import AuthConfig
from orchestrator.api.websocket import ConnectionManager
from orchestrator.config.enums import RoutineSource
from orchestrator.config.global_config import GlobalConfig
from orchestrator.db import (
    RunRepository,
    RunLifecycleProjector,
    SqliteEventStore,
    create_wired_event_store_v2,
)
from orchestrator.workflow import LocalAutoVerifyRunner
from orchestrator.workflow import PersistentEventEmitter
from orchestrator.workflow import (
    EventSignalTransport,
    SignalTransport,
    WorkflowEvent,
)
from orchestrator.workflow.service import WorkflowService
from orchestrator.envfiles.store import EnvFileStore
from orchestrator.envfiles.lifecycle import EnvFileLifecycle
from orchestrator.git import TestRunner
from orchestrator.runners import AgentRunnerExecutor, fetch_codex_models
from orchestrator.runners.agent_detector import ToolDetector

if TYPE_CHECKING:
    from orchestrator.graph_runtime.store import GraphEventStore


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """Get the session factory from app state."""
    return request.app.state.session_factory  # type: ignore[no-any-return]


def get_connection_manager(request: Request) -> ConnectionManager:
    """Get the WebSocket connection manager from app state."""
    return request.app.state.connection_manager  # type: ignore[no-any-return]


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
    returned directly.  Otherwise an ``EventSignalTransport`` backed by the
    events_v2 table is returned.
    """
    override: SignalTransport | None = getattr(request.app.state, "signal_transport", None)
    if override is not None:
        return override
    store = create_wired_event_store_v2(session)
    projector = RunLifecycleProjector()
    return EventSignalTransport(store, projector)


async def get_run_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RunRepository:
    return RunRepository(session)


async def get_event_store_v2(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SqliteEventStore:
    return create_wired_event_store_v2(session)


async def get_graph_store(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> GraphEventStore:
    from orchestrator.graph_runtime.store import GraphEventStore

    return GraphEventStore(session)


def get_env_lifecycle(request: Request) -> EnvFileLifecycle | None:
    """Get the env file lifecycle from app state, if configured."""
    return getattr(request.app.state, "env_lifecycle", None)


def get_global_config(request: Request) -> GlobalConfig:
    """Get global configuration from app state."""
    return request.app.state.global_config  # type: ignore[no-any-return]


def get_lock_manager(request: Request) -> Any:
    """Get the shared lock manager from app state."""
    return request.app.state.lock_manager


async def get_workflow_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    store_v2: Annotated[SqliteEventStore, Depends(get_event_store_v2)],
    env_lifecycle: Annotated[EnvFileLifecycle | None, Depends(get_env_lifecycle)],
    global_config: Annotated[GlobalConfig, Depends(get_global_config)],
    signal_transport: Annotated[SignalTransport, Depends(get_signal_transport)],
    connection_manager: Annotated[ConnectionManager, Depends(get_connection_manager)],
    lock_manager: Annotated[Any, Depends(get_lock_manager)],
) -> WorkflowService:
    emitter = PersistentEventEmitter(store_v2)

    # Wire events to WebSocket broadcast
    manager = connection_manager

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
        event_emitter=emitter,
        auto_verify_runner=LocalAutoVerifyRunner(),
        lock_manager=lock_manager,
        global_config=global_config,
        env_lifecycle=env_lifecycle,
        signal_transport=signal_transport,
        event_store_v2=store_v2,
    )


async def get_event_emitter(
    store_v2: Annotated[SqliteEventStore, Depends(get_event_store_v2)],
    connection_manager: Annotated[ConnectionManager, Depends(get_connection_manager)],
) -> PersistentEventEmitter:
    """Create a PersistentEventEmitter wired to WebSocket broadcast."""
    emitter = PersistentEventEmitter(store_v2)
    manager = connection_manager

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


def get_tool_detector(request: Request) -> ToolDetector:
    """Get the ToolDetector singleton from app state."""
    return request.app.state.tool_detector  # type: ignore[no-any-return]


def get_summary_caches(request: Request) -> dict[str, Any]:
    """Get the run-scoped SummaryCache dict from app state."""
    return request.app.state.summary_caches  # type: ignore[no-any-return]


def get_git_cloner(request: Request) -> "Callable[[str, Path], Awaitable[None]]":
    """Return the git-clone callable.

    In production this runs ``git clone`` as a subprocess.  Tests override it
    by setting ``app.state.git_cloner`` to a no-op or error-raising stub,
    removing any real I/O from the test suite.
    """
    return getattr(request.app.state, "git_cloner", _default_git_clone)  # type: ignore[no-any-return]


async def _default_git_clone(url: str, dest: Path) -> None:
    """Clone *url* into *dest* using a subprocess git clone."""
    import asyncio as _asyncio
    from fastapi import HTTPException as _HTTPException

    proc = await _asyncio.create_subprocess_exec(
        "git",
        "clone",
        url,
        str(dest),
        stdout=_asyncio.subprocess.PIPE,
        stderr=_asyncio.subprocess.PIPE,
    )
    try:
        _, stderr_bytes = await _asyncio.wait_for(proc.communicate(), timeout=60.0)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise _HTTPException(status_code=422, detail="Failed to clone: timed out")
    if proc.returncode != 0:
        stderr = stderr_bytes.decode(errors="replace").strip()
        raise _HTTPException(status_code=422, detail=f"Failed to clone: {stderr}")


def get_codex_models_fn(request: Request) -> "Callable[[], list[str]]":
    """Return the callable used to fetch available Codex model IDs.

    In production this spawns a short-lived ``codex app-server`` subprocess
    via ``fetch_codex_models()``.  Tests override by setting
    ``app.state.codex_models_fn`` to a custom callable, e.g.
    ``lambda: ["gpt-5.3-codex"]``.
    """
    return getattr(request.app.state, "codex_models_fn", fetch_codex_models)  # type: ignore[no-any-return]


def get_current_user() -> str:
    """Get current user for human interaction actions.

    For now, returns a default user. Will be wired to auth system later.
    """
    return "default-user"


def make_service_factory(
    *,
    connection_manager: ConnectionManager | None = None,
    lock_manager: Any | None = None,
    signal_transport_override: SignalTransport | None = None,
    global_config: GlobalConfig | None = None,
    env_lifecycle: EnvFileLifecycle | None = None,
) -> Callable[[AsyncSession], Awaitable[WorkflowService]]:
    """Return a WorkflowService factory for background tasks.

    Unlike ``get_workflow_service`` (request-scoped via ``Depends``), this
    factory is for components that manage their own sessions: the signal
    consumer, stale-run sweeper, startup recovery, and MCP tool handler.

    The returned callable is ``async (session) -> WorkflowService`` and can
    be passed directly to ``SignalConsumer(create_service=...)``.

    Parameters
    ----------
    connection_manager:
        When provided, emitted events are broadcast to WebSocket clients.
    lock_manager:
        Shared pessimistic lock manager, or ``None`` to disable locking.
    signal_transport_override:
        In-memory transport injected by tests.  When ``None`` an
        ``EventSignalTransport`` bound to the session is used instead.
    global_config:
        Application-wide configuration, forwarded to ``WorkflowService``.
    env_lifecycle:
        Env-file lifecycle manager, forwarded to ``WorkflowService``.
    """

    async def _create(session: AsyncSession) -> WorkflowService:
        repo = RunRepository(session)
        store_v2 = create_wired_event_store_v2(session)
        emitter = PersistentEventEmitter(store_v2)

        if connection_manager is not None:
            manager = connection_manager  # narrow type for pyright (closures don't re-check guard)

            def _on_event(event: WorkflowEvent) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast_event(event))
                except RuntimeError:
                    pass

            emitter.add_listener(_on_event)

        transport: SignalTransport = signal_transport_override or EventSignalTransport(
            store_v2, RunLifecycleProjector()
        )

        return WorkflowService(
            session=session,
            repo=repo,
            event_emitter=emitter,
            auto_verify_runner=LocalAutoVerifyRunner(),
            lock_manager=lock_manager,
            signal_transport=transport,
            global_config=global_config,
            env_lifecycle=env_lifecycle,
            event_store_v2=store_v2,
        )

    return _create


def make_workflow_runner(
    executor: AgentRunnerExecutor | None,
) -> Callable[[Any], Awaitable[None]]:
    """Return a workflow runner callback for ``SignalConsumer``.

    Called by the consumer after ``RUN_START`` / ``RESUME`` to set up a
    worktree (if needed) and spawn the agent executor loop.
    """

    async def _run(workflow: Any) -> None:
        if executor is not None:
            await executor.setup_and_spawn(workflow.run_id)

    return _run


def make_workflow_preparer(
    executor: AgentRunnerExecutor | None,
) -> Callable[[str, dict[str, Any] | None], Awaitable[bool]]:
    """Return a callback that prepares run resources before activation."""

    async def _prepare(run_id: str, payload: dict[str, Any] | None = None) -> bool:
        if executor is None:
            return True
        reset_worktree = bool(payload and payload.get("resume_strategy") == "reset_worktree")
        return await executor.prepare_worktree(run_id, reset_worktree=reset_worktree)

    return _prepare


def make_graph_runner(
    session_factory: async_sessionmaker[AsyncSession],
    service_factory: Callable[[AsyncSession], Awaitable[WorkflowService]],
) -> Callable[[str], Awaitable[None]]:
    """Return a graph run driver callback for ``SignalConsumer``."""

    async def _run(run_id: str) -> None:
        from orchestrator.workflow.graph_driver import GraphRunDriver

        driver = GraphRunDriver(session_factory, service_factory)
        await driver.run(run_id)

    return _run
