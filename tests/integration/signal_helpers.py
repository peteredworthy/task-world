"""Shared signal drain helpers for integration tests."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from orchestrator.workflow import LocalAutoVerifyRunner
from orchestrator.workflow import InMemorySignalTransport
from orchestrator.workflow.service import WorkflowService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def drain_signals(
    run_id: str,
    transport: InMemorySignalTransport,
    session: AsyncSession,
    service: WorkflowService,
) -> None:
    """Process all pending signals for a run via RunWorkflow.on_signal().

    Routes through ``build_registry()`` and the actual ``@signal_handler``
    decorated methods (``handle_activity_completed``, ``handle_activity_verified``,
    etc.), which are the canonical transition path used in production.
    """
    from orchestrator.workflow import RunWorkflow

    rw = RunWorkflow(run_id=run_id, transport=transport)
    await rw.on_signal(session, service)


# Type alias for the drain callable used in tests
DrainFn = Callable[[str], Coroutine[Any, Any, None]]


def make_drain_fn(app: FastAPI, transport: InMemorySignalTransport) -> DrainFn:
    """Build a drain callable bound to the app's session factory and transport.

    The returned coroutine function creates a fresh session + WorkflowService
    for each drain call, so it always sees committed state from previous API
    calls through the ASGI transport.

    If the app has a ``submit_event_registry`` on its state, it is passed to
    WorkflowService so that ``submit_for_verification`` fires registered events
    (needed for UserManagedAgent integration tests).

    A ``LocalAutoVerifyRunner`` is always included so that auto-verify commands
    execute during drain (matching the production deps.py wiring).
    """

    async def _drain(run_id: str) -> None:
        registry = getattr(app.state, "submit_event_registry", None)
        async with app.state.session_factory() as session:
            service = WorkflowService(
                session,
                submit_event_registry=registry,
                auto_verify_runner=LocalAutoVerifyRunner(),
            )
            await drain_signals(run_id, transport, session, service)

    return _drain
