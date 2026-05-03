"""Shared signal drain helpers for integration tests."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI

from orchestrator.workflow import GateBlockedError, LocalAutoVerifyRunner
from orchestrator.workflow import InMemorySignalTransport
from orchestrator.workflow.service import WorkflowService
from orchestrator.workflow import SignalQueue, WorkflowSignal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def drain_signals(
    run_id: str,
    transport: InMemorySignalTransport,
    session: AsyncSession,
    service: WorkflowService,
    *,
    executor: Any | None = None,
) -> None:
    """Process all pending signals for a run.

    Handles lifecycle signals (RUN_START, PAUSE, RESUME, CANCEL) via
    ``service._apply_*`` methods and activity signals (ACTIVITY_COMPLETED,
    ACTIVITY_VERIFIED) via the corresponding service methods.

    This replaces the old RunWorkflow.on_signal() drain path so that all
    signal types — including Phase 3 lifecycle signals — are processed.

    If *executor* is provided, ``executor.setup_and_spawn(run_id)`` is called
    after RUN_START so that worktrees are created and agent loops are spawned
    (mirrors the production consumer's workflow_runner behaviour).
    """
    queue = SignalQueue(transport)
    signals = await queue.drain(run_id)

    for signal in signals:
        if signal.signal_type == WorkflowSignal.RUN_START:
            await service.apply_start_run(run_id)
            if executor is not None:
                await executor.setup_and_spawn(run_id)

        elif signal.signal_type == WorkflowSignal.PAUSE:
            reason: str = (signal.payload or {}).get("reason", "manual_pause")
            error_detail: str | None = (signal.payload or {}).get("error_detail")
            await service.apply_pause_run(run_id, reason=reason, error_detail=error_detail)

        elif signal.signal_type == WorkflowSignal.RESUME:
            from orchestrator.config.enums import AgentRunnerType as _AT

            agent_runner_type: _AT | None = None
            agent_runner_config: dict[str, Any] | None = None
            resume_strategy: str | None = None
            if signal.payload:
                if "agent_runner_type" in signal.payload:
                    agent_runner_type = _AT(signal.payload["agent_runner_type"])
                agent_runner_config = signal.payload.get("agent_runner_config")
                resume_strategy = signal.payload.get("resume_strategy")
            await service.apply_resume_run(
                run_id,
                agent_runner_type=agent_runner_type,
                agent_runner_config=agent_runner_config,
                resume_strategy=resume_strategy,
            )

        elif signal.signal_type == WorkflowSignal.CANCEL:
            cancel_reason: str | None = (signal.payload or {}).get("reason")
            await service.apply_cancel_run(run_id, reason=cancel_reason)

        elif signal.signal_type == WorkflowSignal.ACTIVITY_COMPLETED:
            task_id: str | None = (signal.payload or {}).get("task_id")
            if task_id:
                try:
                    await service.submit_for_verification(run_id, task_id)
                except GateBlockedError:
                    await service.apply_pause_run(run_id, reason="gate_blocked")

        elif signal.signal_type == WorkflowSignal.ACTIVITY_VERIFIED:
            task_id = (signal.payload or {}).get("task_id")
            if task_id:
                await service.complete_verification(run_id, task_id)


# Type alias for the drain callable used in tests
DrainFn = Callable[[str], Coroutine[Any, Any, None]]


def make_drain_fn(app: FastAPI, transport: InMemorySignalTransport) -> DrainFn:
    """Build a drain callable bound to the app's session factory and transport.

    The returned coroutine function creates a fresh session + WorkflowService
    for each drain call, so it always sees committed state from previous API
    calls through the ASGI transport.

    Handles all signal types including Phase 3 lifecycle signals (RUN_START,
    PAUSE, RESUME, CANCEL) as well as activity signals.

    If the app has a ``submit_event_registry`` on its state, it is passed to
    WorkflowService so that ``submit_for_verification`` fires registered events
    (needed for UserManagedAgent integration tests).

    A ``LocalAutoVerifyRunner`` is always included so that auto-verify commands
    execute during drain (matching the production deps.py wiring).
    """

    async def _drain(run_id: str) -> None:
        registry = getattr(app.state, "submit_event_registry", None)
        executor = getattr(app.state, "runner_executor", None)
        async with app.state.session_factory() as session:
            service = WorkflowService(
                session,
                submit_event_registry=registry,
                auto_verify_runner=LocalAutoVerifyRunner(),
                signal_transport=transport,
            )
            await drain_signals(run_id, transport, session, service, executor=executor)

    return _drain
